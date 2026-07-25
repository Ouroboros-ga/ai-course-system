"""Phase B 题库管理 API

使用统一权限解析器(require_course_permission)进行课程级权限校验。
- 教师管理: question_bank.manage
- 教师发布: question_bank.publish
- 学生检索: question_bank.read (仅published)
- 未归属题目管理: 平台级操作(教师均可)

题库查询严格按课程和发布状态隔离：
  - 学生只能检索 course_id 匹配且 status=published 的题目
  - 教师可管理自己课程的所有题目
  - unassigned 题目不能被学生检索或推荐
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
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
    QuestionAttempt,
    QuestionStatus,
    QuestionType,
    QuestionDifficulty,
    MappingStatus,
)
from app.models.course_model import Course
from app.services.course_access_service import (
    require_course_permission,
    require_platform_permission,
    CourseAccessContext,
)
from app.services.cognitive_service import record_scored_evidence
from app.models.access_control_model import PlatformPermission

router = APIRouter(tags=["Phase B 题库管理"])


def _count_rows(session: Session, statement) -> int:
    count_statement = statement.with_only_columns(func.count()).order_by(None)
    return int(session.exec(count_statement).one())


def _normalize_objective_answer(question_type: QuestionType, value: str) -> str:
    normalized = value.strip().casefold()
    if question_type == QuestionType.MULTI_CHOICE:
        choices = {
            part for part in re.split(r"[,，;；\s]+", normalized) if part
        }
        return "|".join(sorted(choices))
    if question_type == QuestionType.TRUE_FALSE:
        if normalized in {"true", "1", "yes", "y", "对", "正确", "是"}:
            return "true"
        if normalized in {"false", "0", "no", "n", "错", "错误", "否"}:
            return "false"
    return normalized


# ==================== 请求模型 ====================

class QuestionAssignRequest(BaseModel):
    """将题目分配到课程"""
    question_ids: list[int] = Field(min_length=1, max_length=500)
    course_id: int
    knowledge_node_ids: list[int] = Field(default_factory=list, max_length=100)


class QuestionUpdateRequest(BaseModel):
    """教师编辑题目"""
    question_text: Optional[str] = Field(None, min_length=1, max_length=10000)
    answer: Optional[str] = Field(None, max_length=10000)
    options: Optional[dict] = None
    difficulty: Optional[QuestionDifficulty] = None
    knowledge_node_ids: Optional[list[int]] = Field(None, max_length=100)
    prerequisite_node_ids: Optional[list[int]] = Field(None, max_length=100)


class QuestionPublishRequest(BaseModel):
    """发布/下架题目"""
    question_ids: list[int] = Field(min_length=1, max_length=500)
    publish: bool  # True=发布, False=下架


class QuestionSearchRequest(BaseModel):
    """学生检索题目"""
    keyword: Optional[str] = None
    knowledge_node_ids: Optional[list[int]] = None
    difficulty: Optional[QuestionDifficulty] = None
    limit: int = Field(default=20, ge=1, le=100)


class QuestionAttemptGradeRequest(BaseModel):
    """教师对非客观题进行人工评分。"""
    score: float = Field(ge=0.0, le=1.0)
    feedback: str = Field(default="", max_length=5000)


# ==================== 题库管理接口 ====================

@router.get("/unassigned")
async def list_unassigned_questions(
    category: Optional[str] = Query(None, description="按分类筛选"),
    batch_id: Optional[str] = Query(None, description="按导入批次筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出未归属题目(unassigned)

    仅具有平台管理员权限的用户可查看待归属题源池。
    unassigned 题目不能面向学生使用。
    """
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)

    statement = select(QuestionBankItem).where(
        QuestionBankItem.status == QuestionStatus.UNASSIGNED,
        QuestionBankItem.is_latest == True,
    )
    if category:
        statement = statement.where(QuestionBankItem.category == category)
    if batch_id:
        statement = statement.where(QuestionBankItem.import_batch_id == batch_id)

    # 计算总数
    total = _count_rows(session, statement)
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    items = session.exec(statement).all()

    return unified_response(
        code=200,
        message="获取待归属题目成功",
        data={
            "items": [_serialize_question(q, include_answer=True) for q in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/course/{course_id}")
async def list_course_questions(
    course_id: int,
    status: Optional[QuestionStatus] = Query(None, description="按状态筛选"),
    category: Optional[str] = Query(None, description="按分类筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程题库题目

    教师可查看所有状态；学生仅可查看 published。
    题库查询严格按课程和发布状态隔离。
    """
    context = require_course_permission(session, current_user, course_id, "question_bank.read")

    statement = select(QuestionBankItem).where(
        QuestionBankItem.course_id == course_id,
        QuestionBankItem.is_latest == True,
    )

    can_manage = context.allows("question_bank.manage")
    if not can_manage:
        statement = statement.where(QuestionBankItem.status == QuestionStatus.PUBLISHED)
    elif status:
        statement = statement.where(QuestionBankItem.status == status)

    if category:
        statement = statement.where(QuestionBankItem.category == category)

    total = _count_rows(session, statement)
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    items = session.exec(statement).all()

    return unified_response(
        code=200,
        message="获取课程题目成功",
        data={
            "items": [
                _serialize_question(
                    q,
                    include_answer=can_manage,
                )
                for q in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "course_role": context.role.value if context.role else None,
        },
    )


@router.post("/assign")
async def assign_questions_to_course(
    payload: QuestionAssignRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """将未归属题目分配到课程

    需要课程的 question_bank.manage 权限。
    分配后状态变为 auto_accepted（默认可信可发布）。
    """
    context = require_course_permission(
        session, current_user, payload.course_id, "question_bank.manage"
    )

    updated = 0
    not_found = []
    already_assigned = []

    for qid in payload.question_ids:
        item = session.get(QuestionBankItem, qid)
        if not item:
            not_found.append(qid)
            continue
        if item.course_id is not None and item.course_id != payload.course_id:
            already_assigned.append(qid)
            continue

        item.course_id = payload.course_id
        item.status = QuestionStatus.AUTO_ACCEPTED
        item.knowledge_node_ids = payload.knowledge_node_ids
        item.updated_at = datetime.utcnow()
        session.add(item)
        updated += 1

    session.commit()

    return unified_response(
        code=200,
        message=f"成功分配 {updated} 道题目到课程",
        data={
            "updated": updated,
            "not_found": not_found,
            "already_assigned": already_assigned,
        },
    )


@router.put("/course/{course_id}/{question_id}")
async def update_question(
    course_id: int,
    question_id: int,
    payload: QuestionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师编辑题目

    需要课程的 question_bank.manage 权限。
    教师修改后生成新版本，旧版本保留可追溯。
    """
    require_course_permission(session, current_user, course_id, "question_bank.manage")

    item = session.get(QuestionBankItem, question_id)
    if not item or item.course_id != course_id:
        raise HTTPException(status_code=404, detail="题目不存在或不属于此课程")

    # 保存旧版本
    old_item = QuestionBankItem(
        question_text=item.question_text,
        answer=item.answer,
        options=item.options,
        similar_questions=item.similar_questions,
        question_type=item.question_type,
        difficulty=item.difficulty,
        category=item.category,
        match_mode=item.match_mode,
        rule_status=item.rule_status,
        course_id=item.course_id,
        knowledge_node_ids=item.knowledge_node_ids,
        prerequisite_node_ids=item.prerequisite_node_ids,
        status=item.status,
        version=item.version,
        prev_version_id=item.prev_version_id,
        is_latest=False,  # 旧版本标记为非最新
        import_batch_id=item.import_batch_id,
        source_row_index=item.source_row_index,
        generated_by=item.generated_by,
        generation_metadata=item.generation_metadata,
        created_by=item.created_by,
        created_at=item.created_at,
        updated_at=item.updated_at,
        published_at=item.published_at,
        published_by=item.published_by,
    )
    session.add(old_item)
    session.flush()  # 获取old_item.id

    # 更新当前版本
    if payload.question_text is not None:
        item.question_text = payload.question_text
    if payload.answer is not None:
        item.answer = payload.answer
    if payload.options is not None:
        item.options = payload.options
    if payload.difficulty is not None:
        item.difficulty = payload.difficulty
    if payload.knowledge_node_ids is not None:
        item.knowledge_node_ids = payload.knowledge_node_ids
    if payload.prerequisite_node_ids is not None:
        item.prerequisite_node_ids = payload.prerequisite_node_ids

    item.version += 1
    item.prev_version_id = old_item.id
    item.status = QuestionStatus.TEACHER_EDITED
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()

    return unified_response(
        code=200,
        message="题目已更新，旧版本已保留",
        data={
            "question_id": item.id,
            "version": item.version,
            "prev_version_id": old_item.id,
        },
    )


@router.post("/course/{course_id}/publish")
async def publish_questions(
    course_id: int,
    payload: QuestionPublishRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """发布/下架题目

    需要课程的 question_bank.publish 权限。
    仅 auto_accepted、teacher_edited 状态可发布。
    published 题目学生可检索；下架后变为 teacher_edited。
    """
    context = require_course_permission(
        session, current_user, course_id, "question_bank.publish"
    )
    user_id = int(current_user["user_id"])

    updated = 0
    errors = []

    for qid in payload.question_ids:
        item = session.get(QuestionBankItem, qid)
        if not item or item.course_id != course_id:
            errors.append({"question_id": qid, "reason": "题目不存在或不属于此课程"})
            continue

        if payload.publish:
            if item.status not in (QuestionStatus.AUTO_ACCEPTED, QuestionStatus.TEACHER_EDITED, QuestionStatus.PUBLISHED):
                errors.append({"question_id": qid, "reason": f"当前状态 {item.status.value} 不可发布"})
                continue
            mapping = session.exec(
                select(QuestionSourceMapping).where(
                    QuestionSourceMapping.question_id == qid,
                    QuestionSourceMapping.course_id == course_id,
                    QuestionSourceMapping.is_latest == True,
                    QuestionSourceMapping.status.in_([
                        MappingStatus.AUTO_ACCEPTED,
                        MappingStatus.TEACHER_EDITED,
                        MappingStatus.LOCKED,
                    ]),
                )
            ).first()
            if mapping is None or not mapping.evidence_refs:
                errors.append({
                    "question_id": qid,
                    "reason": "缺少已接受且可追溯的题源映射",
                })
                continue
            item.status = QuestionStatus.PUBLISHED
            item.published_at = datetime.utcnow()
            item.published_by = user_id
        else:
            if item.status != QuestionStatus.PUBLISHED:
                errors.append({"question_id": qid, "reason": "题目未发布，无法下架"})
                continue
            item.status = QuestionStatus.TEACHER_EDITED
            item.published_at = None
            item.published_by = None

        item.updated_at = datetime.utcnow()
        session.add(item)
        updated += 1

    session.commit()

    action = "发布" if payload.publish else "下架"
    return unified_response(
        code=200,
        message=f"成功{action} {updated} 道题目",
        data={"updated": updated, "errors": errors},
    )


@router.get("/course/{course_id}/{question_id}/versions")
async def get_question_versions(
    course_id: int,
    question_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取题目版本历史

    需要课程的 question_bank.manage 权限。
    教师修改后生成新版本，旧映射可追溯。
    """
    require_course_permission(session, current_user, course_id, "question_bank.manage")

    item = session.get(QuestionBankItem, question_id)
    if not item or item.course_id != course_id:
        raise HTTPException(status_code=404, detail="题目不存在或不属于此课程")

    # 沿着 prev_version_id 链追溯
    versions = []
    current = item
    while current:
        versions.append({
            "id": current.id,
            "version": current.version,
            "status": current.status.value,
            "is_latest": current.is_latest,
            "updated_at": current.updated_at.isoformat() if current.updated_at else None,
            "question_text": current.question_text[:100] + "..." if len(current.question_text) > 100 else current.question_text,
        })
        if current.prev_version_id:
            current = session.get(QuestionBankItem, current.prev_version_id)
        else:
            current = None

    return unified_response(
        code=200,
        message="获取版本历史成功",
        data={"versions": versions},
    )


@router.post("/course/{course_id}/search")
async def search_course_questions(
    course_id: int,
    payload: QuestionSearchRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生/教师检索课程题库

    先查课程题库(精确检索)；无匹配题时由推荐系统生成草稿(在别处实现)。
    学生仅可检索 published 题目。
    """
    context = require_course_permission(session, current_user, course_id, "question_bank.read")

    statement = select(QuestionBankItem).where(
        QuestionBankItem.course_id == course_id,
        QuestionBankItem.is_latest == True,
    )

    can_manage = context.allows("question_bank.manage")
    if not can_manage:
        statement = statement.where(QuestionBankItem.status == QuestionStatus.PUBLISHED)

    if payload.keyword:
        statement = statement.where(
            QuestionBankItem.question_text.contains(payload.keyword)
        )
    if payload.difficulty:
        statement = statement.where(QuestionBankItem.difficulty == payload.difficulty)
    if payload.knowledge_node_ids:
        # JSON 数组查询: 知识点交集
        for nid in payload.knowledge_node_ids:
            statement = statement.where(
                QuestionBankItem.knowledge_node_ids.contains([nid])
            )

    statement = statement.limit(payload.limit)
    items = session.exec(statement).all()

    return unified_response(
        code=200,
        message="检索课程题库成功",
        data={
            "items": [
                _serialize_question(
                    q,
                    include_answer=can_manage,
                )
                for q in items
            ],
            "total": len(items),
            "has_match": len(items) > 0,
        },
    )


@router.post("/course/{course_id}/{question_id}/attempt")
async def submit_attempt(
    course_id: int,
    question_id: int,
    student_answer: str = Body(..., embed=True, min_length=1, max_length=20_000),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生提交答题记录

    需要 question_bank.read 权限(学生可答题)。
    仅 published 题目可作答。
    """
    context = require_course_permission(session, current_user, course_id, "question_bank.read")
    user_id = int(current_user["user_id"])
    if not context.analytics_eligible:
        raise HTTPException(
            status_code=403,
            detail="仅课程学习者可以提交形成学情证据的答题记录",
        )

    item = session.get(QuestionBankItem, question_id)
    if not item or item.course_id != course_id:
        raise HTTPException(status_code=404, detail="题目不存在或不属于此课程")
    if item.status != QuestionStatus.PUBLISHED:
        raise HTTPException(status_code=403, detail="题目未发布，无法作答")

    normalized_answer = _normalize_objective_answer(
        item.question_type, student_answer
    )
    normalized_expected = _normalize_objective_answer(
        item.question_type, item.answer
    )
    automatically_judged = item.question_type in {
        QuestionType.SINGLE_CHOICE,
        QuestionType.MULTI_CHOICE,
        QuestionType.TRUE_FALSE,
        QuestionType.FILL_BLANK,
    }
    is_correct = (
        normalized_answer == normalized_expected
        if automatically_judged
        else None
    )
    attempt = QuestionAttempt(
        question_id=question_id,
        course_id=course_id,
        student_id=user_id,
        source_event_id=f"qe_{uuid.uuid4().hex}",
        measurement_role="scored_performance",
        question_version=item.version,
        question_content_hash=hashlib.sha256(
            f"{item.version}|{item.question_text}|{item.answer}".encode("utf-8")
        ).hexdigest(),
        student_answer=student_answer,
        is_correct=is_correct,
        score=float(is_correct) if is_correct is not None else None,
        cognitive_context={},
        judged_by="auto" if automatically_judged else "teacher",
        judged_at=datetime.utcnow() if automatically_judged else None,
    )
    session.add(attempt)
    # P3 §四.4：attempt 与评分型证据同事务提交。
    # 旧实现先 commit attempt 再写证据，证据失败时 attempt 已落库导致证据缺失。
    # 改为 flush 让 attempt 获得 id（供 record_scored_evidence 查询使用），
    # 但不提交事务；证据写入后一次性 commit，任一失败则整体回滚保证一致性。
    session.flush()
    session.refresh(attempt)

    record_scored_evidence(session, attempt)
    session.commit()

    return unified_response(
        code=200,
        message="答题记录已提交",
        data={
            "attempt_id": attempt.id,
            "judgement_status": "judged" if automatically_judged else "pending",
            "is_correct": attempt.is_correct,
            "score": attempt.score,
        },
    )


@router.post("/course/{course_id}/attempt/{attempt_id}/grade")
async def grade_attempt(
    course_id: int,
    attempt_id: int,
    payload: QuestionAttemptGradeRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师评分；只能处理当前课程内的答题记录。"""
    require_course_permission(session, current_user, course_id, "submission.review")
    attempt = session.get(QuestionAttempt, attempt_id)
    if attempt is None or attempt.course_id != course_id:
        raise HTTPException(status_code=404, detail="答题记录不存在或不属于此课程")

    item = session.get(QuestionBankItem, attempt.question_id)
    if item is None or item.course_id != course_id:
        raise HTTPException(status_code=409, detail="答题记录关联的题目无效")

    attempt.score = payload.score
    attempt.is_correct = payload.score >= 0.999
    attempt.judged_by = "teacher"
    attempt.judge_feedback = payload.feedback
    attempt.judged_at = datetime.utcnow()
    session.add(attempt)
    # P3 §四.4：attempt 与评分型证据同事务提交。
    # 旧实现先 commit attempt 再写证据，证据失败时 attempt 已落库导致证据缺失。
    # 改为 flush 让 attempt 获得 id（供 record_scored_evidence 查询使用），
    # 但不提交事务；证据写入后一次性 commit，任一失败则整体回滚保证一致性。
    session.flush()
    session.refresh(attempt)

    record_scored_evidence(session, attempt)
    session.commit()

    return unified_response(
        code=200,
        message="答题评分已保存",
        data={
            "attempt_id": attempt.id,
            "score": attempt.score,
            "is_correct": attempt.is_correct,
            "judged_at": attempt.judged_at.isoformat(),
        },
    )


# ==================== 辅助函数 ====================

def _serialize_question(
    q: QuestionBankItem,
    *,
    include_answer: bool,
) -> dict[str, Any]:
    """序列化题目为前端友好的字典"""
    data = {
        "id": q.id,
        "question_text": q.question_text,
        "options": q.options,
        "similar_questions": q.similar_questions,
        "question_type": q.question_type.value,
        "difficulty": q.difficulty.value,
        "category": q.category,
        "match_mode": q.match_mode,
        "rule_status": q.rule_status,
        "course_id": q.course_id,
        "knowledge_node_ids": q.knowledge_node_ids,
        "prerequisite_node_ids": q.prerequisite_node_ids,
        "status": q.status.value,
        "version": q.version,
        "is_latest": q.is_latest,
        "generated_by": q.generated_by,
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "updated_at": q.updated_at.isoformat() if q.updated_at else None,
        "published_at": q.published_at.isoformat() if q.published_at else None,
    }
    if include_answer:
        data["answer"] = q.answer
    return data
