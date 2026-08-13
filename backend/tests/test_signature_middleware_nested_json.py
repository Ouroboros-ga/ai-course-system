"""Regression coverage for strict JSON APIs behind the legacy signer."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.signature_middleware import SignatureMiddleware


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    coordinate: dict[str, object]


def _canonical_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _signature(payload: dict[str, object], time_value: str) -> str:
    values = {**payload, "time": time_value}
    canonical = "".join(
        f"{key}{_canonical_value(value)}"
        for key, value in sorted(values.items())
        if value is not None and _canonical_value(value).strip()
    )
    return hashlib.md5(
        f"{canonical}{settings.STATIC_KEY}{time_value}".encode("utf-8")
    ).hexdigest().upper()


def test_nested_json_signature_reaches_a_strict_request_model_without_transport_fields() -> None:
    app = FastAPI()
    app.add_middleware(SignatureMiddleware, whitelist_paths=[])

    @app.post("/strict")
    def strict_endpoint(payload: _StrictPayload) -> dict[str, object]:
        return payload.model_dump()

    payload = {
        "message": "review this cue",
        "coordinate": {
            "media_release_item_id": "item-2",
            "local_time_ms": 48_200,
        },
    }
    time_value = datetime.now().strftime(settings.TIME_FORMAT)

    with TestClient(app) as client:
        response = client.post(
            "/strict",
            params={"time": time_value, "enc": _signature(payload, time_value)},
            json=payload,
        )

    assert response.status_code == 200
    assert response.json() == payload
