"""P1-5 LLM-driven personalized question generation.

Replaces the placeholder text in ``practice_recommendation_service`` (e.g.
``"[AI 生成草稿 #X] 针对 {purpose} 的题目"``) with a real LLM call that
produces a question + answer + reason tailored to the student's cognitive
state and the course knowledge graph node.

Design:
1. ``resolve_node_context`` — pull the active ``GraphSnapshotRecord`` for
   the course and locate the target node (by ``node_id``). Returns a
   compact ``{name, description, prerequisites}`` dict so the LLM has
   grounded context. Returns ``None`` when no snapshot exists or the
   node is not found — the LLM call still proceeds with generic
   context, but the draft is marked ``insufficient_context``.
2. ``build_generation_prompt`` — assemble (system, user) prompts that
   constrain the LLM to:
   - only use the supplied node context (no fabricated references)
   - emit strict JSON with ``question_text``, ``answer``, ``options``,
     ``difficulty``, ``confidence``, ``reason_codes``, ``mapping_reason``
   - return ``{"generated": false}`` when it cannot produce a trustworthy
     question
3. ``generate_question_via_llm`` — async entry point that calls
   ``llm_client.chat``, parses the response, and returns a dict ready to
   feed into ``QuestionGenerationDraftService.create_draft``.
4. ``generate_question_sync`` — sync wrapper used by the (currently
   synchronous) ``PracticeRecommendationService.create_recommendation``.

Failure handling:
- If no LLM API key is configured, or the LLM call raises, we fall back
  to a deterministic stub that is **clearly marked** as needing teacher
  review (``mapping_reason`` explains the path, ``confidence`` is
  floored at ``LLM_UNAVAILABLE_CONFIDENCE``). The stub never fabricates
  higher confidence.
- The stub question text is intentionally a placeholder template —
  teachers see it and know the LLM was unavailable. We never silently
  pass off a stub as a real LLM-generated question.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

from sqlmodel import Session

from app.common.llm_client import llm_client, Message
from app.core.config import settings
from app.services.graph_production_service import get_active_snapshot

logger = logging.getLogger(__name__)


# Policy version bumped to reflect LLM-driven generation.
GENERATION_POLICY_VERSION = "question-generation/llm-v1"

# Confidence floor for LLM-unavailable fallback drafts. Kept below the
# ``LOW_CONFIDENCE_THRESHOLD`` (0.4) used by the recommendation service
# so these drafts always surface as "needs more evidence".
LLM_UNAVAILABLE_CONFIDENCE = 0.2

# Map purpose codes to human-readable intent for the LLM prompt.
PURPOSE_INTENT = {
    "diagnose": "诊断学生对当前知识点的掌握情况",
    "remediation": "针对学生的薄弱点进行补救练习",
    "hint_withdrawal": "学生过度依赖提示，需训练独立作答",
    "post_explanation": "讲解后立即巩固，验证理解深度",
}


def resolve_node_context(
    session: Session,
    *,
    course_id: int,
    node_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Resolve the target knowledge-graph node for LLM grounding.

    Returns ``None`` when there is no active snapshot or the node cannot
    be located. Callers must tolerate ``None`` — the LLM can still
    attempt a generic question, but the draft will be flagged with
    ``insufficient_context``.
    """
    if node_id is None:
        return None
    try:
        snapshot = get_active_snapshot(session, course_id)
    except Exception:  # pragma: no cover - defensive
        return None
    if snapshot is None:
        return None

    target_id = str(node_id)
    for node in snapshot.nodes or []:
        if not isinstance(node, dict):
            continue
        node_uid = str(node.get("id") or node.get("node_id") or "")
        if node_uid == target_id:
            return {
                "id": node_uid,
                "name": str(node.get("name") or node.get("label") or ""),
                "description": str(node.get("description") or node.get("summary") or ""),
                "aliases": list(node.get("aliases") or []),
                "prerequisites": list(node.get("prerequisites") or []),
            }
    return None


def build_generation_prompt(
    *,
    purpose: str,
    difficulty: str,
    node_context: Optional[dict[str, Any]],
    cognitive_snapshot: dict,
    six_dimensions: dict,
    reason_codes: list,
    question_signals: Optional[list] = None,
) -> tuple[str, str]:
    """Build (system, user) prompts for the LLM question generator."""
    intent = PURPOSE_INTENT.get(purpose, purpose)

    system_prompt = (
        "你是教育题目生成 EduAgent。基于学生的认知状态和当前知识点，生成一道"
        f"用于「{intent}」的题目。\n\n"
        "严格规则：\n"
        "1. 题目必须紧扣知识点描述，不得编造知识点以外的概念\n"
        "2. 答案必须可被教师验证，不得给出模糊或不可判定的答案\n"
        "3. 难度档位：easy/medium/hard，必须与请求一致\n"
        "4. 置信度反映你对题目质量与目标契合度的判断（0.0-1.0）\n"
        "5. 若知识点信息不足或认知数据不足以生成可信题目，返回 {\"generated\": false}\n\n"
        "返回严格 JSON，结构如下：\n"
        "{\n"
        "  \"generated\": true,\n"
        "  \"question_text\": \"题目正文\",\n"
        "  \"answer\": \"标准答案\",\n"
        "  \"options\": [],\n"
        "  \"difficulty\": \"easy|medium|hard\",\n"
        "  \"category\": \"分类标签\",\n"
        "  \"confidence\": 0.0-1.0,\n"
        "  \"reason_codes\": [\"reason1\", \"reason2\"],\n"
        "  \"mapping_reason\": \"为什么这道题适合当前学生（<=200字）\"\n"
        "}\n"
        "只输出 JSON，不要其他文字。"
    )

    context_block: str
    if node_context is None:
        context_block = (
            "知识点信息：未提供（node_id 为空或课程未发布活跃图谱快照）。"
            "请基于通用学科常识生成题目，并在 mapping_reason 中说明上下文不足。"
        )
    else:
        context_block = (
            f"知识点 ID：{node_context['id']}\n"
            f"知识点名称：{node_context['name'] or '（未命名）'}\n"
            f"知识点描述：{node_context['description'] or '（无描述）'}\n"
            f"别名：{', '.join(node_context['aliases']) or '无'}\n"
            f"先修知识点：{', '.join(map(str, node_context['prerequisites'])) or '无'}"
        )

    dims_block = json.dumps(six_dimensions or {}, ensure_ascii=False, indent=2)
    snapshot_block = json.dumps(cognitive_snapshot or {}, ensure_ascii=False, indent=2)

    # 学生近期提问反推信号（来自 derive_question_inference_signals，结构化、不含原文）。
    # 深度标签 recall/apply/analyze 对应 Bloom 层级，inferred_weak=True 时优先基础巩固题。
    student_signals_block = ""
    if question_signals:
        lines = []
        for sig in question_signals:
            concept = sig.get("concept_id") or "课程级"
            count = sig.get("question_count", 0)
            avg_depth = sig.get("avg_inquiry_depth")
            label = sig.get("depth_label_mode") or "未知"
            weak_tag = "（薄弱，优先基础巩固）" if sig.get("inferred_weak") else ""
            depth_str = f"{avg_depth:.2f}" if isinstance(avg_depth, (int, float)) else "无"
            lines.append(f"- 概念 {concept}：提问 {count} 次，平均深度 {depth_str}，深度标签 {label}{weak_tag}")
        student_signals_block = (
            "学生近期提问反推信号如下，出题时据此调整难度与考查角度"
            "（深度标签 recall→基础理解题、apply→应用题、analyze→分析题）：\n"
            + "\n".join(lines)
        )

    parts = [
        context_block,
        f"难度档位：{difficulty}",
        f"推荐目的：{purpose}（{intent}）",
        f"学生认知状态快照：\n{snapshot_block}",
        f"六维诊断：\n{dims_block}",
    ]
    if student_signals_block:
        parts.append(student_signals_block)
    parts.append(f"已有 reason_codes：{reason_codes}")
    parts.append("请基于上述信息生成一道题目。")
    user_prompt = "\n\n".join(parts)
    return system_prompt, user_prompt


def _parse_llm_response(content: str) -> Optional[dict[str, Any]]:
    """Parse the LLM JSON response into a generation payload."""
    if not content:
        return None
    text = content.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "Question-generation LLM returned non-JSON response: %s",
            content[:200],
        )
        return None

    if not result.get("generated", False):
        return None

    question_text = str(result.get("question_text") or "").strip()
    answer = str(result.get("answer") or "").strip()
    if not question_text or not answer:
        logger.warning(
            "Question-generation LLM returned empty question/answer: %s",
            content[:200],
        )
        return None

    raw_conf = result.get("confidence", 0.5)
    try:
        confidence = float(raw_conf)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    options = result.get("options") or []
    if not isinstance(options, list):
        options = []

    difficulty = str(result.get("difficulty") or "medium").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"

    reason_codes = result.get("reason_codes") or []
    if not isinstance(reason_codes, list):
        reason_codes = []

    return {
        "question_text": question_text[:2000],
        "answer": answer[:4000],
        "options": options,
        "difficulty": difficulty,
        "category": str(result.get("category") or "")[:200],
        "confidence": confidence,
        "reason_codes": [str(r) for r in reason_codes][:20],
        "mapping_reason": str(result.get("mapping_reason") or "")[:500],
        "source": "llm",
    }


def _build_fallback_payload(
    *,
    purpose: str,
    difficulty: str,
    node_context: Optional[dict[str, Any]],
    reason_codes: list,
    unavailable_reason: str,
) -> dict[str, Any]:
    """Build a deterministic stub draft when the LLM is unavailable.

    The stub is **clearly marked** so teachers know the LLM was not used.
    Confidence is floored at ``LLM_UNAVAILABLE_CONFIDENCE`` so the draft
    always surfaces as "needs more evidence".
    """
    node_label = "未指定知识点"
    if node_context is not None:
        node_label = node_context.get("name") or f"知识点#{node_context.get('id')}"

    stub_codes = list(reason_codes)
    if "llm_unavailable" not in stub_codes:
        stub_codes.append("llm_unavailable")

    return {
        "question_text": (
            f"[LLM 不可用 - 占位草稿] 针对 {purpose} / {node_label} "
            f"的 {difficulty} 难度题目（待教师替换）"
        ),
        "answer": "[占位答案 - LLM 不可用，待教师完善]",
        "options": [],
        "difficulty": difficulty,
        "category": "",
        "confidence": LLM_UNAVAILABLE_CONFIDENCE,
        "reason_codes": stub_codes,
        "mapping_reason": (
            f"LLM 个性化出题不可用（{unavailable_reason}），"
            "已生成占位草稿供教师替换。占位草稿不可直接对学生发布。"
        ),
        "source": "llm_unavailable_stub",
    }


async def generate_question_via_llm(
    session: Session,
    *,
    course_id: int,
    node_id: Optional[int],
    purpose: str,
    difficulty: str,
    cognitive_snapshot: Optional[dict] = None,
    six_dimensions: Optional[dict] = None,
    reason_codes: Optional[list] = None,
    question_signals: Optional[list] = None,
) -> dict[str, Any]:
    """Async entry point: generate one personalized question via LLM.

    Returns a dict with keys: question_text, answer, options, difficulty,
    category, confidence, reason_codes, mapping_reason, source. The
    caller (``PracticeRecommendationService``) feeds this into
    ``QuestionGenerationDraftService.create_draft``.
    """
    cognitive_snapshot = cognitive_snapshot or {}
    six_dimensions = six_dimensions or {}
    reason_codes = list(reason_codes or [])

    node_context = resolve_node_context(
        session, course_id=course_id, node_id=node_id,
    )

    api_key = (
        getattr(settings, "LLM_API_KEY", "") or ""
        or getattr(settings, "OPENAI_API_KEY", "")
        or getattr(settings, "QWEN_API_KEY", "")
        or getattr(settings, "DOUBAO_API_KEY", "")
    )
    if not api_key:
        return _build_fallback_payload(
            purpose=purpose,
            difficulty=difficulty,
            node_context=node_context,
            reason_codes=reason_codes,
            unavailable_reason="未配置 LLM_API_KEY",
        )

    system_prompt, user_prompt = build_generation_prompt(
        purpose=purpose,
        difficulty=difficulty,
        node_context=node_context,
        cognitive_snapshot=cognitive_snapshot,
        six_dimensions=six_dimensions,
        reason_codes=reason_codes,
        question_signals=question_signals,
    )

    try:
        response = await llm_client.chat(
            [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ],
            temperature=0.4,
            max_tokens=1200,
        )
    except Exception as exc:
        logger.warning(
            "Question-generation LLM call failed (course=%s node=%s): %s",
            course_id, node_id, exc,
        )
        return _build_fallback_payload(
            purpose=purpose,
            difficulty=difficulty,
            node_context=node_context,
            reason_codes=reason_codes,
            unavailable_reason=f"{type(exc).__name__}: {exc}"[:200],
        )

    parsed = _parse_llm_response(response.content)
    if parsed is None:
        # LLM said "cannot generate" or returned unparseable JSON. Fall
        # back to the stub so the recommendation run still produces a
        # draft item, but it is clearly marked for teacher review.
        return _build_fallback_payload(
            purpose=purpose,
            difficulty=difficulty,
            node_context=node_context,
            reason_codes=reason_codes,
            unavailable_reason="LLM 返回无可信生成结果",
        )

    # Augment with course/node context for downstream audit.
    if node_context is not None:
        parsed.setdefault("reason_codes", [])
        if "node_resolved" not in parsed["reason_codes"]:
            parsed["reason_codes"].append("node_resolved")
    else:
        parsed.setdefault("reason_codes", [])
        if "insufficient_context" not in parsed["reason_codes"]:
            parsed["reason_codes"].append("insufficient_context")

    return parsed


def generate_question_sync(
    session: Session,
    *,
    course_id: int,
    node_id: Optional[int],
    purpose: str,
    difficulty: str,
    cognitive_snapshot: Optional[dict] = None,
    six_dimensions: Optional[dict] = None,
    reason_codes: Optional[list] = None,
    question_signals: Optional[list] = None,
) -> dict[str, Any]:
    """Sync wrapper around ``generate_question_via_llm``.

    Used by the synchronous ``PracticeRecommendationService``. Robust
    against an already-running event loop (e.g. when invoked from within
    a FastAPI request handler): we run the coroutine in a **separate
    thread** with its own event loop, so we never collide with the
    caller's loop.
    """
    import concurrent.futures

    async def _runner() -> dict[str, Any]:
        return await generate_question_via_llm(
            session,
            course_id=course_id,
            node_id=node_id,
            purpose=purpose,
            difficulty=difficulty,
            cognitive_snapshot=cognitive_snapshot,
            six_dimensions=six_dimensions,
            reason_codes=reason_codes,
            question_signals=question_signals,
        )

    try:
        # Fast path: no running loop in this thread.
        loop = asyncio.get_event_loop()
        if not loop.is_running():
            return loop.run_until_complete(_runner())
    except RuntimeError:
        pass

    # Slow path: a loop is already running in this thread (e.g. FastAPI
    # TestClient). Run the coroutine in a worker thread that owns its
    # own loop. The session is not shared across threads for writes —
    # the LLM call only reads from it (``resolve_node_context``), and
    # any pending writes were flushed by the caller before invoking us.
    def _thread_runner() -> dict[str, Any]:
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(_runner())
        finally:
            new_loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_thread_runner)
        return future.result()
