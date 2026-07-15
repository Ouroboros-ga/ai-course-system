"""Contract tests for P1-09 G5A canary_v2 endpoint (ADR-0006 §G5A + §9).

Covers:
1. 503 SHADOW_FEATURE_DISABLED when EVIDENCE_CITATION_MODE not v2_shadow.
2. admin_only enforced: admin -> proceeds; student -> 403; no token -> 401.
3. /run requires course_ids (400 when empty - scope control).
4. /run under all-flags-on returns verdict + real_services_called=False.
5. /report returns verdict + aggregate_invariants.
6. No raw file paths in responses (desensitization).
"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import canary_v2
from app.core import feature_flags as ff
from app.core.security import get_current_user


def _make_app():
    app = FastAPI()
    app.include_router(canary_v2.router, prefix="/api/v1/canary-v2")
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
    cfg = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    cfg[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    cfg[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"
    cfg[ff.EVIDENCE_CITATION_MODE] = "v2_shadow"
    cfg[ff.KNOWLEDGE_GRAPH_PIPELINE_VERSION] = "v2_shadow"
    cfg[ff.LEARNING_EVENT_MODE] = "v2_shadow"
    cfg[ff.STUDENT_MEMORY_MODE] = "shadow"
    cfg[ff.SAFETY_GOVERNANCE_MODE] = "shadow"
    return cfg


def _v1_modes():
    return {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}


class TestFlagGate:
    def test_503_when_flag_off(self):
        with patch("app.api.v1.endpoints.canary_v2._configured_modes", return_value=_v1_modes()):
            with TestClient(_admin()) as c:
                r = c.post("/api/v1/canary-v2/run", json={"course_ids": [101]})
        assert r.status_code == 503
        assert r.json()["detail"]["detail"] == "SHADOW_FEATURE_DISABLED"


class TestAdminOnly:
    def test_student_forbidden(self):
        with patch("app.api.v1.endpoints.canary_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_student()) as c:
                r = c.post("/api/v1/canary-v2/run", json={"course_ids": [101]})
        assert r.status_code == 403

    def test_no_token_unauthorized(self):
        with patch("app.api.v1.endpoints.canary_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_make_app()) as c:
                r = c.post("/api/v1/canary-v2/run", json={"course_ids": [101]})
        assert r.status_code in (401, 403)


class TestRun:
    def test_run_requires_course_ids(self):
        with patch("app.api.v1.endpoints.canary_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                r = c.post("/api/v1/canary-v2/run", json={"course_ids": []})
        assert r.status_code == 400  # scope control: no empty allowlist

    def test_run_returns_verdict_no_real_services(self, tmp_path):
        # Patch the canary runner's flag-read fns to all-flags-on so the
        # underlying triggers actually fire (the endpoint's own flag check
        # is patched above; the runner patches the shadow modules separately).
        from app.platform.canary import canary_runner as cr

        configured = _v2_modes()
        patches = [
            patch("app.platform.shadow.doc_shadow._configured_modes_from_settings", return_value=configured),
            patch("app.platform.shadow.evidence_shadow._configured_modes", return_value=configured),
            patch("app.platform.shadow.learning_shadow._configured_modes", return_value=configured),
            patch("app.platform.shadow.memory_candidate_shadow._configured_modes", return_value=configured),
            patch("app.platform.shadow.safety_dryrun_shadow._configured_modes", return_value=configured),
            patch("app.platform.shadow.graph_shadow._configured_modes", return_value=configured),
        ]
        # Isolate stores to tmp so the run does not touch real shadow roots.
        from app.platform.shadow.doc_shadow import ShadowArtifactStore
        from app.platform.shadow.evidence_shadow import EvidenceTraceStore
        from app.platform.shadow.learning_shadow import LearningEventShadowStore
        from app.platform.shadow.memory_candidate_shadow import MemoryCandidateShadowStore
        from app.platform.shadow.safety_dryrun_shadow import SafetyDryRunStore
        from app.platform.shadow.graph_shadow import GraphShadowStore

        orig_run = cr.run_canary

        def _isolated_run(config):
            config = cr.CanaryConfig(
                course_ids=config.course_ids,
                question=config.question,
                student_id=config.student_id,
                doc_file_path=tmp_path / "src.md",
                doc_store=ShadowArtifactStore(base_dir=tmp_path / "doc"),
                evidence_store=EvidenceTraceStore(base_dir=tmp_path / "ev"),
                learning_store=LearningEventShadowStore(base_dir=tmp_path / "lr"),
                memory_store=MemoryCandidateShadowStore(base_dir=tmp_path / "mem"),
                safety_store=SafetyDryRunStore(base_dir=tmp_path / "sf"),
                graph_store=GraphShadowStore(base_dir=tmp_path / "gr"),
            )
            (tmp_path / "src.md").write_bytes(b"canary bytes")
            return orig_run(config)

        with patch("app.api.v1.endpoints.canary_v2._configured_modes", return_value=configured), \
             patch("app.platform.canary.canary_runner.run_canary", side_effect=_isolated_run):
            for p in patches:
                p.start()
            try:
                with TestClient(_admin()) as c:
                    r = c.post("/api/v1/canary-v2/run", json={"course_ids": [101]})
            finally:
                for p in patches:
                    p.stop()
        assert r.status_code == 200
        body = r.json()
        assert body["real_services_called"] is False
        assert body["verdict"] == "PASS"
        assert body["course_count"] == 1


class TestReport:
    def test_report_returns_verdict(self):
        with patch("app.api.v1.endpoints.canary_v2._configured_modes", return_value=_v2_modes()):
            with TestClient(_admin()) as c:
                r = c.get("/api/v1/canary-v2/report")
        assert r.status_code == 200
        body = r.json()
        assert body["verdict"] in ("PASS", "FAIL")
        assert "aggregate_invariants" in body
        assert body["path_count"] == 6


class TestDesensitization:
    def test_no_raw_paths_in_run_response(self, tmp_path):
        from app.platform.canary import canary_runner as cr

        configured = _v2_modes()
        patches = [
            patch(f"app.platform.shadow.{m}.{fn}", return_value=configured)
            for m, fn in [
                ("doc_shadow", "_configured_modes_from_settings"),
                ("evidence_shadow", "_configured_modes"),
                ("learning_shadow", "_configured_modes"),
                ("memory_candidate_shadow", "_configured_modes"),
                ("safety_dryrun_shadow", "_configured_modes"),
                ("graph_shadow", "_configured_modes"),
            ]
        ]
        from app.platform.shadow.doc_shadow import ShadowArtifactStore
        from app.platform.shadow.evidence_shadow import EvidenceTraceStore
        from app.platform.shadow.learning_shadow import LearningEventShadowStore
        from app.platform.shadow.memory_candidate_shadow import MemoryCandidateShadowStore
        from app.platform.shadow.safety_dryrun_shadow import SafetyDryRunStore
        from app.platform.shadow.graph_shadow import GraphShadowStore

        orig_run = cr.run_canary

        def _isolated_run(config):
            config = cr.CanaryConfig(
                course_ids=config.course_ids, question=config.question, student_id=config.student_id,
                doc_file_path=tmp_path / "src.md",
                doc_store=ShadowArtifactStore(base_dir=tmp_path / "doc"),
                evidence_store=EvidenceTraceStore(base_dir=tmp_path / "ev"),
                learning_store=LearningEventShadowStore(base_dir=tmp_path / "lr"),
                memory_store=MemoryCandidateShadowStore(base_dir=tmp_path / "mem"),
                safety_store=SafetyDryRunStore(base_dir=tmp_path / "sf"),
                graph_store=GraphShadowStore(base_dir=tmp_path / "gr"),
            )
            (tmp_path / "src.md").write_bytes(b"canary bytes")
            return orig_run(config)

        with patch("app.api.v1.endpoints.canary_v2._configured_modes", return_value=configured), \
             patch("app.platform.canary.canary_runner.run_canary", side_effect=_isolated_run):
            for p in patches:
                p.start()
            try:
                with TestClient(_admin()) as c:
                    body = c.post("/api/v1/canary-v2/run", json={"course_ids": [101]}).text
            finally:
                for p in patches:
                    p.stop()
        assert "C:\\" not in body
        assert "/home/" not in body
        assert "file://" not in body
