"""Sentence-level evidence review (Stage 0) tests.

The reviewer deletes near-duplicate, meaningless, and garbled sentences from
each coalesced evidence unit before the controlled prep workflow segments the
corpus.  Review is best-effort: disabled, missing reviewer, a failed batch, or
an empty result must all fall back to the original evidence so the first draft
still builds.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.schemas.controlled_prep import (
    EvidenceReference,
    EvidenceReviewWireItem,
    EvidenceReviewWireResult,
)
from app.services.course_initial_prep_service import InitialCoursePrepService


def asyncio_run(awaitable):
    return asyncio.run(awaitable)


class StubReviewer:
    """Controllable in-memory reviewer mirroring ``PrepLLMAdapter``."""

    def __init__(self, *, items: list[list[str]] | None = None, error: Exception | None = None):
        self._items = items
        self._error = error
        self.calls: list[list[EvidenceReference]] = []

    async def review_evidence(self, evidence, *, run_id: str = "", trace_id: str = ""):
        self.calls.append(list(evidence))
        if self._error is not None:
            raise self._error
        return EvidenceReviewWireResult(items=[
            EvidenceReviewWireItem(sentences=list(sentences))
            for sentences in (self._items or [])
        ])


def _unit(
    text: str,
    *,
    evidence_id: str = "ev_1",
    page: int = 1,
    role: str = "primary_courseware",
    material: str = "mat-1",
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=evidence_id,
        text=text,
        page=page,
        page_end=page,
        block_id=f"block_{evidence_id}",
        source_block_ids=[f"block_{evidence_id}"],
        material_version_id=material,
        material_role=role,
    )


def _service(reviewer: object | None = None) -> InitialCoursePrepService:
    return InitialCoursePrepService(evidence_reviewer=reviewer)


def test_review_deletes_near_duplicate_and_meaningless_sentences():
    unit = _unit(
        "本课程介绍发动机的基本工作原理。本课程介绍发动机的基本原理。欢迎来到本课程。"
        "发动机将燃料的化学能转化为机械能。3. 发动机包括曲柄连杆机构。",
        evidence_id="ev_engine",
    )
    reviewer = StubReviewer(items=[
        ["本课程介绍发动机的基本工作原理。", "发动机将燃料的化学能转化为机械能。", "发动机包括曲柄连杆机构。"],
    ])

    reviewed, warnings = asyncio_run(_service(reviewer)._review_evidence([unit]))

    assert len(reviewed) == 1
    kept = reviewed[0]
    assert kept.evidence_id == "ev_engine"
    assert "本课程介绍发动机的基本原理。" not in kept.text  # near-duplicate dropped
    assert "欢迎来到本课程。" not in kept.text  # meaningless greeting dropped
    assert "3." not in kept.text  # OCR ordering prefix stripped
    assert "发动机将燃料的化学能转化为机械能。" in kept.text
    assert any("PREP_EVIDENCE_REVIEWED" in warning for warning in warnings)


def test_review_keeps_unit_metadata_after_filtering():
    unit = _unit(
        "第一句内容。第二句内容。",
        evidence_id="ev_meta",
        page=7,
        role="textbook",
        material="mat-book",
    )
    reviewer = StubReviewer(items=[["第二句内容。"]])

    reviewed, _ = asyncio_run(_service(reviewer)._review_evidence([unit]))

    assert len(reviewed) == 1
    kept = reviewed[0]
    assert kept.page == 7
    assert kept.material_role == "textbook"
    assert kept.material_version_id == "mat-book"
    assert kept.source_block_ids == [f"block_ev_meta"]


def test_review_batch_failure_falls_back_to_original_evidence():
    unit = _unit("保留原始证据。")
    reviewer = StubReviewer(error=RuntimeError("llm unavailable"))

    reviewed, warnings = asyncio_run(_service(reviewer)._review_evidence([unit]))

    assert reviewed == [unit]
    assert any("PREP_EVIDENCE_REVIEW_PARTIAL" in warning for warning in warnings)


def test_review_disabled_skips_reviewer(monkeypatch):
    unit = _unit("跳过审查。")
    reviewer = StubReviewer(items=[[]])
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REVIEW_ENABLED", False)

    reviewed, warnings = asyncio_run(_service(reviewer)._review_evidence([unit]))

    assert reviewed == [unit]
    assert warnings == []
    assert reviewer.calls == []


def test_review_without_reviewer_keeps_evidence(monkeypatch):
    from app.services.controlled_prep_workflow import controlled_prep_workflow

    unit = _unit("没有审查器。")
    monkeypatch.setattr(controlled_prep_workflow, "client", None)

    reviewed, warnings = asyncio_run(InitialCoursePrepService()._review_evidence([unit]))

    assert reviewed == [unit]
    assert warnings == []


def test_review_empty_result_falls_back_to_original():
    unit = _unit("整段证据被全部删除。")
    reviewer = StubReviewer(items=[[]])

    reviewed, warnings = asyncio_run(_service(reviewer)._review_evidence([unit]))

    assert reviewed == [unit]
    assert any("PREP_EVIDENCE_REVIEW_EMPTY" in warning for warning in warnings)


def test_review_drops_emptied_unit_and_keeps_others():
    first = _unit("保留这一条。", evidence_id="ev_keep")
    second = _unit("整段删除。", evidence_id="ev_drop", page=2)
    reviewer = StubReviewer(items=[["保留这一条。"], []])

    reviewed, warnings = asyncio_run(_service(reviewer)._review_evidence([first, second]))

    assert [item.evidence_id for item in reviewed] == ["ev_keep"]
    assert any("1 条整段证据" in warning for warning in warnings)


def test_review_rejects_rewritten_sentences():
    # The model is only allowed to delete; a polished rewrite must not leak in.
    unit = _unit("发动机把化学能转化为机械能。")
    reviewer = StubReviewer(items=[["发动机将化学能转变成了机械能。"]])

    reviewed, _ = asyncio_run(_service(reviewer)._review_evidence([unit]))

    assert reviewed == [unit]


def test_review_skipped_unit_keeps_every_sentence():
    first = _unit("第一条保留。", evidence_id="ev_a")
    second = _unit("第二条保留。", evidence_id="ev_b", page=3)
    # Model omits the item for the second unit entirely.
    reviewer = StubReviewer(items=[["第一条保留。"]])

    reviewed, _ = asyncio_run(_service(reviewer)._review_evidence([first, second]))

    assert [item.text for item in reviewed] == ["第一条保留。", "第二条保留。"]


def test_split_sentences_strips_ocr_prefixes_and_drops_blanks():
    service = InitialCoursePrepService()

    sentences = service._split_sentences(
        "  3. 发动机工作原理。  \n（1）曲轴连杆机构。欢迎学习！ [page 2]"
    )

    assert sentences == ["发动机工作原理。", "曲轴连杆机构。", "欢迎学习！", "[page 2]"]


def test_chunk_review_batches_splits_by_unit_count(monkeypatch):
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REVIEW_BATCH_UNITS", 6)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REVIEW_BATCH_CHARS", 1_000_000)
    units = [_unit(f"第 {index} 条。", evidence_id=f"ev_{index}", page=index + 1) for index in range(10)]
    texts = [["第 {index} 条。"] for index in range(10)]

    batches = InitialCoursePrepService._chunk_review_batches(units, texts)

    assert [len(units) for units, _ in batches] == [6, 4]


def test_chunk_review_batches_splits_by_char_budget(monkeypatch):
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REVIEW_BATCH_UNITS", 100)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REVIEW_BATCH_CHARS", 30)
    units = [_unit("句子" * 20, evidence_id=f"ev_{index}", page=index + 1) for index in range(3)]

    batches = InitialCoursePrepService._chunk_review_batches(
        units,
        [["句子" * 20] for _ in range(3)],
    )

    assert len(batches) >= 2
    assert sum(len(units) for units, _ in batches) == 3


def test_review_batches_are_positionally_aligned(monkeypatch):
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REVIEW_BATCH_UNITS", 2)
    monkeypatch.setattr(settings, "PREP_INITIAL_EVIDENCE_REVIEW_BATCH_CHARS", 1_000_000)
    units = [
        _unit("甲内容。", evidence_id="ev_a", page=1),
        _unit("乙内容。", evidence_id="ev_b", page=2),
        _unit("丙内容。", evidence_id="ev_c", page=3),
    ]
    reviewer = StubReviewer(items=[
        ["甲内容。"],
        ["乙内容。"],
        ["丙内容。"],
    ])

    reviewed, _ = asyncio_run(_service(reviewer)._review_evidence(units))

    assert [item.evidence_id for item in reviewed] == ["ev_a", "ev_b", "ev_c"]
    assert [len(call) for call in reviewer.calls] == [2, 1]
