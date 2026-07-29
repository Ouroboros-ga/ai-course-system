"""P1-4 EduAgent-based question source mapping.

Replaces the deterministic character-overlap matcher with an LLM-driven
EduAgent that consumes OCR page blocks + question text + answer and
returns a structured mapping candidate.

Design:
1. ``rank_candidates_by_overlap`` — fast deterministic pre-rank using
   character overlap. Produces top-K candidate (document, page, text)
   triples for the LLM. This is ONLY a ranking signal, not the final
   mapping decision.
2. ``eduagent_select_best_evidence`` — calls ``llm_client.chat`` with a
   constrained JSON prompt. The LLM picks the best evidence among the
   top-K candidates and returns ``{document_id, page, confidence,
   mapping_reason}`` or ``null`` when none is trustworthy.
3. ``mapping_status_for_candidate`` — returns the default status for new
   candidates. P1-4: always ``MappingStatus.PENDING_REVIEW`` (teacher
   must review before publishing). ``auto_accepted`` is no longer the
   default for new candidates.

Failure handling:
- If the LLM call fails, the candidate is still created with
  ``pending_review`` status, low confidence (0.3), and a reason that
  explains the LLM-unavailable path. The deterministic ranking signal
  is preserved in ``ocr_evidence`` so the teacher has context.
- The service never fabricates confidence or skips teacher review.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.common.llm_client import llm_client, Message
from app.core.config import settings
from app.models.question_bank_model import (
    MappingStatus,
    QuestionBankItem,
)
from app.models.course_model import DoclingDocument, DoclingText

logger = logging.getLogger(__name__)


# Policy version bumped to reflect LLM-driven mapping decisions.
MAPPING_POLICY_VERSION = "question-mapping/eduagent-ocr-v1"

# Number of top overlap candidates to send to the LLM.
DEFAULT_TOP_K = 5

# Minimum character-overlap score required to even consider a candidate.
MIN_OVERLAP_THRESHOLD = 0.15

# Confidence floor for LLM-unavailable fallback candidates.
LLM_UNAVAILABLE_CONFIDENCE = 0.3


def _normalized_chars(value: str) -> set[str]:
    """Deterministic character set used only for pre-ranking."""
    return set(re.sub(r"[^\w\u4e00-\u9fff]", "", value.casefold()))


def rank_candidates_by_overlap(
    question: QuestionBankItem,
    selected_texts: dict[str, tuple[DoclingDocument, list[DoclingText]]],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Return the top-K (document, page, text) candidates by char overlap.

    The overlap score is a fast ranking signal only — the LLM makes the
    final selection. Candidates with zero overlap are excluded so the
    LLM is not flooded with irrelevant context.
    """
    query_chars = _normalized_chars(f"{question.question_text} {question.answer}")
    if not query_chars:
        return []

    ranked: list[tuple[float, str, DoclingDocument, DoclingText]] = []
    for document_id, (document, texts) in selected_texts.items():
        for text in texts:
            text_chars = _normalized_chars(text.text)
            if not text_chars:
                continue
            score = len(query_chars & text_chars) / len(query_chars)
            if score >= MIN_OVERLAP_THRESHOLD:
                ranked.append((score, document_id, document, text))

    if not ranked:
        return []

    ranked.sort(
        key=lambda row: (-row[0], row[3].page_no, row[3].sort_order, row[3].id or 0)
    )

    out: list[dict[str, Any]] = []
    for score, document_id, document, text in ranked[:top_k]:
        out.append({
            "document_id": document_id,
            "document": document,
            "text_id": text.id,
            "page": text.page_no,
            "text": text.text[:1000],
            "overlap_score": round(score, 6),
        })
    return out


def _build_llm_prompt(
    question: QuestionBankItem,
    candidates: list[dict[str, Any]],
) -> tuple[str, str]:
    """Build (system, user) prompts for the EduAgent LLM call."""
    system_prompt = (
        "你是题源映射 EduAgent。教师已显式圈定课件范围，OCR 已抽取页面文本块。"
        "你的任务：从下面给出的候选文本块里，挑出最能够支撑题目与答案溯源的那个。"
        "只能基于候选列表选择，不要编造没有给出的页码或文档。\n\n"
        "返回严格 JSON，结构如下：\n"
        "{\n"
        "  \"selected\": true | false,\n"
        "  \"document_id\": \"候选中的 document_id\",\n"
        "  \"page\": 页码整数,\n"
        "  \"confidence\": 0.0-1.0 之间的浮点数,\n"
        "  \"reason\": \"为什么选择该证据（中文，<=200 字）\"\n"
        "}\n"
        "若所有候选都不可信，返回 {\"selected\": false}。"
        "只输出 JSON，不要其他文字。"
    )

    candidate_payload = [
        {
            "candidate_index": i + 1,
            "document_id": c["document_id"],
            "page": c["page"],
            "text": c["text"],
            "overlap_score": c["overlap_score"],
        }
        for i, c in enumerate(candidates)
    ]

    user_prompt = (
        f"题目：{question.question_text}\n"
        f"答案：{question.answer or '（无标准答案）'}\n\n"
        f"候选文本块（按字符重叠度预排序）：\n"
        f"{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def _parse_llm_response(
    content: str,
    candidates: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Parse the LLM JSON response and locate the chosen candidate."""
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
        logger.warning("EduAgent LLM returned non-JSON response: %s", content[:200])
        return None

    if not result.get("selected", False):
        return None

    document_id = result.get("document_id")
    page = result.get("page")
    candidate = next(
        (c for c in candidates
         if c["document_id"] == document_id and c["page"] == page),
        None,
    )
    if candidate is None:
        logger.warning(
            "EduAgent LLM selected unknown candidate: document_id=%s page=%s",
            document_id, page,
        )
        return None

    raw_conf = result.get("confidence", 0.5)
    try:
        confidence = float(raw_conf)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "document_id": candidate["document_id"],
        "document": candidate["document"],
        "page": candidate["page"],
        "text": candidate["text"],
        "overlap_score": candidate["overlap_score"],
        "text_id": candidate["text_id"],
        "confidence": confidence,
        "mapping_reason": str(result.get("reason", ""))[:500],
    }


async def eduagent_select_best_evidence(
    question: QuestionBankItem,
    selected_texts: dict[str, tuple[DoclingDocument, list[DoclingText]]],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> Optional[dict[str, Any]]:
    """Use EduAgent (LLM) to pick the best evidence among ranked candidates.

    Returns a dict with keys: document_id, document, page, text,
    overlap_score, text_id, confidence, mapping_reason — or None when no
    trustworthy candidate exists.

    The LLM call is bounded: if it raises or returns nothing parseable,
    we fall back to the top-1 overlap candidate with a low confidence
    (``LLM_UNAVAILABLE_CONFIDENCE``) so the teacher still sees a hint
    but the candidate is clearly marked as needing review.
    """
    candidates = rank_candidates_by_overlap(
        question, selected_texts, top_k=top_k,
    )
    if not candidates:
        return None

    # Skip the LLM call entirely when no API key is configured. This keeps
    # tests deterministic and avoids silent network failures.
    api_key = (
        getattr(settings, "LLM_API_KEY", "") or ""
        or getattr(settings, "OPENAI_API_KEY", "")
        or getattr(settings, "QWEN_API_KEY", "")
        or getattr(settings, "DOUBAO_API_KEY", "")
    )
    if not api_key:
        top = candidates[0]
        return _build_fallback_candidate(top, reason=(
            "EduAgent LLM 未配置 API Key，按字符重叠度最高候选生成待复核映射；"
            "教师须人工确认后再发布。"
        ))

    system_prompt, user_prompt = _build_llm_prompt(question, candidates)
    try:
        response = await llm_client.chat(
            [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ],
            temperature=0.1,
            max_tokens=800,
        )
    except Exception as exc:
        logger.warning(
            "EduAgent LLM call failed for question %s: %s",
            question.id, exc,
        )
        return _build_fallback_candidate(candidates[0], reason=(
            f"EduAgent LLM 调用失败（{type(exc).__name__}），"
            "按字符重叠度最高候选生成待复核映射；教师须人工确认。"
        ))

    selected = _parse_llm_response(response.content, candidates)
    if selected is None:
        # LLM explicitly said "no trustworthy candidate" — return None so
        # the caller records an error entry instead of fabricating a mapping.
        return None
    return selected


def _build_fallback_candidate(
    top_candidate: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    """Build a low-confidence fallback candidate when the LLM is unavailable."""
    return {
        "document_id": top_candidate["document_id"],
        "document": top_candidate["document"],
        "page": top_candidate["page"],
        "text": top_candidate["text"],
        "overlap_score": top_candidate["overlap_score"],
        "text_id": top_candidate["text_id"],
        "confidence": LLM_UNAVAILABLE_CONFIDENCE,
        "mapping_reason": reason,
    }


def mapping_status_for_candidate() -> MappingStatus:
    """P1-4: New EduAgent candidates default to PENDING_REVIEW.

    ``auto_accepted`` is no longer the default for new candidates. It
    remains valid only for historical rows or for teacher-explicit
    approvals (e.g. bulk-accepting a candidate after review).
    """
    return MappingStatus.PENDING_REVIEW


def build_evidence_payload(selected: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Build (ocr_evidence, evidence_refs) for the QuestionSourceMapping row."""
    evidence = [{
        "text_id": selected["text_id"],
        "page": selected["page"],
        "text": selected["text"][:1000],
        "overlap_score": selected["overlap_score"],
        "confidence": selected["confidence"],
    }]
    evidence_refs = [
        f"docling:{selected['document'].id}:text:{selected['text_id']}",
    ]
    return evidence, evidence_refs
