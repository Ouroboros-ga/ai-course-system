"""契约：OJ 题目元数据（难度 / 标签）的域规则。

覆盖 `domain/oj/problems/metadata.py` 的规范化与校验，
并守住两条跨模块契约：

1. **与 `QuestionDifficulty` 取值集一致** —— 两域独立定义枚举
   （刻意不共用，见 metadata.py 的说明），但取值集必须始终相同，
   否则全站难度语义会分裂；
2. **非法难度抛错而非兜底** —— 与 `question_generation_llm` 的
   「非法 → medium」策略有意不同，本组把这个差异钉住，防止有人
   从那个文件照抄兜底逻辑过来。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.domain.oj.problems import (
    DEFAULT_DIFFICULTY,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    ProblemDifficulty,
    normalize_difficulty,
    normalize_tags,
    valid_difficulty_values,
)


class TestDifficultyValues:
    def test_exactly_three_levels(self):
        assert valid_difficulty_values() == {"easy", "medium", "hard"}

    def test_matches_question_bank_difficulty_values(self):
        """跨域契约：与 `QuestionDifficulty` 取值集**必须相同**。

        两域独立定义（避免 bounded context 被一个 Python 枚举绑死），
        但取值集一致是全站难度语义统一的前提。有人只改一边时本断言会红。
        """
        from app.models.question_bank_model import QuestionDifficulty

        ours = valid_difficulty_values()
        theirs = {d.value for d in QuestionDifficulty}
        assert ours == theirs, (
            f"OJ 与问答库的难度取值集已分裂：ours={sorted(ours)} theirs={sorted(theirs)}"
        )

    def test_default_difficulty_is_medium(self):
        assert DEFAULT_DIFFICULTY == "medium"

    def test_default_matches_question_generation_fallback(self):
        """默认值应与出题流水线的兜底一致（都落到 medium）。"""
        source = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "question_generation_llm.py"
        ).read_text(encoding="utf-8-sig")
        assert 'result.get("difficulty") or "medium"' in source, (
            "question_generation_llm 的 difficulty 兜底不再是 medium —— 两处默认值已不一致"
        )


class TestNormalizeDifficulty:
    @pytest.mark.parametrize("value", ["easy", "medium", "hard"])
    def test_accepts_lowercase(self, value):
        assert normalize_difficulty(value) == value

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("EASY", "easy"),
            ("  Hard  ", "hard"),
            ("Medium", "medium"),
        ],
    )
    def test_is_case_and_whitespace_insensitive(self, value, expected):
        assert normalize_difficulty(value) == expected

    def test_accepts_enum_member(self):
        assert normalize_difficulty(ProblemDifficulty.HARD) == "hard"

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_means_use_default(self, value):
        assert normalize_difficulty(value) == DEFAULT_DIFFICULTY

    @pytest.mark.parametrize("value", ["trivial", "expert", "3", "1", "easyy", 0, 3])
    def test_invalid_values_raise_not_fallback(self, value):
        """**这是与 `question_generation_llm` 的关键差异**：

        那边非法值静默兜底为 medium（LLM 输出脏值是预期内的）；
        这边教师显式填写，填错必须报错 ——
        静默兜底会产生「我写了 hard 怎么存成 medium」这类无从排查的问题。
        """
        with pytest.raises(ValueError, match="难度取值非法"):
            normalize_difficulty(value)

    def test_numeric_1_to_5_is_rejected(self):
        """明确拒绝 1–5 整数制：那是 knowledge.py 的取值域，不是本域的。"""
        for n in (1, 2, 3, 4, 5):
            with pytest.raises(ValueError):
                normalize_difficulty(n)


class TestNormalizeTags:
    def test_none_becomes_empty_list(self):
        assert normalize_tags(None) == []

    def test_empty_list_stays_empty(self):
        assert normalize_tags([]) == []

    def test_strips_whitespace(self):
        assert normalize_tags(["  dp  ", "\t贪心\n"]) == ["dp", "贪心"]

    def test_drops_empty_entries(self):
        """教师在输入框多敲的回车不该变成空标签。"""
        assert normalize_tags(["dp", "", "   ", "贪心"]) == ["dp", "贪心"]

    def test_deduplicates_case_insensitively_keeping_order(self):
        assert normalize_tags(["DP", "dp", "Dp", "贪心"]) == ["DP", "贪心"]

    def test_keeps_first_occurrence_spelling(self):
        """保留**首次出现**的写法 —— 那是教师的原始意图，不做大小写归并。

        中文标签无大小写概念，英文缩写 DP / SQL 全大写才是惯用写法；
        归并会把教师的 DP 改成 dp。
        """
        assert normalize_tags(["SQL", "sql"]) == ["SQL"]
        assert normalize_tags(["sql", "SQL"]) == ["sql"]

    def test_coerces_non_string_items(self):
        assert normalize_tags([123, "dp"]) == ["123", "dp"]

    def test_unicode_chinese_tags_preserved(self):
        got = normalize_tags(["动态规划", "贪心", "图论"])
        assert got == ["动态规划", "贪心", "图论"]

    def test_accepts_tuple_and_set_input(self):
        assert normalize_tags(("dp", "贪心")) == ["dp", "贪心"]

    def test_tag_too_long_raises(self):
        with pytest.raises(ValueError, match="标签过长"):
            normalize_tags(["x" * (MAX_TAG_LENGTH + 1)])

    def test_tag_at_exact_limit_is_accepted(self):
        tag = "x" * MAX_TAG_LENGTH
        assert normalize_tags([tag]) == [tag]

    def test_too_many_tags_raises(self):
        many = [f"tag{i}" for i in range(MAX_TAGS + 1)]
        with pytest.raises(ValueError, match="标签过多"):
            normalize_tags(many)

    def test_exactly_max_tags_is_accepted(self):
        many = [f"tag{i}" for i in range(MAX_TAGS)]
        assert len(normalize_tags(many)) == MAX_TAGS

    def test_dedup_happens_before_count_check(self):
        """去重后不超限就不该报错 —— 否则 ["dp","DP","dp"] 这种会被误拒。"""
        dup = ["dp", "DP", "dp"] * (MAX_TAGS // 3 + 1)
        assert normalize_tags(dup) == ["dp"]

    def test_returns_new_list(self):
        source = ["dp"]
        got = normalize_tags(source)
        got.append("mutated")
        assert source == ["dp"], "必须返回新 list，不能把调用方的 list 直接暴露"


class TestProblemMetadataPurity:
    """域层约束：不依赖 ORM / 服务层（与 `test_oj_domain_boundaries` 同一条边界）。"""

    def test_metadata_module_imports_nothing_from_models_or_services(self):
        module_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "domain" / "oj" / "problems" / "metadata.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)

        for mod in imported:
            for forbidden in ("app.models", "app.services", "sqlmodel", "sqlalchemy"):
                assert not (mod == forbidden or mod.startswith(forbidden + ".")), (
                    f"域模块 import 了 `{mod}`——域层不得依赖 ORM / 服务层"
                )

    def test_no_session_parameter_in_public_api(self):
        import inspect

        for fn in (normalize_difficulty, normalize_tags, valid_difficulty_values):
            assert "session" not in inspect.signature(fn).parameters

    def test_no_utf8_bom(self):
        """BOM 会让 ast.parse 报错（本轮 PR-06 踩过），新文件不得带。"""
        for name in ("metadata.py", "__init__.py"):
            path = (
                Path(__file__).resolve().parents[1]
                / "app" / "domain" / "oj" / "problems" / name
            )
            assert path.read_bytes()[:3] != b"\xef\xbb\xbf", f"{name} 带了 UTF-8 BOM"


# ---------------------------------------------------------------------------
# 迁移 ↔ 域层的字面量一致性
# ---------------------------------------------------------------------------

_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION = _BACKEND / "alembic" / "versions" / "20260911_1600_oj_problem_metadata.py"


def _migration_source() -> str:
    return _MIGRATION.read_text(encoding="utf-8-sig")


class TestMigrationContract:
    """迁移文件**刻意不 import 应用代码**（alembic 版本可能与应用版本错开），
    于是 `'medium'` 这个默认值在两边各写了一份字面量。本组是那份重复的守卫：
    只改一边时这里会红，而不是等到线上题库筛选出现一批「难度对不上」的题。
    """

    def test_migration_file_exists(self):
        assert _MIGRATION.exists(), f"PR-09 迁移缺失：{_MIGRATION.name}"

    def test_no_utf8_bom(self):
        assert _MIGRATION.read_bytes()[:3] != b"\xef\xbb\xbf", "迁移文件带了 UTF-8 BOM"

    def test_default_difficulty_literal_matches_domain(self):
        """迁移里的 `_DEFAULT_DIFFICULTY` 必须等于域层 `DEFAULT_DIFFICULTY`。"""
        tree = ast.parse(_migration_source())
        literal: str | None = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_DEFAULT_DIFFICULTY"
                for t in node.targets
            ):
                literal = ast.literal_eval(node.value)
        assert literal == DEFAULT_DIFFICULTY, (
            f"迁移默认难度 {literal!r} != 域层 {DEFAULT_DIFFICULTY!r}"
        )

    def test_revision_chain_points_at_pr01(self):
        """`down_revision` 必须接在 PR-01 迁移之后，否则会开出第二个 head。"""
        source = _migration_source()
        assert 'revision = "oj20260911v2"' in source
        assert 'down_revision = "oj20260911v1"' in source

    def test_uses_json_column_not_text_for_tags(self):
        """`tags` 必须是 JSON 列并与既有 `knowledge_node_ids` 同构。

        写成 `String` 会在 PG 上退化成「逗号拼接的字符串」，届时筛标签
        只能 `LIKE '%x%'`，既无索引又会把 `db` 误匹配 `dbms`。
        """
        source = _migration_source()
        assert 'sa.Column("tags", sa.JSON(), nullable=True)' in source


class TestModelColumns:
    """模型层的两列必须与迁移对齐（列名 / 可空性 / 索引）。"""

    def test_definition_has_difficulty_and_tags(self):
        from app.models.experiment_model import ExperimentDefinition

        columns = ExperimentDefinition.__table__.columns
        assert "difficulty" in columns
        assert "tags" in columns

    def test_difficulty_default_matches_domain(self):
        from app.models.experiment_model import ExperimentDefinition

        column = ExperimentDefinition.__table__.columns["difficulty"]
        assert column.nullable is False
        assert column.server_default is not None or column.default is not None
        default = getattr(column.default, "arg", None)
        assert default == DEFAULT_DIFFICULTY

    def test_difficulty_is_indexed(self):
        from app.models.experiment_model import ExperimentDefinition

        indexes = {
            index.name for index in ExperimentDefinition.__table__.indexes
        }
        assert "ix_experiment_definitions_difficulty" in indexes, (
            f"difficulty 未建索引，实际索引：{sorted(indexes)}"
        )
