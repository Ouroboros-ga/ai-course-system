"""Authenticated teacher API smoke for course 87 snapshot lifecycle."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS", "1")
os.environ.setdefault("AI_COURSE_TESTING", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402


def body(response, label: str):
    payload = response.json()
    if response.status_code >= 400 or payload.get("code", 200) >= 400:
        raise RuntimeError(f"{label} failed: {response.status_code} {payload}")
    return payload.get("data")


def main() -> None:
    token = create_access_token({"sub": "6", "username": "demo-owner", "role": "teacher"})
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)
    course = 87

    before = body(client.get(f"/api/v1/graph/course/{course}/snapshots", headers=headers), "list snapshots")
    items = before.get("items", [])
    if not items:
        raise RuntimeError("course 87 has no published snapshot")
    v1 = body(client.get(f"/api/v1/graph/course/{course}/snapshot", headers=headers), "get active snapshot")

    # A controlled second publication uses the server-validated current payload;
    # this is only for exercising diff/rollback, not a candidate bypass.
    v2 = body(client.post(
        f"/api/v1/graph/course/{course}/publish",
        headers=headers,
        json={
            "nodes": v1["nodes"],
            "relations": v1["relations"],
            "label": "课程 87 Demo 版本对比演练",
        },
    ), "publish controlled second version")
    versions = body(client.get(f"/api/v1/graph/course/{course}/snapshots", headers=headers), "list versions")
    if len(versions.get("items", [])) < 2:
        raise RuntimeError("controlled second version was not persisted")

    diff = body(client.get(
        f"/api/v1/graph/course/{course}/snapshots/diff",
        params={"a": v1["snapshot_id"], "b": v2["snapshot_id"]},
        headers=headers,
    ), "diff versions")
    if not {"nodes", "relations"}.issubset(diff):
        raise RuntimeError(f"diff contract missing nodes/relations: {diff}")

    rolled = body(client.post(
        f"/api/v1/graph/course/{course}/rollback/{v1['snapshot_id']}",
        headers=headers,
    ), "rollback to v1")
    active = body(client.get(f"/api/v1/graph/course/{course}/snapshot", headers=headers), "verify active after rollback")
    if active["snapshot_id"] != v1["snapshot_id"]:
        raise RuntimeError(f"rollback did not switch active snapshot: {active}")

    print(json.dumps({
        "v1_snapshot_id": v1["snapshot_id"],
        "v2_snapshot_id": v2["snapshot_id"],
        "diff_node_added": len(diff["nodes"]["added"]),
        "diff_node_removed": len(diff["nodes"]["removed"]),
        "diff_node_modified": len(diff["nodes"]["modified"]),
        "diff_relation_added": len(diff["relations"]["added"]),
        "rollback_response_snapshot_id": rolled["snapshot_id"],
        "active_after_rollback": active["snapshot_id"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
