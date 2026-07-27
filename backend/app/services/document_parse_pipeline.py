"""P0-4 真实 DocumentIR/OCR/图谱构建流水线。

由 document_parse_handler 调用，串联：
1. 从 SourceMaterialVersion 读取 object_key
2. 从对象存储读取文件内容
3. DocumentProbe 探测格式
4. ParsePlanner 规划解析步骤
5. ParserRegistry 查找 Provider
6. Provider.parse 解析
7. map_*_output_to_ir 生成 DocumentIR blocks
8. 写入 DocumentBlock / EvidenceSpan / GraphCandidateBatch

设计要点：
- 真实 Provider 不可用时降级到 Fake Provider（保证端到端流程可用）
- 解析失败必须返回结构化错误，不伪装成功
- EvidenceSpan 候选基于规则抽取（每个非空 text block 生成一个候选）
- GraphCandidateBatch 自动创建并标记 succeeded
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.course_build_model import SourceMaterialVersion
from app.models.document_parse_model import (
    DocumentBlock,
    DocumentParseRun,
    EvidenceSpan,
    GraphCandidateBatch,
    ParseRunStatus,
)
from app.services.document_parse_service import (
    document_parse_service,
    graph_candidate_service,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider 注册表（懒加载，避免导入时副作用）
# ---------------------------------------------------------------------------


_PARSER_REGISTRY = None


def _get_parser_registry():
    """获取 ParserRegistry 单例，注册内置 Provider。

    P1-3: 用真实 Provider 替换 fake 实现：
    - NativePptxProvider: 真实 PPTX 解析（python-pptx）
    - PdfPlumberProvider: 真实 PDF 解析（pdfplumber，CPU-only）
    - TesseractOcrProvider: 真实 OCR（pytesseract，CPU-only）
    - OcrProvider: PaddleOCR 占位（GPU，未启用）

    所有 Provider 在依赖不可用时抛 ParseUnavailableError，绝不返回伪造结果。
    """
    global _PARSER_REGISTRY
    if _PARSER_REGISTRY is not None:
        return _PARSER_REGISTRY

    from app.platform.document_intelligence.registry import ParserRegistry
    from app.platform.document_intelligence.providers.native_pptx import NativePptxProvider
    from app.platform.document_intelligence.providers.pdf_plumber import PdfPlumberProvider
    from app.platform.document_intelligence.providers.ocr_provider import (
        TesseractOcrProvider,
        OcrProvider,
    )

    registry = ParserRegistry()
    registry.register(NativePptxProvider())
    registry.register(PdfPlumberProvider())
    registry.register(TesseractOcrProvider())
    registry.register(OcrProvider())
    _PARSER_REGISTRY = registry
    return registry


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def run_parse_pipeline(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    material_id: str,
    material_version_id: Optional[str],
    pipeline: str = "full",
    stale_strategy: str = "mark_stale",
) -> tuple[int, int, int]:
    """执行真实解析流水线，返回 (block_count, evidence_span_count, graph_candidate_count)。

    失败时抛 ParsePipelineError，由 handler 捕获并转为 mark_failed。
    """
    # 0. 读取 parse_run，获取 initiated_by（用于 GraphCandidateBatch）
    parse_run = session.exec(
        select(DocumentParseRun).where(
            DocumentParseRun.run_id == run_id,
            DocumentParseRun.course_id == course_id,
        )
    ).first()
    if parse_run is None:
        raise ParsePipelineError(
            "VALIDATION_FAILED",
            f"DocumentParseRun not found: run_id={run_id}, course_id={course_id}",
        )
    initiated_by = parse_run.initiated_by or 0

    # 1. 读取 SourceMaterialVersion
    version = _resolve_material_version(
        session, course_id=course_id, version_id=material_version_id,
    )
    object_key = version.file_path
    if not object_key:
        raise ParsePipelineError(
            "SOURCE_UNAVAILABLE",
            f"SourceMaterialVersion {version.version_id} has no file_path (object_key)",
        )

    # 2. 从对象存储读取文件内容
    from app.services.object_storage import get_object_storage
    storage = get_object_storage()
    try:
        content = storage.get(object_key)
    except FileNotFoundError as exc:
        raise ParsePipelineError(
            "SOURCE_UNAVAILABLE",
            f"Object not found in storage: {object_key}: {exc}",
        ) from exc
    except Exception as exc:
        raise ParsePipelineError(
            "SOURCE_UNAVAILABLE",
            f"Failed to read object {object_key}: {exc}",
        ) from exc

    # 3. 探测格式
    from app.platform.document_intelligence.probe import DocumentProbe
    probe = DocumentProbe()
    probe_result = probe.probe(content, filename=object_key, mime=version.mime_type or "")

    # 4. 规划解析步骤
    from app.platform.document_intelligence.planner import ParsePlanner
    planner = ParsePlanner()
    # 显式告知 planner 哪些 provider 已注册（默认空 set 会导致 plan.steps 为空）
    registry = _get_parser_registry()
    planner.set_available_providers(list(registry.list_providers()))
    artifact_id = f"art_{uuid.uuid4().hex}"
    plan = planner.plan(probe_result, artifact_id)

    # 5. 查找并执行 Provider
    from app.platform.document_intelligence.source_artifact import SourceArtifact

    source = SourceArtifact.from_bytes(
        content,
        filename=object_key,
        mime=version.mime_type or "application/octet-stream",
        uri=object_key,
    )

    parser_run_id = f"prun_{uuid.uuid4().hex}"
    blocks_data: list[dict[str, Any]] = []
    units_data: list[dict[str, Any]] = []
    assets_data: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_provider: str = ""

    # 按优先级尝试每个 step 的 provider
    for step in plan.steps:
        provider = registry.get(step.provider_name)
        if provider is None:
            warnings.append(f"provider {step.provider_name} not registered; skipped")
            continue
        try:
            output = await provider.parse(source, plan)
            used_provider = step.provider_name
            # 调用对应的 IR mapper
            if step.provider_name == "native-pptx":
                from app.platform.document_intelligence.providers.native_pptx import (
                    map_pptx_output_to_ir,
                )
                blocks_data, units_data, assets_data = map_pptx_output_to_ir(
                    output, source, run_id, parser_run_id,
                )
            elif step.provider_name == "pdf-plumber":
                from app.platform.document_intelligence.providers.pdf_plumber import (
                    map_pdf_plumber_output_to_ir,
                )
                blocks_data, units_data, assets_data = map_pdf_plumber_output_to_ir(
                    output, source, run_id, parser_run_id,
                )
            elif step.provider_name in ("tesseract-ocr", "paddleocr"):
                from app.platform.document_intelligence.providers.ocr_provider import (
                    map_ocr_output_to_ir,
                )
                blocks_data, units_data, assets_data = map_ocr_output_to_ir(
                    output, source, run_id, parser_run_id,
                )
            # 第一个成功的 primary provider 即停止
            break
        except Exception as exc:
            warnings.append(f"provider {step.provider_name} failed: {type(exc).__name__}: {exc}")
            continue

    if not blocks_data:
        raise ParsePipelineError(
            "PARSE_FAILED",
            f"All providers failed for {object_key}. Warnings: {warnings}",
        )

    # 6. 写入 DocumentBlock + EvidenceSpan 候选
    block_count = 0
    evidence_span_count = 0
    for blk in blocks_data:
        block_type = _map_block_type(blk.get("block_type", "paragraph"))
        text = blk.get("text") or ""
        page_or_slide = blk.get("page_or_slide") or 1
        bbox = blk.get("bbox")
        bbox_dict = bbox if isinstance(bbox, dict) else (
            bbox.__dict__ if hasattr(bbox, "__dict__") and not isinstance(bbox, type) else None
        )

        db_block = document_parse_service.add_block(
            session,
            course_id=course_id,
            run_id=run_id,
            document_id=None,
            page_number=int(page_or_slide),
            block_type=block_type,
            text=text,
            bbox=bbox_dict,
            char_start=0,
            char_end=len(text),
            order_index=block_count,
        )
        block_count += 1

        # 自动抽取 EvidenceSpan 候选：非空 text block 生成一个候选
        if text and len(text.strip()) >= 5:
            span = document_parse_service.add_evidence_span(
                session,
                course_id=course_id,
                run_id=run_id,
                block_id=db_block.block_id,
                document_id=None,
                page_number=int(page_or_slide),
                text_snippet=text[:500],  # 截断到 500 字符
                bbox=bbox_dict,
                char_start=0,
                char_end=len(text),
                linked_node_ids=[],
            )
            evidence_span_count += 1

    # 7. 创建 GraphCandidateBatch
    batch = graph_candidate_service.create_batch(
        session,
        course_id=course_id,
        parse_run_id=run_id,
        initiated_by=initiated_by,
    )
    # 简单规则：每个 block 一个节点候选，相邻 block 一条关系候选
    node_count = block_count
    relation_count = max(0, block_count - 1)
    graph_candidate_service.mark_succeeded(
        session,
        batch_id=batch.batch_id,
        course_id=course_id,
        node_candidate_count=node_count,
        relation_candidate_count=relation_count,
    )

    return block_count, evidence_span_count, 1  # graph_candidate_count=1（一个 batch）


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _resolve_material_version(
    session: Session,
    *,
    course_id: int,
    version_id: Optional[str],
) -> SourceMaterialVersion:
    """根据 version_id 解析 SourceMaterialVersion；未指定时取最新的 current。"""
    if version_id:
        stmt = select(SourceMaterialVersion).where(
            SourceMaterialVersion.version_id == version_id,
            SourceMaterialVersion.course_id == course_id,
        )
    else:
        stmt = (
            select(SourceMaterialVersion)
            .where(SourceMaterialVersion.course_id == course_id)
            .order_by(SourceMaterialVersion.created_at.desc())
            .limit(1)
        )
    version = session.exec(stmt).first()
    if version is None:
        raise ParsePipelineError(
            "SOURCE_UNAVAILABLE",
            f"SourceMaterialVersion not found: version_id={version_id}, course_id={course_id}",
        )
    return version


def _map_block_type(ir_block_type: str) -> str:
    """把 DocumentIR block_type 映射到 DocumentBlock.block_type。"""
    mapping = {
        "paragraph": "text",
        "heading": "title",
        "image": "figure_caption",
        "table": "table_cell",
        "unknown": "text",
    }
    return mapping.get(ir_block_type, "text")


class ParsePipelineError(Exception):
    """解析流水线错误，携带 error_code 与 message。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
