"""Phase B 题源映射 API

使用统一权限解析器进行课程级权限校验。
- 生成映射: question_mapping.generate (教师触发 OCR+EduAgent)
- 管理映射: question_mapping.manage (教师编辑、锁定、拒绝、重跑)

核心流程：
  教师选择课程+课件范围
  -> OCR 解析教师显式选中的课件
  -> EduAgent 基于题目、答案、OCR页块、课程图谱生成映射
  -> P1-4: 默认 status=pending_review，教师须复核后才能发布
  -> 教师可编辑、锁定、拒绝或重新生成
  -> locked 映射 EduAgent 重跑不可覆盖（教师安全阀门）

不会扫描整个课件目录；OCR 只处理教师显式选择的文件。
"""
from __future__ import annotations

import hashlib
from app.core.time_utils import utcnow_aware
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionSourceMapping,
    QuestionStatus,
    MappingStatus,
)
from app.models.course_model import Course, DoclingDocument, DoclingText
from app.models.document_artifact_model import DocumentArtifact
from app.services.course_access_service import require_course_permission
from app.services.question_mapping_eduagent import (
    MAPPING_POLICY_VERSION,
    build_evidence_payload,
    eduagent_select_best_evidence,
    mapping_status_for_candidate,
)

router = APIRouter(tags=["Phase B 题源映射"])


def _load_selected_texts(
    session: Session,
    course_id: int,
    artifacts: list[DocumentArtifact],
) -> dict[str, tuple[DoclingDocument, list[DoclingText]]]:
    """Resolve selected artifacts to real parsed text without scanning directories."""
    resolved: dict[str, tuple[DoclingDocument, list[DoclingText]]] = {}
    for artifact in artifacts:
        parse_info = artifact.parse_info or {}
        document = None
        parsed_document_id = parse_info.get("docling_document_id")
        if parsed_document_id is not None:
            candidate = session.get(DoclingDocument, parsed_document_id)
            if candidate is not None and candidate.course_id == course_id:
                document = candidate

        candidates = list(session.exec(
            select(DoclingDocument).where(
                DoclingDocument.course_id == course_id,
                DoclingDocument.origin_filename == artifact.file_name,
            ).order_by(DoclingDocument.created_at.desc())
        ).all())
        artifact_hash = parse_info.get("origin_binary_hash") or parse_info.get("content_hash")
        if document is None and artifact_hash:
            matches = [
                candidate for candidate in candidates
                if candidate.origin_binary_hash == artifact_hash
            ]
            if len(matches) == 1:
                document = matches[0]
        if document is None and len(candidates) == 1:
            document = candidates[0]
        if document is None:
            continue
        texts = list(session.exec(
            select(DoclingText).where(
                DoclingText.doc_id == document.id,
            ).order_by(DoclingText.sort_order).limit(5000)
        ).all())
        if texts:
            resolved[artifact.document_id] = (document, texts)
    return resolved


def _best_evidence(
    question: QuestionBankItem,
    selected_texts: dict[str, tuple[DoclingDocument, list[DoclingText]]],
) -> Optional[dict[str, Any]]:
    """P1-4: EduAgent-driven evidence selection (sync wrapper for back-compat).

    Delegates to ``eduagent_select_best_evidence`` which:
    1. Pre-ranks candidates by character overlap (fast deterministic signal).
    2. Calls the LLM to pick the best evidence among the top-K candidates.
    3. Returns a low-confidence fallback when the LLM is unavailable, so
       the teacher still sees a candidate but must review it.

    This sync wrapper is retained for callers that are not inside an
    event loop. The FastAPI ``generate_mappings`` endpoint awaits the
    async coroutine directly.
    """
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        eduagent_select_best_evidence(question, selected_texts)
    )


# ==================== 请求模型 ====================

class GenerateMappingRequest(BaseModel):
    """生成映射请求

    教师显式指定课件范围和题目范围。
    OCR 只处理 document_ids 中列出的文档。
    """
    question_ids: list[int] = Field(
        default_factory=list,
        max_length=500,
        description="题目ID列表(空=课程内所有auto_accepted/teacher_edited)",
    )
    document_ids: list[str] = Field(
        min_length=1,
        max_length=20,
        description="课件文档ID列表(教师显式选择)",
    )
    regenerate: bool = Body(default=False, description="是否强制重新生成(跳过已locked的)")


class UpdateMappingRequest(BaseModel):
    """教师编辑映射"""
    slide_file_name: Optional[str] = Field(None, max_length=500)
    page_start: Optional[int] = Field(None, ge=1)
    page_end: Optional[int] = Field(None, ge=1)
    knowledge_node_ids: Optional[list[int]] = Field(None, max_length=100)
    mapping_reason: Optional[str] = Field(None, max_length=5000)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class MappingStatusUpdateRequest(BaseModel):
    """映射状态更新"""
    status: MappingStatus


# ==================== 题源映射接口 ====================

@router.get("/course/{course_id}")
async def list_mappings(
    course_id: int,
    question_id: Optional[int] = Query(None, description="按题目筛选"),
    status: Optional[MappingStatus] = Query(None, description="按状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的题源映射

    需要 question_mapping.manage 权限(教师)。
    """
    require_course_permission(session, current_user, course_id, "question_mapping.manage")

    statement = select(QuestionSourceMapping).where(
        QuestionSourceMapping.course_id == course_id,
        QuestionSourceMapping.is_latest == True,
    )
    if question_id:
        statement = statement.where(QuestionSourceMapping.question_id == question_id)
    if status:
        statement = statement.where(QuestionSourceMapping.status == status)

    total_statement = statement.with_only_columns(func.count()).order_by(None)
    total = int(session.exec(total_statement).one())
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    items = session.exec(statement).all()

    return unified_response(
        code=200,
        message="获取题源映射成功",
        data={
            "items": [_serialize_mapping(m, session) for m in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.post("/course/{course_id}/generate")
async def generate_mappings(
    course_id: int,
    payload: GenerateMappingRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """生成题源映射候选

    需要 question_mapping.generate 权限。
    OCR 只处理 payload.document_ids 中显式列出的课件。
    EduAgent 生成映射候选，默认 status=auto_accepted。
    locked 映射不可被覆盖(除非 regenerate=True 且映射非locked)。

    这是教师安全阀门：EduAgent 候选默认可信，但教师始终可控。
    """
    require_course_permission(session, current_user, course_id, "question_mapping.generate")
    user_id = int(current_user["user_id"])

    # 获取题目范围
    if payload.question_ids:
        questions = session.exec(
            select(QuestionBankItem).where(
                QuestionBankItem.id.in_(payload.question_ids),
                QuestionBankItem.course_id == course_id,
                QuestionBankItem.is_latest == True,
            )
        ).all()
    else:
        questions = session.exec(
            select(QuestionBankItem).where(
                QuestionBankItem.course_id == course_id,
                QuestionBankItem.is_latest == True,
                QuestionBankItem.status.in_([
                    QuestionStatus.AUTO_ACCEPTED,
                    QuestionStatus.TEACHER_EDITED,
                ]),
            )
        ).all()

    if not questions:
        return unified_response(
            code=200,
            message="没有需要生成映射的题目",
            data={"generated": 0, "skipped_locked": 0},
        )

    # 只解析教师显式选择且属于当前课程的文档，绝不遍历课件目录。
    documents = list(session.exec(
        select(DocumentArtifact).where(
            DocumentArtifact.document_id.in_(payload.document_ids),
            DocumentArtifact.course_id == course_id,
        )
    ).all())
    found_document_ids = {item.document_id for item in documents}
    missing_document_ids = sorted(set(payload.document_ids) - found_document_ids)
    if missing_document_ids:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SELECTED_DOCUMENT_NOT_FOUND",
                "document_ids": missing_document_ids,
            },
        )
    selected_texts = _load_selected_texts(session, course_id, documents)
    if not selected_texts:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SELECTED_DOCUMENT_NOT_PARSED",
                "message": "所选课件尚无可用解析文本，不能生成可信映射",
            },
        )
    artifacts_by_id = {item.document_id: item for item in documents}

    generated = 0
    skipped_locked = 0
    errors = []

    for q in questions:
        # 检查是否已有映射
        existing = session.exec(
            select(QuestionSourceMapping).where(
                QuestionSourceMapping.question_id == q.id,
                QuestionSourceMapping.is_latest == True,
            )
        ).first()

        if existing and existing.status == MappingStatus.LOCKED:
            if not payload.regenerate:
                skipped_locked += 1
                continue
            # locked 映射即使 regenerate=True 也不覆盖（安全阀门）
            skipped_locked += 1
            continue

        # P1-4: 用 EduAgent (LLM + OCR) 选择最佳证据，替代确定性字符重叠匹配
        match = await eduagent_select_best_evidence(q, selected_texts)
        if match is None:
            errors.append({
                "question_id": q.id,
                "reason": "所选课件中没有达到最低阈值的可追溯文本证据，或 EduAgent 判定无可信候选",
            })
            continue

        artifact = artifacts_by_id[match["document_id"]]

        # 生成内容哈希
        content_str = f"{q.question_text}|{q.answer}"
        content_str += (
            f"|{artifact.file_name}|{artifact.document_id}|"
            f"{match['document'].origin_binary_hash or ''}|{MAPPING_POLICY_VERSION}"
        )
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:32]

        # 如果已有映射且内容未变化，跳过
        if existing and existing.content_hash == content_hash:
            continue

        # 标记旧映射为非最新
        if existing:
            existing.is_latest = False
            session.add(existing)

        # P1-4: 用 EduAgent 返回的置信度（已含 LLM 判断或 fallback 0.3）
        confidence = max(0.0, min(0.99, match["confidence"]))
        evidence, evidence_refs = build_evidence_payload(match)
        mapping_reason = match.get("mapping_reason") or (
            "EduAgent+OCR 自动生成，待教师复核"
        )
        mapping = QuestionSourceMapping(
            question_id=q.id,
            course_id=course_id,
            document_id=artifact.document_id,
            slide_file_name=artifact.file_name,
            page_start=match["page"],
            page_end=match["page"],
            ocr_evidence=evidence,
            evidence_refs=evidence_refs,
            knowledge_node_ids=q.knowledge_node_ids or [],
            mapping_reason=mapping_reason,
            confidence=confidence,
            model_version=MAPPING_POLICY_VERSION,
            ocr_version=match["document"].version,
            graph_version="",
            content_hash=content_hash,
            # P1-4: 新候选默认 pending_review，教师须复核后才能发布
            status=mapping_status_for_candidate(),
            version=1 if not existing else existing.version + 1,
            prev_version_id=existing.id if existing else None,
            is_latest=True,
            created_by=user_id,
        )
        session.add(mapping)
        generated += 1

    session.commit()

    return unified_response(
        code=200,
        message=f"生成 {generated} 条映射候选（待教师复核）",
        data={
            "generated": generated,
            "skipped_locked": skipped_locked,
            "total_questions": len(questions),
            "errors": errors,
            "policy_version": MAPPING_POLICY_VERSION,
            "default_status": mapping_status_for_candidate().value,
        },
    )


@router.put("/course/{course_id}/{mapping_id}")
async def update_mapping(
    course_id: int,
    mapping_id: int,
    payload: UpdateMappingRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师编辑映射

    需要 question_mapping.manage 权限。
    教师编辑后状态变为 teacher_edited，生成新版本。
    locked 映射不可编辑（需先解锁）。
    """
    require_course_permission(session, current_user, course_id, "question_mapping.manage")

    mapping = session.get(QuestionSourceMapping, mapping_id)
    if not mapping or mapping.course_id != course_id:
        raise HTTPException(status_code=404, detail="映射不存在或不属于此课程")
    if not mapping.is_latest:
        raise HTTPException(status_code=400, detail="只能编辑最新版本")
    if mapping.status == MappingStatus.LOCKED:
        raise HTTPException(status_code=403, detail="映射已锁定，请先解锁再编辑")

    # 保存旧版本
    if mapping.status == MappingStatus.AUTO_ACCEPTED:
        old = QuestionSourceMapping(
            question_id=mapping.question_id,
            course_id=mapping.course_id,
            document_id=mapping.document_id,
            slide_file_name=mapping.slide_file_name,
            page_start=mapping.page_start,
            page_end=mapping.page_end,
            ocr_evidence=mapping.ocr_evidence,
            evidence_refs=mapping.evidence_refs,
            knowledge_node_ids=mapping.knowledge_node_ids,
            mapping_reason=mapping.mapping_reason,
            confidence=mapping.confidence,
            model_version=mapping.model_version,
            ocr_version=mapping.ocr_version,
            graph_version=mapping.graph_version,
            content_hash=mapping.content_hash,
            status=mapping.status,
            version=mapping.version,
            prev_version_id=mapping.prev_version_id,
            is_latest=False,
            created_by=mapping.created_by,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at,
        )
        session.add(old)
        session.flush()
        mapping.version += 1
        mapping.prev_version_id = old.id

    # 更新字段
    if payload.slide_file_name is not None:
        mapping.slide_file_name = payload.slide_file_name
    if payload.page_start is not None:
        mapping.page_start = payload.page_start
    if payload.page_end is not None:
        mapping.page_end = payload.page_end
    if payload.knowledge_node_ids is not None:
        mapping.knowledge_node_ids = payload.knowledge_node_ids
    if payload.mapping_reason is not None:
        mapping.mapping_reason = payload.mapping_reason
    if payload.confidence is not None:
        mapping.confidence = payload.confidence
    if (
        mapping.page_start is not None
        and mapping.page_end is not None
        and mapping.page_end < mapping.page_start
    ):
        raise HTTPException(status_code=422, detail="page_end 不能小于 page_start")

    mapping.status = MappingStatus.TEACHER_EDITED
    mapping.updated_at = utcnow_aware()
    session.add(mapping)
    session.commit()

    return unified_response(
        code=200,
        message="映射已更新",
        data={"mapping_id": mapping.id, "version": mapping.version},
    )


@router.post("/course/{course_id}/{mapping_id}/status")
async def update_mapping_status(
    course_id: int,
    mapping_id: int,
    payload: MappingStatusUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新映射状态

    需要 question_mapping.manage 权限。
    支持的状态: teacher_edited, rejected, locked, stale
    locked = 教师锁定，EduAgent重跑不可覆盖（安全阀门）
    """
    require_course_permission(session, current_user, course_id, "question_mapping.manage")
    user_id = int(current_user["user_id"])

    mapping = session.get(QuestionSourceMapping, mapping_id)
    if not mapping or mapping.course_id != course_id:
        raise HTTPException(status_code=404, detail="映射不存在或不属于此课程")
    if not mapping.is_latest:
        raise HTTPException(status_code=400, detail="只能更新最新版本")

    new_status = payload.status
    # P1-4: 允许教师显式批准 pending_review -> auto_accepted（不再作为新候选默认值，
    # 但仍可作为教师显式批准后的状态）。其余状态转换保持原安全阀门约束。
    allowed_statuses = {
        MappingStatus.AUTO_ACCEPTED,
        MappingStatus.TEACHER_EDITED,
        MappingStatus.REJECTED,
        MappingStatus.LOCKED,
        MappingStatus.STALE,
        MappingStatus.PENDING_REVIEW,
    }
    if new_status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="不允许手工切换到该映射状态")

    if new_status == MappingStatus.LOCKED:
        mapping.locked_by = user_id
        mapping.locked_at = utcnow_aware()
    elif mapping.status == MappingStatus.LOCKED and new_status != MappingStatus.LOCKED:
        mapping.locked_by = None
        mapping.locked_at = None

    mapping.status = new_status
    mapping.updated_at = utcnow_aware()
    session.add(mapping)
    session.commit()

    return unified_response(
        code=200,
        message=f"映射状态已更新为 {new_status.value}",
        data={"mapping_id": mapping.id, "status": mapping.status.value},
    )


@router.get("/course/{course_id}/{mapping_id}/versions")
async def get_mapping_versions(
    course_id: int,
    mapping_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取映射版本历史

    需要 question_mapping.manage 权限。
    旧映射可追溯。
    """
    require_course_permission(session, current_user, course_id, "question_mapping.manage")

    mapping = session.get(QuestionSourceMapping, mapping_id)
    if not mapping or mapping.course_id != course_id:
        raise HTTPException(status_code=404, detail="映射不存在或不属于此课程")

    versions = []
    current = mapping
    while current:
        versions.append({
            "id": current.id,
            "version": current.version,
            "status": current.status.value,
            "is_latest": current.is_latest,
            "content_hash": current.content_hash,
            "updated_at": current.updated_at.isoformat() if current.updated_at else None,
        })
        if current.prev_version_id:
            current = session.get(QuestionSourceMapping, current.prev_version_id)
        else:
            current = None

    return unified_response(
        code=200,
        message="获取映射版本历史成功",
        data={"versions": versions},
    )


# ==================== 辅助函数 ====================

def _serialize_mapping(m: QuestionSourceMapping, session: Session) -> dict[str, Any]:
    """序列化映射为前端友好的字典"""
    # 获取关联题目信息
    question = session.get(QuestionBankItem, m.question_id)
    return {
        "id": m.id,
        "question_id": m.question_id,
        "question_text": question.question_text if question else "",
        "answer": question.answer if question else "",
        "course_id": m.course_id,
        "document_id": m.document_id,
        "slide_file_name": m.slide_file_name,
        "page_start": m.page_start,
        "page_end": m.page_end,
        "ocr_evidence": m.ocr_evidence,
        "evidence_refs": m.evidence_refs,
        "knowledge_node_ids": m.knowledge_node_ids,
        "mapping_reason": m.mapping_reason,
        "confidence": m.confidence,
        "model_version": m.model_version,
        "ocr_version": m.ocr_version,
        "graph_version": m.graph_version,
        "content_hash": m.content_hash,
        "status": m.status.value,
        "version": m.version,
        "is_latest": m.is_latest,
        "locked_by": m.locked_by,
        "locked_at": m.locked_at.isoformat() if m.locked_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }
