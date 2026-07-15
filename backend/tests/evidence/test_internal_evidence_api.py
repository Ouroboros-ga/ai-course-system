"""Contract tests for P1-09 G4A internal-evidence-api/1.0 (ADR-0006 §8/§9).

Covers:
1. DTO models serialize snake_case per the frozen contract.
2. 503 SHADOW_FEATURE_DISABLED when EVIDENCE_CITATION_MODE not v2_shadow.
3. admin_only enforced: admin -> proceeds; student -> 403; no token -> 401.
4. G4 empty/abstain responses conform to the DTO.
5. No raw file paths in any response (desensitization).
6. validate endpoint abstains (no_evidence) without fake citation keys.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import evidence_v2
from app.core import feature_flags as ff
from app.core.security import get_current_user


# ---------------------------------------------------------------------------
# App + auth override helpers
# ---------------------------------------------------------------------------


def _make_app():
    app = FastAPI()
    app.include_router(evidence_v2.router, prefix="/api/v1/evidence-v2")
    return app


def _admin():
    app = _make_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "username": "admin", "role": "admin",
    }
    return app


def _student():
    app = _make_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 2, "username": "student", "role": "student",
    }
    return app


def _v2_modes():
    """All flags on the doc->runtime->evidence chain v2_shadow so
    EVIDENCE_CITATION_MODE is effectively v2_shadow (no conflict)."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"
    configured[ff.EVIDENCE_CITATION_MODE] = "v2_shadow"
    return configured


def _v1_modes():
    return {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}


DOC = "doc_test_001"


# ---------------------------------------------------------------------------
# DTO shape (snake_case)
# ---------------------------------------------------------------------------


class TestDTOShape:
    def test_evidence_span_dto_snake_case(self):
        es = evidence_v2.EvidenceSpanDTO(
            artifact_id="art_1", document_id="doc_1", block_id="blk_1",
            page_or_slide=2, char_start=0, char_end=10, status="active",
        )
        dumped = es.model_dump()
        assert set(dumped.keys()) == {
            "artifact_id", "document_id", "unit_id", "block_id", "version_ref",
            "page_or_slide", "char_start", "char_end", "text_snippet", "score",
            "status", "metadata",
        }
        assert dumped["artifact_id"] == "art_1"
        assert dumped["block_id"] == "blk_1"

    def test_citation_dto_key_nullable(self):
        c = evidence_v2.CitationDTO(statement="s")
        assert c.key is None  # no fake key without evidence
        assert c.statement == "s"

    def test_citation_validation_result_dto_fields(self):
        r = evidence_v2.CitationValidationResultDTO(
            status="no_evidence", abstain=True, abstain_reason="x", total_count=3,
        )
        d = r.model_dump()
        assert d["status"] == "no_evidence"
        assert d["abstain"] is True
        assert d["abstain_reason"] == "x"
        assert d["verified_count"] == 0
        assert d["total_count"] == 3
        assert d["details"] == []

    def test_document_page_dto_fields(self):
        p = evidence_v2.DocumentPageDTO(document_id="d", page_number=1)
        d = p.model_dump()
        assert set(d.keys()) == {
            "document_id", "page_number", "image_url", "natural_width", "natural_height",
        }


# ---------------------------------------------------------------------------
# Flag gate (503)
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_503_when_flag_off(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v1_modes()):
            app = _admin()
            with TestClient(app) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/evidence")
        assert r.status_code == 503
        body = r.json()["detail"]
        assert body["detail"] == "SHADOW_FEATURE_DISABLED"
        assert body["flag"] == ff.EVIDENCE_CITATION_MODE

    def test_conflict_downgrade_503(self):
        """DOCUMENT_KG_RUNTIME_MODE=v1_only downgrades EVIDENCE_CITATION_MODE."""
        configured = _v2_modes()
        configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v1_only"
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=configured):
            app = _admin()
            with TestClient(app) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/citations")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# admin_only enforcement (ADR §9)
# ---------------------------------------------------------------------------


class TestAdminOnly:
    def test_admin_proceeds_when_flag_on(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            app = _admin()
            with TestClient(app) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/evidence")
        assert r.status_code == 200
        assert r.json() == {"evidence_spans": []}

    def test_student_forbidden(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            app = _student()
            with TestClient(app) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/evidence")
        assert r.status_code == 403

    def test_no_token_unauthorized(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            app = _make_app()  # no override -> get_current_user runs -> no token -> 401
            with TestClient(app) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/evidence")
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# G4 empty/abstain responses conform to DTO
# ---------------------------------------------------------------------------


class TestG4Responses:
    def test_evidence_empty_list(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/evidence")
        assert r.status_code == 200
        assert r.json() == {"evidence_spans": []}

    def test_citations_empty_list(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/citations")
        assert r.status_code == 200
        assert r.json() == {"citations": []}

    def test_validate_abstains_no_evidence(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                r = c.post(
                    f"/api/v1/evidence-v2/documents/{DOC}/citations/validate",
                    json={"citations": [{"statement": "s1"}, {"statement": "s2"}]},
                )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "no_evidence"
        assert body["abstain"] is True
        assert body["abstain_reason"] == "no_evidence_backed_citations"
        assert body["verified_count"] == 0
        assert body["total_count"] == 2  # echo of input count

    def test_pages_empty_list(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/pages")
        assert r.status_code == 200
        assert r.json() == {"pages": []}

    def test_page_image_503_rendering_not_available(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                r = c.get(f"/api/v1/evidence-v2/documents/{DOC}/pages/1/image")
        assert r.status_code == 503
        assert r.json()["detail"]["detail"] == "PAGE_RENDERING_NOT_AVAILABLE_IN_G4"


# ---------------------------------------------------------------------------
# Desensitization: no raw file paths
# ---------------------------------------------------------------------------


class TestDesensitization:
    def test_no_raw_paths_in_responses(self):
        with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                paths = [
                    c.get(f"/api/v1/evidence-v2/documents/{DOC}/evidence").text,
                    c.get(f"/api/v1/evidence-v2/documents/{DOC}/citations").text,
                    c.post(f"/api/v1/evidence-v2/documents/{DOC}/citations/validate",
                           json={"citations": []}).text,
                    c.get(f"/api/v1/evidence-v2/documents/{DOC}/pages").text,
                ]
        for body in paths:
            assert "C:\\" not in body
            assert "/home/" not in body
            assert "file://" not in body
