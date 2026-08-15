"""HTTP boundaries for learner-owned learning-adjustment transitions."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_transition_router_is_registered_with_learner_owned_contract() -> None:
    """The API is intentionally separate from the TeachingAgent answer route."""
    from app.api.v1.endpoints import learning_adjustments

    app = FastAPI()
    app.include_router(learning_adjustments.router, prefix="/api/v1/learning-adjustments")
    paths = {
        f"/api/v1/learning-adjustments{route.path}"
        for route in learning_adjustments.router.routes
    }

    assert "/api/v1/learning-adjustments/course/{course_id}/recent" in paths
    assert "/api/v1/learning-adjustments/{adjustment_id}/apply" in paths
    assert "/api/v1/learning-adjustments/{adjustment_id}/return" in paths
    assert "/api/v1/learning-adjustments/{adjustment_id}/dismiss" in paths


def test_transition_router_rejects_invalid_idempotency_before_service_call(monkeypatch) -> None:
    """Clients cannot smuggle a weak or malformed idempotency identity through apply."""
    from app.api.v1.endpoints import learning_adjustments

    app = FastAPI()
    app.include_router(learning_adjustments.router, prefix="/api/v1/learning-adjustments")
    app.dependency_overrides[learning_adjustments.get_session] = lambda: object()
    app.dependency_overrides[learning_adjustments.get_current_user] = lambda: {"user_id": "7"}
    monkeypatch.setattr(
        learning_adjustments,
        "require_course_permission",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=True),
    )

    response = TestClient(app).post(
        "/api/v1/learning-adjustments/lad_demo/apply",
        json={
            "return_anchor": {
                "course_release_id": "cr_1",
                "media_release_id": "mrel_1",
                "media_release_item_id": "mrit_1",
                "outline_node_id": "node_1",
                "local_time_ms": 100,
                "page": 1,
            },
            "idempotency_key": "short",
        },
    )

    assert response.status_code == 422
