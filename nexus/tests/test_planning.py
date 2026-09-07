"""NX-H1 计划产品投影单元测试（planning.py 纯函数）。"""

from nexus.planning import plan_snapshot, normalize_todos


def test_snapshot_minimum_semantics():
    """任务书 §4 最低语义：session/plan/revision/items/source 全在。"""
    snap = plan_snapshot(
        "synthetic-session",
        [{"content": "读取论文证据", "status": "in_progress"}],
        revision=2,
    )
    assert snap is not None
    assert snap["session_id"] == "synthetic-session"
    assert snap["plan_id"].startswith("plan-")
    assert snap["revision"] == 2
    assert snap["source"] == "agent_plan"
    assert snap["items"] == [{"id": snap["items"][0]["id"], "content": "读取论文证据", "status": "in_progress"}]


def test_item_ids_stable_across_revisions():
    """同内容跨 revision 的条目 id 稳定；状态变化不换 id。"""
    todos_v1 = [{"content": "读取证据", "status": "pending"}, {"content": "综合", "status": "pending"}]
    todos_v2 = [{"content": "读取证据", "status": "completed"}, {"content": "综合", "status": "in_progress"}]
    s1 = plan_snapshot("s", todos_v1, revision=1)
    s2 = plan_snapshot("s", todos_v2, revision=2)
    assert [i["id"] for i in s1["items"]] == [i["id"] for i in s2["items"]]
    assert s1["items"][0]["status"] == "pending" and s2["items"][0]["status"] == "completed"


def test_duplicate_content_gets_stable_suffix():
    """重复内容条目 id 唯一且跨投影稳定。"""
    todos = [{"content": "same", "status": "pending"}, {"content": "same", "status": "completed"}]
    s1 = plan_snapshot("s", todos, revision=1)
    s2 = plan_snapshot("s", todos, revision=2)
    ids1 = [i["id"] for i in s1["items"]]
    assert len(set(ids1)) == 2
    assert ids1 == [i["id"] for i in s2["items"]]


def test_plan_id_stable_per_session_and_differs_across():
    """同会话 plan_id 恒定（全量替换不换 id）；不同会话不共享。"""
    a1 = plan_snapshot("sess-a", [{"content": "x", "status": "pending"}], revision=1)
    a2 = plan_snapshot("sess-a", [{"content": "y", "status": "completed"}], revision=2)
    b = plan_snapshot("sess-b", [{"content": "x", "status": "pending"}], revision=1)
    assert a1["plan_id"] == a2["plan_id"]
    assert a1["plan_id"] != b["plan_id"]


def test_invalid_todos_return_none():
    """非 list / 空条目 / 全非法 → None（不 emit 空计划）。"""
    assert plan_snapshot("s", None, revision=1) is None
    assert plan_snapshot("s", [], revision=1) is None
    assert plan_snapshot("s", "not-a-list", revision=1) is None
    assert plan_snapshot("s", [{"content": "", "status": "pending"}], revision=1) is None
    assert plan_snapshot("s", ["plain-string"], revision=1) is None
    # 非法 status 丢弃：不猜测语义（不 coerce 成 pending）。
    assert plan_snapshot("s", [{"content": "a", "status": "cancelled"}], revision=1) is None
    mixed = plan_snapshot(
        "s",
        [{"content": "ok", "status": "pending"}, {"content": "bad", "status": "failed"}],
        revision=1,
    )
    assert [i["content"] for i in mixed["items"]] == ["ok"]


def test_content_truncated_and_enumeration_stays_native():
    """内容截断 200 字符；状态枚举保持 middleware 原生三值。"""
    long = "x" * 500
    snap = plan_snapshot("s", [{"content": long, "status": "completed"}], revision=1)
    assert len(snap["items"][0]["content"]) == 200
    assert normalize_todos([{"content": "a", "status": "pending"},
                            {"content": "b", "status": "in_progress"},
                            {"content": "c", "status": "completed"}]) is not None
