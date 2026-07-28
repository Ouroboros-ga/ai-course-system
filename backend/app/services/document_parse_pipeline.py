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
import os
import tempfile
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
    from app.platform.document_intelligence.providers.python_docx import (
        PythonDocxProvider,
    )

    registry = ParserRegistry()
    registry.register(NativePptxProvider())
    registry.register(PdfPlumberProvider())
    registry.register(TesseractOcrProvider())
    registry.register(OcrProvider())
    registry.register(PythonDocxProvider())  # Step 3: DOCX native parsing
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

    # 3. Office conversion before probing.  ``.doc`` is not a zip format and
    # cannot be honestly parsed by python-docx; ``.docx`` additionally needs
    # PDF coordinates and image OCR.  Keep the original DOCX bytes for its
    # semantic parser, then make the converted PDF the OCR/rendering source.
    original_docx_content: bytes | None = None
    original_docx_mime = version.mime_type or "application/octet-stream"
    original_docx_filename = object_key
    lower_name = object_key.lower()
    if lower_name.endswith((".doc", ".docx", ".ppt")):
        if lower_name.endswith(".docx"):
            original_docx_content = content
        try:
            from app.platform.document_intelligence.libreoffice_converter import (
                ConversionError,
                libreoffice_converter,
            )
            suffix = os.path.splitext(lower_name)[1] or ".office"
            with tempfile.TemporaryDirectory(prefix="course_convert_") as temp_dir:
                source_path = os.path.join(temp_dir, f"source{suffix}")
                with open(source_path, "wb") as temp_source:
                    temp_source.write(content)
                converted = libreoffice_converter.convert_to_pdf(source_path, output_dir=temp_dir)
                with open(converted.pdf_path, "rb") as converted_file:
                    content = converted_file.read()
            object_key = f"{object_key}.converted.pdf"
            version_mime_for_parse = "application/pdf"
        except ConversionError as exc:
            raise ParsePipelineError(exc.error_code, exc.message) from exc
        except Exception as exc:
            raise ParsePipelineError(
                "CONVERSION_FAILED",
                f"Office conversion failed; please re-upload as PDF or DOCX: {exc}",
            ) from exc
    else:
        version_mime_for_parse = version.mime_type or "application/octet-stream"

    # 4. Probe the actual parsing source (the converted PDF for legacy Office).
    from app.platform.document_intelligence.probe import DocumentProbe
    probe = DocumentProbe()
    probe_result = probe.probe(content, filename=object_key, mime=version_mime_for_parse)

    # 5. 规划解析步骤
    from app.platform.document_intelligence.planner import ParsePlanner
    planner = ParsePlanner()
    # 显式告知 planner 哪些 provider 已注册（默认空 set 会导致 plan.steps 为空）
    registry = _get_parser_registry()
    planner.set_available_providers(list(registry.list_providers()))
    artifact_id = f"art_{uuid.uuid4().hex}"
    plan = planner.plan(probe_result, artifact_id)

    # 6. 查找并执行 Provider
    from app.platform.document_intelligence.source_artifact import SourceArtifact

    source = SourceArtifact.from_bytes(
        content,
        filename=object_key,
        mime=version_mime_for_parse,
        uri=object_key,
    )

    parser_run_id = f"prun_{uuid.uuid4().hex}"
    primary_blocks: list[dict[str, Any]] = []
    enrichment_blocks: list[dict[str, Any]] = []
    units_data: list[dict[str, Any]] = []
    assets_data: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_providers: list[str] = []
    provider_versions: dict[str, str] = {}

    from app.platform.document_intelligence.planner import ParsePriority
    from app.platform.document_intelligence.providers.python_docx import (
        PythonDocxProvider,
        map_docx_output_to_ir,
    )

    # ------------------------------------------------------------------
    # Step 3 组合式解析：消费完整 ParsePlan（PRIMARY + ENRICHMENT）。
    # 旧实现：第一个成功 provider 就 break -> PDF 不 OCR、PPTX 低文本页无补充。
    # 新实现：PRIMARY 收集原生文本块；ENRICHMENT 经 DocumentOcrPort 补充 OCR 块；
    #         若两者都有，用 BlockReconciler 合并（原生优先，OCR 补图片/扫描）。
    # ------------------------------------------------------------------

    def _map_step_output(step_name: str, output):
        """把某个 provider 的 ParserOutput 映射为 IR block dicts。"""
        if step_name == "native-pptx":
            from app.platform.document_intelligence.providers.native_pptx import (
                map_pptx_output_to_ir,
            )
            b, u, a = map_pptx_output_to_ir(output, source, run_id, parser_run_id)
        elif step_name == "pdf-plumber":
            from app.platform.document_intelligence.providers.pdf_plumber import (
                map_pdf_plumber_output_to_ir,
            )
            b, u, a = map_pdf_plumber_output_to_ir(output, source, run_id, parser_run_id)
        elif step_name == "python-docx":
            b, u, a = map_docx_output_to_ir(output, source, run_id, parser_run_id)
        elif step_name in ("tesseract-ocr", "paddleocr"):
            from app.platform.document_intelligence.providers.ocr_provider import (
                map_ocr_output_to_ir,
            )
            b, u, a = map_ocr_output_to_ir(output, source, run_id, parser_run_id)
        else:
            b, u, a = [], [], []
        return b, u, a

    # DOCX semantic pass is intentionally retained in addition to the
    # converted PDF pass.  The former gives headings/tables; the latter gives
    # page coordinates and every-page OCR.  A conversion failure has already
    # produced an auditable task failure above, never a fabricated success.
    if original_docx_content is not None:
        docx_provider = registry.get("python-docx")
        if docx_provider is not None:
            try:
                original_source = SourceArtifact.from_bytes(
                    original_docx_content,
                    filename=original_docx_filename,
                    mime=original_docx_mime,
                    uri=version.file_path,
                )
                output = await docx_provider.parse(original_source, plan)
                used_providers.append("python-docx")
                provider_versions["python-docx"] = output.provider_version
                b, u, a = _map_step_output("python-docx", output)
                primary_blocks.extend(b)
                units_data.extend(u)
                assets_data.extend(a)
            except Exception as exc:
                warnings.append(f"native DOCX semantic pass failed: {type(exc).__name__}: {exc}")

    # PDF policy requires OCR of every page, not a silent first-N subset.
    if probe_result.detected_format.value == "pdf":
        from app.core.config import settings
        page_count = int(probe_result.page_or_slide_count or 0)
        if page_count > settings.PADDLEOCR_MAX_PAGES:
            raise ParsePipelineError(
                "OCR_PAGE_LIMIT_EXCEEDED",
                f"PDF has {page_count} pages; configured OCR limit is {settings.PADDLEOCR_MAX_PAGES}. "
                "Increase PADDLEOCR_MAX_PAGES or split the document; partial OCR is not accepted.",
            )

    # 执行 PRIMARY 步骤（收集原生文本，不 break）
    for step in plan.steps:
        if step.priority != ParsePriority.PRIMARY:
            continue
        provider = registry.get(step.provider_name)
        if provider is None:
            warnings.append(f"primary provider {step.provider_name} not registered; skipped")
            continue
        try:
            output = await provider.parse(source, plan)
            used_providers.append(step.provider_name)
            provider_versions[step.provider_name] = output.provider_version
            b, u, a = _map_step_output(step.provider_name, output)
            if u:
                units_data.extend(u)
            if a:
                assets_data.extend(a)
            primary_blocks.extend(b)
        except Exception as exc:
            warnings.append(
                f"primary provider {step.provider_name} failed: {type(exc).__name__}: {exc}"
            )
            continue

    # 执行 ENRICHMENT 步骤（OCR 补充）。优先用独立 PaddleOCR 服务（DocumentOcrPort），
    # 其次回退到进程内 Tesseract provider。
    for step in plan.steps:
        if step.priority != ParsePriority.ENRICHMENT:
            continue
        # 先尝试经 DocumentOcrPort 调独立 PaddleOCR 服务
        if step.provider_name in ("tesseract-ocr", "paddleocr"):
            ocr_blocks = await _ocr_enrichment_via_port(
                source, plan, step, warnings, run_id, parser_run_id, content,
            )
            if ocr_blocks:
                enrichment_blocks.extend(ocr_blocks)
                provider_versions["paddleocr-service"] = ocr_blocks[0].get(
                    "provider_version", "paddleocr-service"
                )
                continue
            # PDF 的每一页都必须经过独立 PaddleOCR；不能在服务不可用时
            # 静默降级为仅 pdfplumber/Tesseract 的“成功解析”。空白页可以
            # 合法地产生零 OCR block，因此只以服务健康性判断是否失败。
            if "pdf" in (source.mime or "").lower():
                from app.core.config import settings
                from app.platform.document_intelligence.ocr_port import get_ocr_port
                if settings.PADDLEOCR_REQUIRED_FOR_PDF and not get_ocr_port().is_available:
                    raise ParsePipelineError(
                        "OCR_SERVICE_UNAVAILABLE",
                        "PDF requires the configured PaddleOCR service; retry after the service is healthy.",
                    )
        # 回退：进程内 provider（如 TesseractOcrProvider）
        provider = registry.get(step.provider_name)
        if provider is None:
            continue
        try:
            output = await provider.parse(source, plan)
            used_providers.append(step.provider_name)
            provider_versions[step.provider_name] = output.provider_version
            b, _, _ = _map_step_output(step.provider_name, output)
            enrichment_blocks.extend(b)
        except Exception as exc:
            warnings.append(
                f"enrichment provider {step.provider_name} failed: {type(exc).__name__}: {exc}"
            )
            continue

    # 合并：原生文本优先；有 enrichment 时经 BlockReconciler 去重/补充
    if enrichment_blocks and primary_blocks:
        blocks_data = _reconcile_blocks(primary_blocks, enrichment_blocks, run_id, parser_run_id, warnings)
    elif primary_blocks:
        blocks_data = primary_blocks
    else:
        # 无原生文本（如纯图片）：enrichment 即主结果
        blocks_data = enrichment_blocks

    if not blocks_data:
        raise ParsePipelineError(
            "PARSE_FAILED",
            f"All providers failed for {object_key}. Warnings: {warnings}",
        )

    # 6. 写入 DocumentBlock + EvidenceSpan 候选（带解析溯源字段）
    block_count = 0
    evidence_span_count = 0
    combined_provider_version = "|".join(
        f"{k}={v}" for k, v in provider_versions.items()
    ) or "unknown"
    for blk in blocks_data:
        block_type = _map_block_type(blk.get("block_type", "paragraph"))
        text = blk.get("text") or ""
        page_or_slide = blk.get("page_or_slide") or 1
        bbox = blk.get("bbox")
        bbox_dict = bbox if isinstance(bbox, dict) else (
            bbox.__dict__ if hasattr(bbox, "__dict__") and not isinstance(bbox, type) else None
        )
        # 溯源：判断该块来自原生解析还是 OCR 补充
        provenance = blk.get("provenance")
        source_kind = "native"
        confidence = 1.0
        if provenance is not None:
            prov_provider = getattr(provenance, "provider", "") or ""
            if "ocr" in prov_provider or "paddleocr" in prov_provider or "tesseract" in prov_provider:
                source_kind = "ocr"
            conf = getattr(provenance, "confidence", None)
            if conf is not None:
                try:
                    confidence = float(conf)
                except (TypeError, ValueError):
                    confidence = 0.0
        else:
            # enrichment-only blocks（无 provenance 字段）按 OCR 处理
            if not primary_blocks and enrichment_blocks:
                source_kind = "ocr"
                confidence = 0.0

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
            material_version_id=material_version_id,
            page_or_slide=int(page_or_slide),
            source_kind=source_kind,
            confidence=confidence,
            provider_version=combined_provider_version,
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
                text_snippet=text[:500],
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


async def _ocr_enrichment_via_port(
    source,
    plan,
    step,
    warnings: list[str],
    run_id: str,
    parser_run_id: str,
    source_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    """经 DocumentOcrPort 调独立 PaddleOCR 服务，做 OCR enrichment。

    渲染源文档的指定页为图片，逐页调 OCR 服务，返回 IR block dicts。
    若 OCR 服务不可用（UnavailableOcrPort / 服务 503 / 超时），返回空列表，
    由调用方回退到进程内 Tesseract provider；不伪造输出。

    ``source`` 需有 ``uri``（对象存储 object_key）以便读取字节。
    """
    blocks: list[dict[str, Any]] = []
    try:
        from app.platform.document_intelligence.ocr_port import (
            get_ocr_port, OcrUnavailable,
        )
        port = get_ocr_port()
        if not port.is_available:
            warnings.append("OCR service unavailable via DocumentOcrPort; will try in-process fallback")
            return []

        # A DOC/DOCX/PPT conversion produces transient PDF bytes that are not
        # an object-storage key. Prefer the pipeline-provided bytes; ordinary
        # sources still use the durable object key.
        if source_bytes is not None:
            content_bytes = source_bytes
        else:
            from app.services.object_storage import get_object_storage
            try:
                content_bytes = get_object_storage().get(source.uri)
            except Exception as exc:
                warnings.append(f"OCR enrichment: could not read source {source.uri}: {exc}")
                return []

        # 确定要 OCR 的页码（来自 plan step config）
        target_pages = step.config.get("pages", [1]) if step.config else [1]

        # 若源是 PDF，用 ocr_pdf；否则按图片逐页 ocr_image
        mime = (source.mime or "").lower()
        if "pdf" in mime:
            try:
                result = port.ocr_pdf(
                    content_bytes, pages=target_pages,
                    max_pages=len(target_pages) or 50,
                )
            except OcrUnavailable as exc:
                warnings.append(f"OCR service ocr_pdf failed: {exc.error_code}: {exc.message}")
                return []
        else:
            # 图片型 PPT 页或其他图片：逐页 OCR。此处 content_bytes 是整个文件；
            # 图片型 PPT 的逐页渲染由 planner/preprobe 决定页范围，简化为整文件一次 OCR。
            try:
                result = port.ocr_image(content_bytes, page=int(target_pages[0]) if target_pages else 1)
            except OcrUnavailable as exc:
                warnings.append(f"OCR service ocr_image failed: {exc.error_code}: {exc.message}")
                return []

        # 把 OcrResult 转成 IR block dicts（与 map_ocr_output_to_ir 同形）
        from app.platform.document_intelligence.contracts import (
            BoundingBox, CoordinateSpace,
        )
        from app.platform.document_intelligence.document_ir.models import Provenance
        idx = 0
        for page in result.pages:
            for blk in page.blocks:
                bbox = None
                if blk.bbox and len(list(blk.bbox)) == 4:
                    try:
                        bbox = BoundingBox(
                            x0=round(float(blk.bbox[0]), 6),
                            y0=round(float(blk.bbox[1]), 6),
                            x1=round(float(blk.bbox[2]), 6),
                            y1=round(float(blk.bbox[3]), 6),
                            coordinate_space=CoordinateSpace.NORMALIZED,
                        )
                    except (ValueError, TypeError):
                        bbox = None
                text = blk.text or ""
                provenance = Provenance(
                    artifact_id=source.artifact_id,
                    run_id=run_id,
                    parser_run_id=parser_run_id,
                    provider="paddleocr-service",
                    raw_locator=f"pages/{page.page}/blocks/{idx}",
                    page_or_slide=page.page,
                    bbox=bbox,
                    confidence=blk.confidence,
                )
                blocks.append({
                    "block_id": f"blk_ocr_p{page.page}_b{idx}",
                    "block_type": "paragraph",
                    "text": text,
                    "page_or_slide": page.page,
                    "bbox": bbox,
                    "char_start": 0,
                    "char_end": len(text),
                    "order_index": idx,
                    "provenance": provenance,
                    "provider_version": result.provider_version,
                })
                idx += 1
        return blocks
    except Exception as exc:
        warnings.append(f"OCR enrichment via port failed: {type(exc).__name__}: {exc}")
        return []


def _reconcile_blocks(
    primary_blocks: list[dict[str, Any]],
    enrichment_blocks: list[dict[str, Any]],
    run_id: str,
    parser_run_id: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """用 BlockReconciler 合并原生文本块与 OCR 块。

    原生文本优先保留；OCR 补充图片/扫描文本；通过内容坐标去重避免双重文本。
    Reconciler 输入是 DocumentIR，需把 block dicts 转成 Block 对象再合并。
    """
    if not enrichment_blocks:
        return primary_blocks
    try:
        from app.platform.document_intelligence.reconciliation import BlockReconciler
        from app.platform.document_intelligence.document_ir.models import (
            DocumentIR, ContentBlock, Provenance,
        )
        from app.platform.document_intelligence.contracts import (
            BoundingBox, CoordinateSpace,
        )

        def _to_ir(blocks: list[dict[str, Any]]) -> DocumentIR:
            ir_blocks = []
            for b in blocks:
                bbox = b.get("bbox")
                ir_bbox = None
                if bbox is not None and not isinstance(bbox, dict):
                    try:
                        ir_bbox = BoundingBox(
                            x0=float(getattr(bbox, "x0", 0)),
                            y0=float(getattr(bbox, "y0", 0)),
                            x1=float(getattr(bbox, "x1", 0)),
                            y1=float(getattr(bbox, "y1", 0)),
                            coordinate_space=CoordinateSpace.NORMALIZED,
                        )
                    except Exception:
                        ir_bbox = None
                prov = b.get("provenance") or Provenance(
                    artifact_id="",
                    run_id=run_id,
                    parser_run_id=parser_run_id,
                    provider="unknown",
                    raw_locator="",
                    page_or_slide=int(b.get("page_or_slide", 1) or 1),
                    bbox=ir_bbox,
                    confidence=None,
                )
                ir_blocks.append(ContentBlock(
                    block_id=b.get("block_id", f"blk_{id(b)}"),
                    block_type=b.get("block_type", "paragraph"),
                    text=b.get("text", ""),
                    page_or_slide=int(b.get("page_or_slide", 1) or 1),
                    bbox=ir_bbox,
                    order_index=b.get("order_index", 0),
                    provenance=prov,
                ))
            return DocumentIR(
                document_id="reconcile",
                artifact_id="reconcile",
                blocks=tuple(ir_blocks),
                units=(),
                assets=(),
                warnings=(),
            )

        primary_ir = _to_ir(primary_blocks)
        enrichment_ir = _to_ir(enrichment_blocks)
        reconciler = BlockReconciler()
        result = reconciler.reconcile(primary_ir, enrichment_ir, primary_priority=True)

        # 转回 block dicts（保留原生块的原结构，补充 OCR 新块）
        out: list[dict[str, Any]] = []
        for b in result.blocks:
            # 若该 block 来自 primary（按 block_id 匹配），保留原 dict
            match = next((pb for pb in primary_blocks if pb.get("block_id") == b.block_id), None)
            if match is not None:
                out.append(match)
            else:
                # 来自 enrichment 的新块
                prov = getattr(b, "provenance", None)
                out.append({
                    "block_id": b.block_id,
                    "block_type": getattr(b, "block_type", "paragraph"),
                    "text": getattr(b, "text", "") or "",
                    "page_or_slide": getattr(b, "page_or_slide", 1) or 1,
                    "bbox": getattr(b, "bbox", None),
                    "char_start": 0,
                    "char_end": len(getattr(b, "text", "") or ""),
                    "order_index": getattr(b, "order_index", len(out)),
                    "provenance": prov,
                })
        return out
    except Exception as exc:
        warnings.append(
            f"BlockReconciler failed; falling back to primary+enrichment concat: {exc}"
        )
        # 降级：原生优先，enrichment 全量追加（不去重）
        return primary_blocks + enrichment_blocks


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
