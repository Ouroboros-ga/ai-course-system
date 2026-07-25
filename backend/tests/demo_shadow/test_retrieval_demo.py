from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints.retrieval_demo import require_demo_visible, router
from app.core.config import settings
from app.core.security import admin_only
from app.platform.retrieval_demo.mode import resolve_demo_mode
from app.platform.retrieval_demo.service import DemoService
from app.platform.retrieval_demo.store import DemoRunStore


class FakeR2Provider:
    course_ids = ("COURSE_A",)
    metadata = {
        "fixture_id": "reviewed_silver_v0_2",
        "model": {"revision": "fake-revision", "model_safetensors_sha256": "fake-weight"},
        "r2_config_sha256": "fake-config",
        "r3_graph_expansion_called": False,
    }

    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.called = False

    def retrieve(self, *, course_id: str, question: str) -> dict:
        self.called = True
        if self.raises:
            raise RuntimeError("local model unavailable")
        return {
            "status": "ok",
            "hits": [{
                "rank": 1,
                "research_chunk_id": "chunk-1",
                "course_id": course_id,
                "page_or_slide": 7,
                "block_id": "block-7",
                "research_evidence_ids": ["evidence-7"],
                "score": 0.9,
                "text_snippet": "evidence-backed text",
                "citations": [{"research_evidence_id": "evidence-7", "citation_key": "cite-7", "page_or_slide": 7, "block_id": "block-7"}],
            }],
        }


def make_service(tmp_path: Path, provider: FakeR2Provider, *, mode: str = "demo_compare") -> DemoService:
    return DemoService(
        configured_mode=mode,
        environment="test",
        provider=provider,
        store=DemoRunStore(tmp_path / "runs"),
    )


def signed_payload(payload: dict[str, str]) -> dict[str, str]:
    """Create the same local request signature used by the app middleware."""
    request_time = datetime.now().strftime(settings.TIME_FORMAT)
    signed = {**payload, "time": request_time}
    concatenated = "".join(f"{key}{signed[key]}" for key in sorted(signed))
    return {
        **signed,
        "enc": hashlib.md5(f"{concatenated}{settings.STATIC_KEY}{request_time}".encode("utf-8")).hexdigest().upper(),
    }


def test_v1_only_is_disabled_and_rollback_only_disables_demo(tmp_path: Path) -> None:
    service = make_service(tmp_path, FakeR2Provider(), mode="v1_only")
    assert service.mode_state().enabled is False
    with pytest.raises(HTTPException) as error:
        require_demo_visible(service)
    assert error.value.status_code == 503
    visible = make_service(tmp_path, FakeR2Provider())
    assert visible.rollback_to_v1_only().effective_mode == "v1_only"
    assert visible.mode_state().enabled is False


def test_disabled_router_rejects_query_before_provider_or_v1_path(tmp_path: Path) -> None:
    """The exposed route is closed by default, not merely hidden by the UI."""
    provider = FakeR2Provider()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/retrieval-demo")
    app.state.retrieval_demo_service = make_service(tmp_path, provider, mode="v1_only")
    app.dependency_overrides[admin_only] = lambda: {"role": "admin"}

    response = TestClient(app).post(
        "/api/v1/retrieval-demo/query",
        json={"course_id": "COURSE_A", "question": "question"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DEMO_SHADOW_DISABLED"
    assert provider.called is False


def test_actual_app_requires_admin_then_returns_disabled_before_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the mounted main app, not only a synthetic APIRouter app."""
    monkeypatch.setenv("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS", "1")
    from app.main import app

    provider = FakeR2Provider()
    app.state.retrieval_demo_service = make_service(tmp_path, provider, mode="v1_only")
    try:
        client = TestClient(app)
        unauthenticated = client.post(
            "/api/v1/retrieval-demo/query",
            json=signed_payload({"course_id": "COURSE_A", "question": "question"}),
        )
        app.dependency_overrides[admin_only] = lambda: {"role": "admin"}
        response = client.post(
            "/api/v1/retrieval-demo/query",
            json=signed_payload({"course_id": "COURSE_A", "question": "question"}),
        )
    finally:
        app.dependency_overrides.pop(admin_only, None)
        delattr(app.state, "retrieval_demo_service")

    assert unauthenticated.status_code == 401
    assert response.status_code == 503
    assert response.json()["data"]["code"] == "DEMO_SHADOW_DISABLED"
    assert provider.called is False


def test_visible_modes_are_rejected_outside_demo_safe_environment() -> None:
    state = resolve_demo_mode(configured_mode="demo_shadow_visible", environment="production")
    assert state.enabled is False
    assert state.effective_mode == "v1_only"
    assert state.reason == "environment_not_demo_safe"
    assert resolve_demo_mode(configured_mode="demo_shadow_visible", environment="demo").enabled is True
    assert resolve_demo_mode(configured_mode="demo_compare", environment="development").enabled is True


def test_unknown_course_abstains_before_provider_retrieval(tmp_path: Path) -> None:
    provider = FakeR2Provider()
    response = make_service(tmp_path, provider).query(course_id="OTHER", question="question")
    assert provider.called is False
    assert response["result"]["status"] == "abstain"
    assert response["result"]["abstain_reason"] == "course_not_available"
    assert response["result"]["hits"] == []


def test_provider_failure_keeps_v1_reference_isolated_and_persists_run(tmp_path: Path) -> None:
    response = make_service(tmp_path, FakeR2Provider(raises=True)).query(
        course_id="COURSE_A",
        question="question",
        v1_reference="operator captured V1 response",
    )
    assert response["result"]["abstain_reason"] == "demo_provider_unavailable"
    assert response["v1_v2_comparison"]["v1_text"] == "operator captured V1 response"
    assert response["v1_v2_comparison"]["status"] == "operator_supplied_v1_reference"
    assert "V1 未被调用" in " ".join(response["warnings"])
    saved_run = tmp_path / "runs" / f"{response['demo_run_id']}.json"
    assert saved_run.is_file()
    assert json.loads(saved_run.read_text(encoding="utf-8"))["v1_v2_comparison"] == response["v1_v2_comparison"]


def test_hit_citation_locator_is_preserved_and_r3_is_not_called(tmp_path: Path) -> None:
    response = make_service(tmp_path, FakeR2Provider()).query(course_id="COURSE_A", question="question")
    hit = response["result"]["hits"][0]
    citation = hit["citations"][0]
    assert (hit["course_id"], hit["page_or_slide"], hit["block_id"], citation["citation_key"]) == ("COURSE_A", 7, "block-7", "cite-7")
    assert response["run_trace"]["r3_graph_expansion_called"] is False
    assert all(stage["name"] != "r3_graph_expansion" for stage in response["run_trace"]["stages"])
    assert response["runtime"]["model"]["revision"] == "fake-revision"
    assert response["runtime"]["model"]["model_safetensors_sha256"] == "fake-weight"
    assert response["runtime"]["r2_config_sha256"] == "fake-config"
    assert response["runtime"]["p50_ms"] >= 0
    assert response["runtime"]["p95_ms"] >= response["runtime"]["p50_ms"]


def test_rollback_endpoint_disables_visible_demo_before_any_future_query(tmp_path: Path) -> None:
    provider = FakeR2Provider()
    service = make_service(tmp_path, provider, mode="demo_compare")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/retrieval-demo")
    app.state.retrieval_demo_service = service
    app.dependency_overrides[admin_only] = lambda: {"role": "admin"}
    client = TestClient(app)

    rollback = client.post("/api/v1/retrieval-demo/rollback", json={})
    query = client.post(
        "/api/v1/retrieval-demo/query",
        json={"course_id": "COURSE_A", "question": "question"},
    )

    assert rollback.status_code == 200
    assert rollback.json()["effective_mode"] == "v1_only"
    assert query.status_code == 503
    assert provider.called is False


def test_sidecar_rollback_to_fixture_is_explicit_and_source_labeled(tmp_path: Path) -> None:
    sidecar = FakeR2Provider()
    fixture = FakeR2Provider()
    service = DemoService(
        configured_mode="demo_compare", environment="test", provider=sidecar,
        fallback_provider=fixture, store=DemoRunStore(tmp_path / "runs"),
    )
    assert service.query(course_id="COURSE_A", question="before")["data_source"] == "course_sidecar"
    assert sidecar.called is True and fixture.called is False
    service.rollback_to_fixture()
    after = service.query(course_id="COURSE_A", question="after")
    assert after["data_source"] == "research_fixture_rollback"
    assert fixture.called is True


def test_fixture_rollback_endpoint_switches_future_queries(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/retrieval-demo")
    app.dependency_overrides[admin_only] = lambda: {"role": "admin"}
    primary, fallback = FakeR2Provider(), FakeR2Provider()
    app.state.retrieval_demo_service = DemoService(
        configured_mode="demo_compare", environment="test", provider=primary,
        fallback_provider=fallback, store=DemoRunStore(tmp_path / "runs"),
    )
    client = TestClient(app)
    rollback = client.post("/api/v1/retrieval-demo/rollback-to-fixture", json={})
    query = client.post(
        "/api/v1/retrieval-demo/query",
        json={"course_id": "COURSE_A", "question": "question"},
    )
    assert rollback.status_code == 200
    assert rollback.json()["data_source"] == "research_fixture_rollback"
    assert query.status_code == 200
    assert query.json()["data_source"] == "research_fixture_rollback"
    assert primary.called is False and fallback.called is True
