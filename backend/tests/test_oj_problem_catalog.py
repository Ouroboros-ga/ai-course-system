"""B1/B2 域层：题库的筛选 / 排序 / 编号规则（`domain/oj/problems/catalog.py`）。

纯函数测试，不碰 DB、不碰 HTTP。这里钉住的是「多条调用路径必须共享同一套规则」
的那几条 —— 它们一旦分裂，症状是「列表显示 #007、点进去显示 #009」这类
谁也说不清哪个对的问题。
"""
from __future__ import annotations

import pytest

from app.domain.oj.problems.catalog import (
    CLEAR_SOURCE,
    CLEAR_YEAR,
    MAX_SOURCE_LENGTH,
    MAX_YEAR,
    MIN_YEAR,
    ProblemSortRecord,
    build_problem_no_index,
    compare_records,
    difficulty_rank,
    format_problem_no,
    matches_search,
    matches_tags,
    normalize_search_in,
    normalize_sort_by,
    normalize_sort_order,
    normalize_source,
    normalize_tag_mode,
    normalize_year,
    problem_no_for,
    resolve_difficulty_bounds,
    sort_records_with,
)


class TestSourceNormalization:
    def test_trims_and_keeps_case(self):
        """`ICPC` / `Codeforces` 是专名，不做大小写归并。"""
        assert normalize_source("  Codeforces  ") == "Codeforces"
        assert normalize_source("ICPC") == "ICPC"
        assert normalize_source("icpc") == "icpc"

    def test_empty_becomes_none(self):
        """空串 = 清空（`None` 已被 PATCH 的「别动」占用）。"""
        assert normalize_source(CLEAR_SOURCE) == None  # noqa: E711
        assert normalize_source("   ") is None
        assert normalize_source(None) is None

    def test_over_length_raises_instead_of_truncating(self):
        with pytest.raises(ValueError):
            normalize_source("x" * (MAX_SOURCE_LENGTH + 1))
        # 边界值仍然合法 —— 否则 off-by-one 会把最长合法值也拦掉
        assert normalize_source("x" * MAX_SOURCE_LENGTH) == "x" * MAX_SOURCE_LENGTH

    def test_column_width_matches_domain_constant(self):
        """与 `ExperimentDefinition.source` 的 max_length 必须一致。

        迁移文件不 import 应用代码，模型列宽也只能写死，因此一致性靠这条字面量
        断言守住（与 PR-09 的 `_DEFAULT_DIFFICULTY` 同一手法）。
        """
        assert MAX_SOURCE_LENGTH == 64


class TestYearNormalization:
    def test_accepts_int_and_digit_string(self):
        assert normalize_year(2026) == 2026
        assert normalize_year("2026") == 2026
        assert normalize_year(" 2019 ") == 2019

    def test_clear_and_unset_both_become_none(self):
        assert normalize_year(CLEAR_YEAR) == None  # noqa: E711
        assert normalize_year(None) is None
        assert normalize_year("") is None
        assert normalize_year("   ") is None

    def test_out_of_range_raises_instead_of_clamping(self):
        """越界是「填错」不是「越界就夹到边界」——夹边界会造出教师没填过的值。"""
        with pytest.raises(ValueError):
            normalize_year(MIN_YEAR - 1)
        with pytest.raises(ValueError):
            normalize_year(MAX_YEAR + 1)
        assert normalize_year(MIN_YEAR) == MIN_YEAR
        assert normalize_year(MAX_YEAR) == MAX_YEAR

    def test_rejects_non_numeric_and_bool(self):
        with pytest.raises(ValueError):
            normalize_year("两千")
        with pytest.raises(ValueError):
            normalize_year("20x6")
        # bool 是 int 的子类 —— 不显式拦截会让 `year=True` 静默变成 1（再被判越界）
        with pytest.raises(ValueError):
            normalize_year(True)


class TestSearchScope:
    def test_empty_keyword_matches_everything(self):
        assert matches_search(title="任意", description="", keyword=None)
        assert matches_search(title="任意", description="", keyword="")
        assert matches_search(title="任意", description="", keyword="   ")

    def test_title_scope_ignores_statement(self):
        """「搜索题面」没勾时，题面里的关键词不该命中 —— 否则勾选框形同虚设。"""
        assert not matches_search(
            title="两数之和", description="用 dijkstra 求最短路", keyword="dijkstra",
        )
        assert matches_search(
            title="两数之和", description="用 dijkstra 求最短路", keyword="dijkstra",
            scope="statement",
        )
        assert matches_search(
            title="两数之和", description="用 dijkstra 求最短路", keyword="dijkstra",
            scope="both",
        )

    def test_case_insensitive(self):
        assert matches_search(title="Dijkstra 模板", description="", keyword="dijkstra")
        assert matches_search(title="两数之和", description="BFS 求最短路", keyword="bfs",
                              scope="statement")

    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError):
            normalize_search_in("everywhere")
        assert normalize_search_in(None) == "title"
        assert normalize_search_in(" BOTH ") == "both"


class TestTagMatching:
    def test_empty_wanted_matches_everything(self):
        assert matches_tags(["数组"], None)
        assert matches_tags(["数组"], [])
        assert matches_tags(None, [])

    def test_and_mode_requires_all(self):
        assert matches_tags(["数组", "哈希"], ["数组", "哈希"])
        assert not matches_tags(["数组"], ["数组", "哈希"])

    def test_or_mode_requires_any(self):
        assert matches_tags(["数组"], ["数组", "哈希"], "or")
        assert not matches_tags(["树"], ["数组", "哈希"], "or")

    def test_casefold_but_keeps_original_display(self):
        """教师填 `DP`、按 `dp` 筛 —— 命中，但展示仍是 `DP`（与 normalize_tags 同取向）。"""
        assert matches_tags(["DP"], ["dp"])
        assert matches_tags(["dp"], ["DP"])
        assert not matches_tags(["DP"], ["图论"])

    def test_blank_entries_are_ignored(self):
        """空白标签不构成筛选条件。

        返回 True（= 不过滤）而不是 False：调用方传了 `["   "]` 时若按「必须命中
        空白标签」处理，结果集会被静默清空 —— 那是个极难排查的「筛选没结果」。
        与 `normalize_tags` 丢弃空串的取向一致。
        """
        assert matches_tags(["  "], None)
        assert matches_tags(["数组"], ["   "])

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            normalize_tag_mode("xor")
        assert normalize_tag_mode(None) == "and"


class TestDifficultyBounds:
    def test_no_bounds_means_no_filter(self):
        assert resolve_difficulty_bounds(None, None) is None

    def test_single_value_is_exact_match(self):
        """旧的单值 `difficulty=hard` 语义必须保持：只命中 hard。"""
        assert resolve_difficulty_bounds("hard", "hard") == {"hard"}

    def test_min_only_is_open_ended_upwards(self):
        assert resolve_difficulty_bounds("medium", None) == {"medium", "hard"}

    def test_max_only_is_open_ended_downwards(self):
        assert resolve_difficulty_bounds(None, "medium") == {"easy", "medium"}

    def test_reversed_bounds_yield_empty_not_error(self):
        """端点拖反了 → 空结果集（用户语义上确实没有任何题满足），
        不抛 422 —— 抛错会逼前端为「拖反滑块」单独写一处错误处理。"""
        assert resolve_difficulty_bounds("hard", "easy") == set()

    def test_invalid_value_still_raises(self):
        with pytest.raises(ValueError):
            resolve_difficulty_bounds("impossible", None)

    def test_rank_order_is_monotonic(self):
        assert difficulty_rank("easy") < difficulty_rank("medium") < difficulty_rank("hard")

    def test_blank_difficulty_takes_the_default_rank(self):
        """空值不是第四档 —— `normalize_difficulty` 已把「没填」归为 medium。

        存储层是 NOT NULL + server_default=medium，产生不出「未标注」难度；
        域层再造一个 rank 0 的幽灵档位会让排序结果无法解释。
        """
        assert difficulty_rank(None) == difficulty_rank("") == difficulty_rank("medium") == 2


class TestProblemNoDerivation:
    def test_pads_to_three_digits(self):
        assert format_problem_no(1) == "#001"
        assert format_problem_no(15) == "#015"
        assert format_problem_no(999) == "#999"
        assert format_problem_no(1000) == "#1000"

    def test_invalid_sequence_returns_placeholder_not_exception(self):
        for value in (0, -1, None, "abc"):
            assert format_problem_no(value) == "—"

    def test_index_is_order_independent(self):
        a = build_problem_no_index(["exp_c", "exp_a", "exp_b"])
        b = build_problem_no_index(["exp_b", "exp_c", "exp_a"])
        assert a == b == {"exp_a": 1, "exp_b": 2, "exp_c": 3}

    def test_index_dedupes(self):
        assert build_problem_no_index(["exp_a", "exp_a", "exp_b"]) == {"exp_a": 1, "exp_b": 2}

    def test_codepoint_order_not_locale_order(self):
        """前端 `ojTheme` 用 `<`/`>`（code-point），Python `sorted` 默认也是 code-point。

        这条把口径钉死：若前端改用 `localeCompare`，`'exp_a-1'` 与 `'exp_a_1'`
        会因为标点被 locale 忽略而排出不同顺序，同一批题在两端的题号就会不一致。
        """
        ids = ["exp_a_1", "exp_a-1", "exp_ab"]
        assert build_problem_no_index(ids) == {
            "exp_a-1": 1,   # '-' = 0x2D
            "exp_a_1": 2,   # '_' = 0x5F
            "exp_ab": 3,    # 'b' = 0x62
        }

    def test_numbering_must_come_from_the_unfiltered_catalog(self):
        """反向验证：拿筛选后的结果编号，整列题号会平移。

        这是 B1 刻意让服务端统一下发 `problem_no` 的原因 —— 前端在
        `ojTheme.test.js` 里有同一条反向验证。
        """
        catalog = ["exp_a", "exp_b", "exp_c"]
        full = build_problem_no_index(catalog)
        assert problem_no_for(full, "exp_c") == "#003"

        filtered = [i for i in catalog if i != "exp_b"]
        assert problem_no_for(build_problem_no_index(filtered), "exp_c") == "#002"

    def test_unknown_problem_gets_placeholder(self):
        assert problem_no_for({"exp_a": 1}, "exp_zzz") == "—"


class TestSorting:
    @staticmethod
    def _record(no, title, difficulty, pass_rate, attempt_total=0):
        return ProblemSortRecord(
            problem_no=no, title=title, difficulty=difficulty,
            pass_rate=pass_rate, attempt_total=attempt_total,
        )

    def test_default_sorts_by_problem_no(self):
        records = [
            self._record(3, "c", "hard", 0.1),
            self._record(1, "a", "easy", 0.9),
            self._record(2, "b", "medium", 0.5),
        ]
        ordered = sort_records_with(records)
        assert [r.problem_no for r in ordered] == [1, 2, 3]

    def test_difficulty_sorts_by_rank_not_alphabet(self):
        """字典序会给 hard < medium（h < m）——难度排序必须走档位权重。"""
        records = [
            self._record(1, "a", "hard", None),
            self._record(2, "b", "easy", None),
            self._record(3, "c", "medium", None),
        ]
        assert [r.difficulty for r in sort_records_with(records, sort_by="difficulty")] == [
            "easy", "medium", "hard",
        ]

    def test_missing_pass_rate_sinks_regardless_of_direction(self):
        """「还没人交过」不是 0% —— 升序不该把它顶成第一名，降序也不该。"""
        records = [
            self._record(1, "有数据低", "easy", 0.1),
            self._record(2, "无数据", "easy", None),
            self._record(3, "有数据高", "easy", 0.9),
        ]
        asc = [r.title for r in sort_records_with(records, sort_by="pass_rate")]
        desc = [r.title for r in sort_records_with(
            records, sort_by="pass_rate", sort_order="desc"
        )]
        assert asc == ["有数据低", "有数据高", "无数据"]
        assert desc == ["有数据高", "有数据低", "无数据"]

    def test_desc_reverses_values_not_missingness(self):
        records = [
            self._record(1, "a", "easy", None, attempt_total=1),
            self._record(2, "b", "easy", None, attempt_total=9),
        ]
        ordered = sort_records_with(records, sort_by="attempt_total", sort_order="desc")
        assert [r.attempt_total for r in ordered] == [9, 1]

    def test_compare_records_is_antisymmetric(self):
        left = self._record(1, "a", "easy", 0.2)
        right = self._record(2, "b", "hard", 0.8)
        assert compare_records(left, right, sort_by="pass_rate") == -1
        assert compare_records(right, left, sort_by="pass_rate") == 1
        assert compare_records(left, left, sort_by="pass_rate") == 0

    def test_sort_does_not_mutate_input(self):
        records = [
            self._record(2, "b", "medium", 0.5),
            self._record(1, "a", "easy", 0.9),
        ]
        sort_records_with(records, sort_by="no")
        assert [r.problem_no for r in records] == [2, 1]

    def test_invalid_sort_arguments_raise(self):
        with pytest.raises(ValueError):
            normalize_sort_by("popularity")
        with pytest.raises(ValueError):
            normalize_sort_order("sideways")
        assert normalize_sort_by(None) == "default"
        assert normalize_sort_order(" DESC ") == "desc"
