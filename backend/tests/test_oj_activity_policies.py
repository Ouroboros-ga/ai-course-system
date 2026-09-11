"""契约：OJ Activity 域的纯规则（值域 / 时间窗 / 版本固定 / 确定性算分）。

与 `test_oj_problem_metadata.py` 同一取向：域层不依赖 ORM / session，
测试 therefore 只 import 域模块。**确定性算分**是 DoD 的硬要求，
所以顺序敏感与浮点精度在这里单独成组钉住。
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.oj.activity import (
    ACTIVITY_STATUSES,
    ACTIVITY_TYPES,
    MAX_PROBLEMS_PER_ACTIVITY,
    RANKING_MODES,
    SCORING_MODES,
    SCOPE_TYPES,
    SUPPORTED_ACTIVITY_TYPES,
    ActivityStatus,
    ActivityType,
    assert_pinned_versions,
    assert_supported_type,
    assert_unique_ordinals,
    compute_homework_score,
    is_submission_open,
    normalize_activity_status,
    normalize_activity_type,
    normalize_ordinal,
    normalize_ranking_mode,
    normalize_scoring_mode,
    normalize_scope_type,
    validate_scope_payload,
    validate_time_window,
)

_T0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 值域
# ---------------------------------------------------------------------------


class TestValueDomains:
    def test_type_vocabulary_has_all_four(self):
        """4 值一次建全 —— 加行为不动表（本 PR 的拍板结论）。"""
        assert ACTIVITY_TYPES == {"homework", "contest", "exam", "practice_set"}

    def test_only_homework_is_supported_now(self):
        assert SUPPORTED_ACTIVITY_TYPES == {"homework"}

    def test_status_aligned_with_experiment_publish_status(self):
        """与既有 `ExperimentPublishStatus` 取值集一致（draft/published/archived）。

        两域独立定义但取值集相同 —— 跨域一致性由本断言守住，
        有人只改一边时这里会红。
        """
        from app.models.experiment_model import ExperimentPublishStatus

        assert ACTIVITY_STATUSES == {s.value for s in ExperimentPublishStatus}

    def test_no_closed_status(self):
        """**刻意没有 closed**：结束与否由 end_at 推导，不存可漂移的状态位。"""
        assert "closed" not in ACTIVITY_STATUSES

    def test_unimplemented_modes_narrowed(self):
        """排行/算分只收**已实现**的值 —— 防止建出没人实现语义的活动。"""
        assert SCORING_MODES == {"sum"}
        assert RANKING_MODES == {"none", "icpc"}

    def test_scope_types(self):
        assert SCOPE_TYPES == {"course", "class", "user"}


class TestNormalize:
    @pytest.mark.parametrize("given,expected", [
        ("HOMEWORK", "homework"),
        ("  Contest ", "contest"),
        (ActivityType.EXAM, "exam"),
        (None, "homework"),
        ("", "homework"),
    ])
    def test_activity_type(self, given, expected):
        assert normalize_activity_type(given) == expected

    def test_activity_type_invalid_raises_not_fallback(self):
        """非法值抛错不兜底 —— 与 `normalize_difficulty` 同一原则。"""
        with pytest.raises(ValueError, match="活动类型"):
            normalize_activity_type("olympiad")

    @pytest.mark.parametrize("given,expected", [
        ("DRAFT", "draft"), ("Published", "published"),
        (ActivityStatus.ARCHIVED, "archived"), (None, "draft"), ("", "draft"),
    ])
    def test_activity_status(self, given, expected):
        assert normalize_activity_status(given) == expected

    @pytest.mark.parametrize("given,expected", [
        ("SUM", "sum"), (None, "sum"), ("", "sum"),
    ])
    def test_scoring_mode(self, given, expected):
        assert normalize_scoring_mode(given) == expected

    @pytest.mark.parametrize("given,expected", [
        ("NONE", "none"), ("ICPC", "icpc"), (None, "none"),
    ])
    def test_ranking_mode(self, given, expected):
        assert normalize_ranking_mode(given) == expected

    @pytest.mark.parametrize("given,expected", [
        ("COURSE", "course"), ("User", "user"), (None, "course"),
    ])
    def test_scope_type(self, given, expected):
        assert normalize_scope_type(given) == expected

    def test_unsupported_type_rejected_explicitly(self):
        """**合法但未实现**的 type 必须被显式拒绝，绝不静默当 homework。"""
        assert "contest" in ACTIVITY_TYPES  # 合法
        with pytest.raises(ValueError, match="尚未实现"):
            assert_supported_type("contest")
        assert_supported_type("homework")  # 不抛


# ---------------------------------------------------------------------------
# 时间窗
# ---------------------------------------------------------------------------


class TestTimeWindow:
    def test_end_must_be_after_start(self):
        with pytest.raises(ValueError, match="必须晚于"):
            validate_time_window(_T0, _T0 - timedelta(hours=1))
        validate_time_window(_T0, _T0 + timedelta(hours=1))  # 不抛
        validate_time_window(None, None)  # 不限时合法
        validate_time_window(_T0, None)  # 只给开始合法

    def test_not_started(self):
        allowed, reason = is_submission_open(
            _T0 - timedelta(seconds=1), start_at=_T0, end_at=None
        )
        assert (allowed, reason) == (False, "not_started")

    def test_ended_without_late(self):
        allowed, reason = is_submission_open(
            _T0 + timedelta(hours=2), start_at=_T0, end_at=_T0 + timedelta(hours=1)
        )
        assert (allowed, reason) == (False, "ended")

    def test_late_submit_is_distinguishable_from_open(self):
        """**迟交必须能和准时区分** —— 只返回 bool 会把两者混在一起。"""
        allowed, reason = is_submission_open(
            _T0 + timedelta(hours=2), start_at=_T0, end_at=_T0 + timedelta(hours=1),
            allow_late_submit=True,
        )
        assert (allowed, reason) == (True, "late")

    def test_open_inside_window(self):
        allowed, reason = is_submission_open(
            _T0 + timedelta(minutes=30), start_at=_T0, end_at=_T0 + timedelta(hours=1)
        )
        assert (allowed, reason) == (True, "open")

    def test_unbounded_window_is_always_open(self):
        for offset in (timedelta(0), timedelta(days=400)):
            allowed, reason = is_submission_open(_T0 + offset, start_at=None, end_at=None)
            assert (allowed, reason) == (True, "open")


# ---------------------------------------------------------------------------
# 版本固定（DoD：同一 Activity 固定 problem_version_id）
# ---------------------------------------------------------------------------


class TestVersionPinning:
    def test_single_version_returned(self):
        assert assert_pinned_versions(["v1", "v1"]) == "v1"

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="至少需要一个版本"):
            assert_pinned_versions([])

    def test_same_problem_with_two_versions_rejected(self):
        """同一道题出现两行且版本不同 → 拒绝（"这道题的版本"失去意义）。"""
        with pytest.raises(ValueError, match="同一道题"):
            assert_pinned_versions(["ver_aaa", "ver_bbb"])

    def test_one_problem_is_enough(self):
        assert assert_pinned_versions(["only"]) == "only"

    def test_unique_ordinals(self):
        assert assert_unique_ordinals([3, 1, 2]) == [1, 2, 3]
        with pytest.raises(ValueError, match="题序重复"):
            assert_unique_ordinals([1, 2, 2])

    def test_immutable_after_publish(self):
        from app.domain.oj.activity import assert_immutable_after_publish

        assert_immutable_after_publish("draft", "题目集合")  # 不抛
        with pytest.raises(ValueError, match="不可变更"):
            assert_immutable_after_publish("published", "题目集合")
        assert_immutable_after_publish("archived", "题目集合")  # 归档后同样把门



class TestOrdinal:
    def test_positive_integers_accepted(self):
        assert normalize_ordinal(1) == 1
        assert normalize_ordinal("3") == 3
        assert normalize_ordinal(2.0) == 2

    @pytest.mark.parametrize("bad", [0, -1, 1.5, "x", None, True])
    def test_invalid_rejected(self, bad):
        with pytest.raises(ValueError):
            normalize_ordinal(bad)


# ---------------------------------------------------------------------------
# 确定性算分（DoD：score 可重算且 deterministic）
# ---------------------------------------------------------------------------


class TestDeterministicScoring:
    def test_sum_is_independent_of_input_order(self):
        """**核心 DoD**：同一组题不管以什么顺序传入，总分必须逐位一致。

        浮点加法不满足交换律，所以域层先按 ordinal 排序再求和。
        """
        a = [(1, "p1", 0.7, 5.0), (2, "p2", 0.9, 5.0)]
        b = [(2, "p2", 0.9, 5.0), (1, "p1", 0.7, 5.0)]
        assert compute_homework_score(a) == compute_homework_score(b)

    def test_repeated_recompute_is_stable(self):
        """重算 100 次必须逐字节相同 —— 「可重算且 deterministic」的字面验证。"""
        data = [(i, f"p{i}", 0.1 * (i % 7), 3.0) for i in range(1, 11)]
        first = compute_homework_score(data)
        for _ in range(100):
            assert compute_homework_score(data) == first

    def test_score_and_max_totals(self):
        result = compute_homework_score([(1, "p1", 1.0, 5.0), (2, "p2", 0.5, 5.0)])
        assert result["total"] == 7.5
        assert result["max_total"] == 10.0
        assert [d["ordinal"] for d in result["per_problem"]] == [1, 2]

    def test_empty_activity_scores_zero(self):
        assert compute_homework_score([]) == {"total": 0.0, "max_total": 0.0, "per_problem": []}

    def test_out_of_range_score_rejected_not_clamped(self):
        """越界分是**上游判分坏了**的信号，clamp 会把坏分伪装成满分。"""
        with pytest.raises(ValueError, match="越界"):
            compute_homework_score([(1, "p1", 1.5, 5.0)])
        with pytest.raises(ValueError, match="越界"):
            compute_homework_score([(1, "p1", -0.1, 5.0)])

    def test_negative_max_rejected(self):
        with pytest.raises(ValueError, match="不能为负"):
            compute_homework_score([(1, "p1", 1.0, -1.0)])


# ---------------------------------------------------------------------------
# scope
# ---------------------------------------------------------------------------


class TestScopeValidation:
    def test_valid_course_scope(self):
        assert validate_scope_payload("COURSE", 42) == ("course", 42)

    def test_missing_id_rejected(self):
        with pytest.raises(ValueError, match="scope_id"):
            validate_scope_payload("course", None)

    def test_bad_id_rejected(self):
        for bad in (0, -3, 1.5, True, "x"):
            with pytest.raises(ValueError):
                validate_scope_payload("course", bad)

    def test_bad_type_rejected(self):
        with pytest.raises(ValueError, match="可见范围"):
            validate_scope_payload("school", 1)


# ---------------------------------------------------------------------------
# 域层纯度与防回归（与 test_oj_problem_metadata 同一取向）
# ---------------------------------------------------------------------------


class TestActivityDomainPurity:
    def test_policy_module_imports_nothing_from_models_or_services(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "app" / "domain" / "oj" / "activity" / "policies.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        for mod in imported:
            for forbidden in ("app.models", "app.services", "sqlmodel", "sqlalchemy"):
                assert not (mod == forbidden or mod.startswith(forbidden + ".")), (
                    f"域模块 import 了 `{mod}` —— 域层不得依赖 ORM / 服务层"
                )

    def test_no_utf8_bom(self):
        for name in ("policies.py", "__init__.py"):
            path = (
                Path(__file__).resolve().parents[1]
                / "app" / "domain" / "oj" / "activity" / name
            )
            assert path.read_bytes()[:3] != b"\xef\xbb\xbf", f"{name} 带了 UTF-8 BOM"

    def test_problem_cap_is_sane(self):
        assert 1 <= MAX_PROBLEMS_PER_ACTIVITY <= 500
