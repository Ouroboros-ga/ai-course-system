"""P1-4 tests for EduAgent question source mapping.

Validates that:
1. New mapping candidates default to ``PENDING_REVIEW`` (not ``AUTO_ACCEPTED``).
2. EduAgent ranks candidates by character overlap (ranking signal only).
3. When no LLM API key is configured, the service returns a low-confidence
   fallback candidate (confidence=0.3) so the teacher still sees a hint
   but must review it — no fabricated high confidence.
4. LLM JSON parsing rejects hallucinated candidates not in the input list.
5. ``build_evidence_payload`` produces the expected evidence structure.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.question_bank_model import MappingStatus, QuestionBankItem
from app.services.question_mapping_eduagent import (
    DEFAULT_TOP_K,
    LLM_UNAVAILABLE_CONFIDENCE,
    MIN_OVERLAP_THRESHOLD,
    MAPPING_POLICY_VERSION,
    _parse_llm_response,
    build_evidence_payload,
    eduagent_select_best_evidence,
    mapping_status_for_candidate,
    rank_candidates_by_overlap,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_question(qid: int, text: str, answer: str = "答案") -> QuestionBankItem:
    # 注意：默认 answer 必须是中文，避免 "ans" 等 ASCII 字符引入字符重叠污染
    # （否则 "DNA 是生物遗传物质的载体" 会因 'a','n' 与 "ans" 重叠而误判）
    return QuestionBankItem(
        id=qid,
        question_text=text,
        answer=answer,
        course_id=1,
        is_latest=True,
    )


def _make_doc(doc_id: int, name: str = "doc.pdf", version: str = "v1") -> SimpleNamespace:
    return SimpleNamespace(
        id=doc_id,
        origin_filename=name,
        origin_binary_hash=f"hash_{doc_id}",
        version=version,
    )


def _make_text(text_id: int, page: int, text: str, sort_order: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=text_id,
        page_no=page,
        text=text,
        sort_order=sort_order,
    )


def _selected_texts():
    doc1 = _make_doc(101, "doc1.pdf", "v1")
    doc2 = _make_doc(102, "doc2.pdf", "v1")
    return {
        "art_1": (doc1, [
            _make_text(1, 1, "光合作用是植物利用光能合成有机物的过程。"),
            _make_text(2, 2, "叶绿体是光合作用的主要场所。"),
            _make_text(3, 3, "线粒体是细胞呼吸的场所，与光合作用无关。"),
        ]),
        "art_2": (doc2, [
            _make_text(4, 1, "DNA 是生物遗传物质的载体。"),
            _make_text(5, 2, "光合作用需要叶绿素参与。"),
        ]),
    }


# ---------------------------------------------------------------------------
# Default status
# ---------------------------------------------------------------------------


class TestDefaultStatus:
    def test_default_status_is_pending_review(self) -> None:
        """P1-4 hard requirement: new candidates default to PENDING_REVIEW."""
        assert mapping_status_for_candidate() is MappingStatus.PENDING_REVIEW

    def test_default_status_not_auto_accepted(self) -> None:
        assert mapping_status_for_candidate() is not MappingStatus.AUTO_ACCEPTED

    def test_policy_version_bumped(self) -> None:
        """Policy version must reflect the new LLM-driven mapping."""
        assert MAPPING_POLICY_VERSION == "question-mapping/eduagent-ocr-v1"


# ---------------------------------------------------------------------------
# Candidate ranking
# ---------------------------------------------------------------------------


class TestRankCandidatesByOverlap:
    def test_returns_empty_when_query_empty(self) -> None:
        q = _make_question(1, "", "")
        assert rank_candidates_by_overlap(q, _selected_texts()) == []

    def test_returns_empty_when_no_overlap(self) -> None:
        q = _make_question(1, "量子力学")
        assert rank_candidates_by_overlap(q, _selected_texts()) == []

    def test_ranks_by_overlap_desc(self) -> None:
        """Highest-overlap candidate must come first."""
        q = _make_question(1, "光合作用 叶绿体")
        ranked = rank_candidates_by_overlap(q, _selected_texts())
        assert len(ranked) > 0
        # doc1 page 2 文本 "叶绿体是光合作用的主要场所" 同时包含 "光合作用" 与 "叶绿体"，
        # 字符重叠最高，应排在第一位
        assert ranked[0]["document_id"] == "art_1"
        assert ranked[0]["page"] == 2
        # Verify descending order
        scores = [r["overlap_score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_respects_top_k(self) -> None:
        q = _make_question(1, "光合作用 叶绿体 叶绿素")
        ranked = rank_candidates_by_overlap(q, _selected_texts(), top_k=2)
        assert len(ranked) <= 2

    def test_filters_below_threshold(self) -> None:
        q = _make_question(1, "光合作用")
        ranked = rank_candidates_by_overlap(q, _selected_texts())
        for r in ranked:
            assert r["overlap_score"] >= MIN_OVERLAP_THRESHOLD


# ---------------------------------------------------------------------------
# EduAgent selection (no API key — fallback path)
# ---------------------------------------------------------------------------


class TestEduAgentFallback:
    """When no LLM API key is configured, EduAgent must NOT fabricate confidence."""

    @pytest.fixture(autouse=True)
    def _no_api_key(self, monkeypatch):
        from app.services import question_mapping_eduagent as mod
        # 仅覆盖 Settings 实际存在的字段；OPENAI_API_KEY 不在 Settings 中，
        # 实现侧已用 getattr(settings, "OPENAI_API_KEY", "") 兜底处理
        monkeypatch.setattr(mod.settings, "LLM_API_KEY", "", raising=False)
        monkeypatch.setattr(mod.settings, "QWEN_API_KEY", "", raising=False)
        monkeypatch.setattr(mod.settings, "DOUBAO_API_KEY", "", raising=False)

    def test_returns_low_confidence_fallback(self) -> None:
        q = _make_question(1, "光合作用 叶绿体")
        result = asyncio.run(eduagent_select_best_evidence(q, _selected_texts()))
        assert result is not None
        # Hard requirement: fallback confidence must be the low floor, not
        # a fabricated high value.
        assert result["confidence"] == LLM_UNAVAILABLE_CONFIDENCE
        assert "未配置 API Key" in result["mapping_reason"]

    def test_returns_none_when_no_candidates(self) -> None:
        q = _make_question(1, "量子力学")
        result = asyncio.run(eduagent_select_best_evidence(q, _selected_texts()))
        assert result is None


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    def _candidates(self):
        return [
            {"document_id": "art_1", "document": _make_doc(101),
             "text_id": 1, "page": 1, "text": "光合作用", "overlap_score": 0.8},
            {"document_id": "art_2", "document": _make_doc(102),
             "text_id": 4, "page": 1, "text": "DNA", "overlap_score": 0.4},
        ]

    def test_parses_valid_json(self) -> None:
        content = (
            '{"selected": true, "document_id": "art_1", "page": 1, '
            '"confidence": 0.85, "reason": "题干与候选文本高度匹配"}'
        )
        result = _parse_llm_response(content, self._candidates())
        assert result is not None
        assert result["document_id"] == "art_1"
        assert result["page"] == 1
        assert result["confidence"] == 0.85
        assert "高度匹配" in result["mapping_reason"]

    def test_parses_markdown_fenced_json(self) -> None:
        content = (
            "```json\n"
            '{"selected": true, "document_id": "art_2", "page": 1, '
            '"confidence": 0.6, "reason": "次优候选"}\n'
            "```"
        )
        result = _parse_llm_response(content, self._candidates())
        assert result is not None
        assert result["document_id"] == "art_2"

    def test_returns_none_when_not_selected(self) -> None:
        content = '{"selected": false}'
        result = _parse_llm_response(content, self._candidates())
        assert result is None

    def test_returns_none_for_invalid_json(self) -> None:
        result = _parse_llm_response("not json", self._candidates())
        assert result is None

    def test_returns_none_for_empty_content(self) -> None:
        result = _parse_llm_response("", self._candidates())
        assert result is None

    def test_rejects_hallucinated_candidate(self) -> None:
        """LLM must not invent a document_id not in the candidate list."""
        content = (
            '{"selected": true, "document_id": "art_FAKE", "page": 99, '
            '"confidence": 0.99, "reason": "幻觉"}'
        )
        result = _parse_llm_response(content, self._candidates())
        assert result is None

    def test_clamps_confidence_to_unit_interval(self) -> None:
        content = (
            '{"selected": true, "document_id": "art_1", "page": 1, '
            '"confidence": 1.5, "reason": "高置信度"}'
        )
        result = _parse_llm_response(content, self._candidates())
        assert result is not None
        assert result["confidence"] == 1.0

    def test_clamps_negative_confidence_to_zero(self) -> None:
        content = (
            '{"selected": true, "document_id": "art_1", "page": 1, '
            '"confidence": -0.5, "reason": "低置信度"}'
        )
        result = _parse_llm_response(content, self._candidates())
        assert result is not None
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Evidence payload
# ---------------------------------------------------------------------------


class TestBuildEvidencePayload:
    def test_builds_evidence_and_refs(self) -> None:
        selected = {
            "document_id": "art_1",
            "document": _make_doc(101),
            "page": 2,
            "text": "叶绿体是光合作用的场所。",
            "overlap_score": 0.85,
            "text_id": 7,
            "confidence": 0.9,
            "mapping_reason": "EduAgent 高置信度选择",
        }
        evidence, refs = build_evidence_payload(selected)
        assert len(evidence) == 1
        assert evidence[0]["text_id"] == 7
        assert evidence[0]["page"] == 2
        assert evidence[0]["overlap_score"] == 0.85
        assert evidence[0]["confidence"] == 0.9
        assert refs == ["docling:101:text:7"]
