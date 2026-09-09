"""DK3 Adjudicator D 裁决与决策审计验收测试。"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.discipline_knowledge_model import (
    DisciplineAlias,
    DisciplineAssertion,
    DisciplineConcept,
    DisciplineDecision,
    DisciplineMention,
)
from app.services.discipline_knowledge.adjudication import adjudicate
from app.services.discipline_knowledge.decisions import (
    DisciplineDecisionError,
    merge_concepts,
    record_decision,
    revert_decision,
)


def test_tied_votes_are_never_force_accepted():
    result = adjudicate({
        "kind": "verification",
        "target_type": "assertion",
        "target_id": "dka_tie",
        "votes": {"verifier": {"verdict": "insufficient",
                               "reason_codes": ["EVIDENCE_WEAK"]}},
        "reason_codes": ["EVIDENCE_WEAK"],
    })
    assert result["decision"] == "quarantine"


def test_contradicted_evidence_rejects():
    result = adjudicate({
        "kind": "verification",
        "votes": {"verifier": {"verdict": "contradicted",
                               "reason_codes": ["NEGATION_CONTRADICTED"]}},
        "reason_codes": ["NEGATION_CONTRADICTED"],
    })
    assert result["decision"] == "reject"


def test_prompt_injection_rejects():
    result = adjudicate({
        "kind": "verification",
        "votes": {},
        "reason_codes": ["INSTRUCTION_IN_CORPUS"],
        "context": {"prompt_injected": True},
    })
    assert result["decision"] == "reject"
    assert result["reason_codes"] == ["INSTRUCTION_IN_CORPUS"]


def test_fabricated_citation_rejects_but_misaligned_quarantines():
    fabricated = adjudicate({
        "kind": "grounding",
        "reason_codes": ["GROUNDING_FAILED"],
        "context": {"fabricated": True},
    })
    assert fabricated["decision"] == "reject"
    misaligned = adjudicate({
        "kind": "grounding",
        "reason_codes": ["GROUNDING_FAILED"],
        "context": {"fabricated": False},
    })
    assert misaligned["decision"] == "quarantine"


def test_single_exact_identity_accepts_when_not_high_risk():
    result = adjudicate({
        "kind": "identity",
        "votes": {"resolver": {"decision": "resolved", "concept_id": "dkn_hash"}},
        "candidates": [{"concept_id": "dkn_hash"}],
    })
    assert result["decision"] == "accept"
    assert result["concept_id"] == "dkn_hash"


def test_ambiguous_identities_keep_separate_or_quarantine():
    low_risk = adjudicate({
        "kind": "identity",
        "votes": {"resolver": {"decision": "ambiguous"}},
        "candidates": [{"concept_id": "a"}, {"concept_id": "b"}],
    })
    assert low_risk["decision"] == "keep_separate"
    high_risk = adjudicate({
        "kind": "identity",
        "votes": {"resolver": {"decision": "ambiguous"}},
        "candidates": [{"concept_id": "a"}, {"concept_id": "b"}],
        "context": {"high_risk": True},
    })
    assert high_risk["decision"] == "quarantine"


def test_version_conflict_coexists_or_isolates():
    coexisting = adjudicate({
        "kind": "conflict",
        "reason_codes": ["VERSION_CONFLICT"],
        "context": {"versions": [{"version": "RFC 793"}, {"version": "RFC 9293"}]},
    })
    assert coexisting["decision"] == "keep_separate"
    assert coexisting["after"]["coexist"] == ["RFC 793", "RFC 9293"]
    stuck = adjudicate({
        "kind": "conflict",
        "reason_codes": ["VERSION_CONFLICT"],
        "context": {},
    })
    assert stuck["decision"] == "quarantine"


def test_record_decision_and_stale_rejection(session):
    import uuid as _uuid

    concept_id = f"dkd_test_c_{_uuid.uuid4().hex[:8]}"
    session.add(DisciplineConcept(
        concept_id=concept_id, canonical_name="测试概念",
        domain="cs", node_type="concept", status="active", revision=1,
    ))
    session.commit()
    ok = record_decision(
        session, target_type="concept", target_id=concept_id,
        expected_revision=1, decision="quarantine",
        reason_codes=["EVIDENCE_WEAK"], actor_type="model", actor_ref="verifier-c",
    )
    assert ok["decision_id"].startswith("dkd_")
    # 行 revision 仍为 1（记审计不推进版本）；用过期期望写即 STALE
    with pytest.raises(DisciplineDecisionError) as exc_info:
        record_decision(
            session, target_type="concept", target_id=concept_id,
            expected_revision=2, decision="accept",
            reason_codes=["EXACT_ALIAS"], actor_type="model", actor_ref="adjudicator-d",
        )
    assert exc_info.value.error_code == "STALE_REVISION"
    with pytest.raises(DisciplineDecisionError):
        record_decision(
            session, target_type="concept", target_id="dkd_test_c1",
            expected_revision=1, decision="maybe",
            reason_codes=["EVIDENCE_WEAK"], actor_type="model", actor_ref="x",
        )


def _seed_merge_pair(session, tag):
    src, dst = f"dkm_src_{tag}", f"dkm_dst_{tag}"
    session.add(DisciplineConcept(
        concept_id=src, canonical_name="堆", domain="cs",
        node_type="concept", status="active", revision=1,
    ))
    session.add(DisciplineConcept(
        concept_id=dst, canonical_name="堆", domain="cs",
        node_type="concept", status="active", revision=1,
    ))
    session.add(DisciplineMention(
        mention_id=f"dkm_m1_{tag}", chunk_id="dkch_x", char_start=0, char_end=1,
        surface_text="堆", concept_id=src, run_id="r1",
    ))
    session.add(DisciplineMention(
        mention_id=f"dkm_m2_{tag}", chunk_id="dkch_x", char_start=2, char_end=3,
        surface_text="堆", concept_id=src, run_id="r1",
    ))
    session.add(DisciplineAlias(
        concept_id=src, language="en", normalized_alias="heap",
        raw_alias="heap", basis="test",
    ))
    session.add(DisciplineAlias(
        concept_id=dst, language="en", normalized_alias="heap",
        raw_alias="heap", basis="test",
    ))
    session.commit()
    return src, dst


def test_merge_moves_refs_and_bumps_revision(session):
    src, dst = _seed_merge_pair(session, "merge")
    record = merge_concepts(
        session, source_id=src, target_id=dst,
        actor_ref="adjudicator-d", reason_codes=["EXACT_ALIAS", "DEFINITION_CONTEXT"],
    )
    assert record["moved_mentions"] == 2
    assert record["moved_aliases"] == 0  # heap 在目标已存在，跳过不覆盖
    assert record["skipped_aliases"] == 1
    src_row = session.exec(
        select(DisciplineConcept).where(DisciplineConcept.concept_id == src)
    ).one()
    dst_row = session.exec(
        select(DisciplineConcept).where(DisciplineConcept.concept_id == dst)
    ).one()
    assert src_row.status == "merged"
    assert dst_row.revision == 2
    mentions = session.exec(
        select(DisciplineMention).where(DisciplineMention.run_id == "r1")
    ).all()
    moved_here = [m for m in mentions if m.mention_id.endswith("_merge")]
    assert moved_here and {m.concept_id for m in moved_here} == {dst}
    audit = session.exec(
        select(DisciplineDecision).where(
            DisciplineDecision.decision_id == record["decision_id"])
    ).one()
    assert audit.after_ref["target_revision"] == 2
    # 合并已推进版本：再用旧 revision 写即 STALE（409 语义）
    with pytest.raises(DisciplineDecisionError) as exc_info:
        record_decision(
            session, target_type="concept", target_id=dst,
            expected_revision=1, decision="quarantine",
            reason_codes=["EVIDENCE_WEAK"], actor_type="admin", actor_ref="reviewer",
        )
    assert exc_info.value.error_code == "STALE_REVISION"


def test_revert_restores_before_refs_with_new_revision(session):
    src, dst = _seed_merge_pair(session, "revert")
    record = merge_concepts(
        session, source_id=src, target_id=dst,
        actor_ref="adjudicator-d", reason_codes=["EXACT_ALIAS"],
    )
    reverted = revert_decision(
        session, decision_id=record["decision_id"],
        actor_ref="admin-user", reason="合错了，领域不同",
    )
    assert reverted["restored_mentions"] == 2
    src_row = session.exec(
        select(DisciplineConcept).where(DisciplineConcept.concept_id == src)
    ).one()
    dst_row = session.exec(
        select(DisciplineConcept).where(DisciplineConcept.concept_id == dst)
    ).one()
    assert src_row.status == "active"
    assert dst_row.revision == 3
    mentions = session.exec(
        select(DisciplineMention).where(DisciplineMention.run_id == "r1")
    ).all()
    moved_here = [m for m in mentions if m.mention_id.endswith("_revert")]
    assert moved_here and {m.concept_id for m in moved_here} == {src}
    with pytest.raises(DisciplineDecisionError) as exc_info:
        revert_decision(
            session, decision_id=reverted["decision_id"],
            actor_ref="admin-user", reason="重复撤销",
        )
    assert exc_info.value.error_code == "IRREVERSIBLE_DECISION"


def test_assertion_revision_lock(session):
    import uuid as _uuid

    assertion_id = f"dkd_test_a_{_uuid.uuid4().hex[:8]}"
    session.add(DisciplineAssertion(
        assertion_id=assertion_id, subject_id="dkm_dst",
        predicate="defines", literal="堆是一种结构。",
        qualifiers={}, status="extracted", revision=4,
    ))
    session.commit()
    with pytest.raises(DisciplineDecisionError) as exc_info:
        record_decision(
            session, target_type="assertion", target_id=assertion_id,
            expected_revision=3, decision="quarantine",
            reason_codes=["EVIDENCE_WEAK"], actor_type="policy", actor_ref="gate",
        )
    assert exc_info.value.error_code == "STALE_REVISION"
    ok = record_decision(
        session, target_type="assertion", target_id=assertion_id,
        expected_revision=4, decision="quarantine",
        reason_codes=["EVIDENCE_WEAK"], actor_type="policy", actor_ref="gate",
    )
    assert ok["decision"] == "quarantine"
