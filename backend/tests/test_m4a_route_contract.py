from collections import Counter, defaultdict

from fastapi.routing import APIRoute


def _route_rows(app):
    openapi_paths = set(app.openapi()["paths"].keys())
    rows = []
    for index, route in enumerate(app.routes):
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(method for method in route.methods if method not in {"HEAD", "OPTIONS"})
        for method in methods:
            rows.append({
                "index": index,
                "method": method,
                "path": route.path,
                "endpoint": route.endpoint.__name__,
                "module": route.endpoint.__module__,
                "in_openapi": route.path in openapi_paths,
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

    assert {(row["method"], row["path"], row["endpoint"], row["module"]) for row in hidden_rows} == {
        ("DELETE", "/{path:path}", "catch_all", "app.main"),
        ("GET", "/{path:path}", "catch_all", "app.main"),
        ("PATCH", "/{path:path}", "catch_all", "app.main"),
        ("POST", "/{path:path}", "catch_all", "app.main"),
        ("PUT", "/{path:path}", "catch_all", "app.main"),
    }


def test_route_contract_locks_known_duplicate_document_routes(fastapi_app):
    rows = _route_rows(fastapi_app)
    counts = Counter((row["method"], row["path"]) for row in rows)

    assert counts[("GET", "/api/v1/document/courses")] == 2
    assert counts[("POST", "/api/v1/document/course/{course_id}/save")] == 2

    duplicate_rows = defaultdict(list)
    for row in rows:
        if counts[(row["method"], row["path"])] > 1:
            duplicate_rows[(row["method"], row["path"])].append(row)

    assert [row["endpoint"] for row in duplicate_rows[("GET", "/api/v1/document/courses")]] == [
        "get_courses_list",
        "get_courses_list",
    ]
    assert [row["endpoint"] for row in duplicate_rows[("POST", "/api/v1/document/course/{course_id}/save")]] == [
        "save_course_nodes",
        "save_course_nodes",
    ]


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


def test_route_contract_locks_frontend_chat_path_mismatch(fastapi_app):
    rows = _route_rows(fastapi_app)
    paths = {row["path"] for row in rows}

    assert "/api/v1/chat/messages/{chat_id}" in paths
    assert "/api/v1/chat/{chat_id}" not in paths

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
