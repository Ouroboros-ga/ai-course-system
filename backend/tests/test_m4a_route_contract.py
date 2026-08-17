from collections import Counter

from fastapi.routing import APIRoute


def _iter_effective_api_routes(routes, prefix=""):
    """Flatten FastAPI's eager and 0.141+ lazy router registrations."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield f"{prefix}{route.path}", route
            continue

        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        included_prefix = getattr(include_context, "prefix", None)
        if original_router is not None and included_prefix is not None:
            yield from _iter_effective_api_routes(
                original_router.routes,
                prefix=f"{prefix}{included_prefix}",
            )


def _route_rows(app):
    openapi_paths = set(app.openapi()["paths"].keys())
    rows = []
    for index, (path, route) in enumerate(_iter_effective_api_routes(app.routes)):
        methods = sorted(method for method in route.methods if method not in {"HEAD", "OPTIONS"})
        for method in methods:
            rows.append({
                "index": index,
                "method": method,
                "path": path,
                "endpoint": route.endpoint.__name__,
                "module": route.endpoint.__module__,
                "in_openapi": path in openapi_paths,
            })
    return rows


def test_route_contract_records_required_fields(fastapi_app):
    rows = _route_rows(fastapi_app)
    assert rows
    for row in rows:
        assert set(row) == {"index", "method", "path", "endpoint", "module", "in_openapi"}
        assert row["method"]
        assert row["path"].startswith("/")
        assert row["endpoint"]
        assert row["module"].startswith("app.")
        assert isinstance(row["in_openapi"], bool)

    assert any(row["in_openapi"] for row in rows)


def test_route_contract_locks_known_non_openapi_catch_all(fastapi_app):
    rows = _route_rows(fastapi_app)
    hidden_rows = [row for row in rows if not row["in_openapi"]]

    expected_hidden = {
        ("DELETE", "/{path:path}", "catch_all", "app.main"),
        ("GET", "/{path:path}", "catch_all", "app.main"),
        ("PATCH", "/{path:path}", "catch_all", "app.main"),
        ("POST", "/{path:path}", "catch_all", "app.main"),
        ("PUT", "/{path:path}", "catch_all", "app.main"),
    }
    # Media assets deliberately remain out of OpenAPI because the path
    # converter accepts slash-containing object keys; access is still checked
    # by the endpoint before any metadata or content is returned.
    expected_hidden.update({
        ("GET", "/api/v1/media/assets/{object_key:path}/content", "get_asset_content", "app.api.v1.endpoints.media_timeline"),
        ("GET", "/api/v1/media/assets/{object_key:path}", "get_asset", "app.api.v1.endpoints.media_timeline"),
        # G5 storage admin: soft-delete/reactivate 同样使用 {object_key:path}
        # 因为对象键可含斜杠；端点内部仍做平台管理员权限校验。
        ("POST", "/api/v1/admin/storage/refs/{object_key:path}/reactivate", "reactivate_ref", "app.api.v1.endpoints.storage_admin"),
        ("POST", "/api/v1/admin/storage/refs/{object_key:path}/soft-delete", "mark_soft_deleted", "app.api.v1.endpoints.storage_admin"),
        # 媒体 PPT manifest 同步：内部门户路由，include_in_schema=False（git 9e070e33 引入后契约未同步）。
        ("POST", "/api/v1/media/course/{course_id}/releases/{release_id}/ppt-manifest/sync", "build_ppt_manifest", "app.api.v1.endpoints.media_release"),
    })
    assert {(row["method"], row["path"], row["endpoint"], row["module"]) for row in hidden_rows} == expected_hidden


def test_route_contract_locks_known_duplicate_document_routes(fastapi_app):
    rows = _route_rows(fastapi_app)
    counts = Counter((row["method"], row["path"]) for row in rows)

    assert counts[("GET", "/api/v1/document/courses")] == 1
    # The compatibility route is registered once.  A duplicate registration
    # produces ambiguous OpenAPI operation IDs and must not return.
    assert counts[("POST", "/api/v1/document/course/{course_id}/save")] == 1

    assert not any(
        key == ("POST", "/api/v1/document/course/{course_id}/save")
        and count > 1
        for key, count in counts.items()
    )


def test_route_contract_locks_document_router_double_mount(fastapi_app):
    rows = _route_rows(fastapi_app)
    paths = {row["path"] for row in rows}

    assert "/api/v1/document/upload" in paths
    assert "/api/v1/chat/file/upload" in paths
    assert "/api/v1/document/course/{course_id}/slides" in paths
    assert "/api/v1/chat/file/course/{course_id}/slides" in paths


def test_route_contract_locks_video_gen_and_known_absent_old_routes(fastapi_app):
    rows = _route_rows(fastapi_app)
    paths = {row["path"] for row in rows}

    assert "/api/v1/video-gen/health" in paths
    assert "/api/v1/video-gen/course/{course_id}/generate" in paths
    assert "/api/v1/video-generation/health" not in paths
    assert "/api/v1/video-generation/course/{course_id}/generate" not in paths


def test_route_contract_marks_unconsumed_legacy_chat_session_routes_deprecated(fastapi_app):
    rows = _route_rows(fastapi_app)
    paths = {row["path"] for row in rows}

    assert "/api/v1/chat/create" in paths
    assert "/api/v1/chat/messages/{chat_id}" in paths
    assert "/api/v1/chat/{chat_id}" not in paths

    openapi_paths = fastapi_app.openapi()["paths"]
    assert openapi_paths["/api/v1/chat/create"]["post"]["deprecated"] is True
    assert openapi_paths["/api/v1/chat/messages/{chat_id}"]["get"]["deprecated"] is True

def test_route_contract_document_my_courses_precedes_document_id(fastapi_app):
    rows = _route_rows(fastapi_app)
    my_courses_rows = [
        row for row in rows
        if row["method"] == "GET" and row["path"] == "/api/v1/document/my-courses"
    ]
    document_id_rows = [
        row for row in rows
        if row["method"] == "GET" and row["path"] == "/api/v1/document/{document_id}"
    ]

    assert len(my_courses_rows) == 1
    assert len(document_id_rows) == 1
    assert my_courses_rows[0]["endpoint"] == "get_my_courses"
    assert my_courses_rows[0]["index"] < document_id_rows[0]["index"]
