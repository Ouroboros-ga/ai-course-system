"""Characterization：OJ intelligence 判定规则的行为基线。

本文件是 PR-06（`intelligence/` 归位）的**回归门禁**。

`_classify` / `_debug_steps` 的纯规则逻辑要从
`app/services/coding_eduagent_service.py` 搬进 `app/domain/oj/intelligence/`。
搬迁前先把**当前行为逐条钉住**——每个 outcome 分支、每条诊断文案、
每个 reason code 都断言到位。搬迁后本文件必须全绿且**一个字不改**。

为什么需要它：现有测试只覆盖 `wrong_answer → logic` 一条路径，
其余 7 个 outcome 分支、7 个 `_debug_steps` 分支、全部 reason code 均无直接断言。
没有这层基线，"搬家" 与 "顺手改文案" 无法区分。

`apiContracts.test.cjs` 是读源码 + 正则断言，搬家时**不会红**，
不能替代本文件（见 ADR-0001 决定 10）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest

from app.domain.oj.intelligence.rules import _LINE_RE as DOMAIN_LINE_RE
from app.services.coding_eduagent_service import (
    _classify,
    _debug_steps,
    build_rule_explanation,
    serialize_diagnosis,
)


class _Run:
    """ExperimentRun 的最小替身：只带 _classify 真正读的 4 个字段。"""

    def __init__(self, outcome=None, **fields):
        self.outcome = outcome
        self.error_code = fields.get("error_code")
        self.error_message = fields.get("error_message")
        self.compile_message = fields.get("compile_message")
        self.runtime_message = fields.get("runtime_message")


class _Artifact:
    def __init__(self, artifact_type="stderr", content=""):
        self.artifact_type = artifact_type
        self.content = content


class TestClassifyOutcomeBranches:
    """8 个 outcome 分支的判定结果。每个分支都断言三元组（class, summary, reasons）。"""

    def test_compilation_error_with_syntax_token(self):
        got = _classify(_Run("compilation_error", compile_message="SyntaxError: bad"), [])
        assert got == ("syntax", "编译阶段发现语法或缩进问题。", ["COMPILE_ERROR", "SYNTAX_LIKE"])

    def test_compilation_error_without_syntax_token(self):
        got = _classify(_Run("compilation_error", compile_message="undefined reference"), [])
        assert got == ("compile", "代码未能通过编译或解释器检查。", ["COMPILE_ERROR"])

    def test_runtime_error_index_like(self):
        got = _classify(_Run("runtime_error", runtime_message="IndexError: list index"), [])
        assert got == ("runtime", "运行时访问了不存在的索引或元素。", ["RUNTIME_ERROR", "INDEX_LIKE"])

    def test_runtime_error_division_by_zero(self):
        got = _classify(_Run("runtime_error", runtime_message="ZeroDivisionError"), [])
        assert got == ("runtime", "运行时发生除零错误。", ["RUNTIME_ERROR", "DIVISION_BY_ZERO"])

    def test_runtime_error_generic(self):
        got = _classify(_Run("runtime_error", runtime_message="assert failed"), [])
        assert got == ("runtime", "程序运行过程中抛出了错误。", ["RUNTIME_ERROR"])

    def test_wrong_answer(self):
        got = _classify(_Run("wrong_answer"), [])
        assert got == ("logic", "程序可以运行，但输出与测试预期不一致。", ["WRONG_ANSWER", "CHECK_LOGIC"])

    def test_time_limit_exceeded(self):
        got = _classify(_Run("time_limit_exceeded"), [])
        assert got == ("complexity", "程序超过了本题的时间限制。", ["TIME_LIMIT", "CHECK_COMPLEXITY"])

    def test_memory_limit_exceeded(self):
        got = _classify(_Run("memory_limit_exceeded"), [])
        assert got == ("complexity", "程序超过了本题的内存限制。", ["MEMORY_LIMIT", "CHECK_SPACE"])

    def test_accepted(self):
        got = _classify(_Run("accepted"), [])
        assert got == ("none", "本次运行通过了可见的评分检查。", ["ACCEPTED"])

    def test_sandbox_unavailable(self):
        got = _classify(_Run("sandbox_unavailable"), [])
        assert got == (
            "environment",
            "代码沙箱暂不可用，本次没有形成有效执行证据。",
            ["SANDBOX_UNAVAILABLE"],
        )

    def test_unknown_outcome_falls_back(self):
        got = _classify(_Run("totally_made_up"), [])
        assert got == (
            "unknown",
            "当前运行结果不足以形成可靠的代码诊断。",
            ["INSUFFICIENT_EXECUTION_EVIDENCE"],
        )

    def test_none_outcome_falls_back(self):
        got = _classify(_Run(None), [])
        assert got[0] == "unknown"
        assert got[2] == ["INSUFFICIENT_EXECUTION_EVIDENCE"]


class TestClassifyOutcomeNormalization:
    """outcome 是枚举时取 .value；None 时按 'unknown' 处理。"""

    def test_enum_outcome_uses_value(self):
        class _Outcome:
            value = "wrong_answer"

        got = _classify(_Run(_Outcome()), [])
        assert got[0] == "logic"

    def test_empty_string_outcome_falls_back_to_unknown(self):
        # `_outcome_value` 里 `value or "unknown"` —— 空串是 falsy
        got = _classify(_Run(""), [])
        assert got[0] == "unknown"


class TestClassifyEvidenceText:
    """判定文本来自 run 的 4 个 message 字段 + stderr/compile 两类 artifact 的拼接。"""

    def test_syntax_token_found_in_artifact_content(self):
        got = _classify(_Run("compilation_error"), [_Artifact("stderr", "SyntaxError here")])
        assert got[0] == "syntax"

    def test_chinese_syntax_token_also_matches(self):
        got = _classify(_Run("compilation_error"), [_Artifact("compile", "语法错误")])
        assert got[0] == "syntax"

    def test_artifact_with_other_type_is_ignored(self):
        # 只有 stderr / compile 会被读入判定文本
        got = _classify(_Run("compilation_error"), [_Artifact("stdout", "SyntaxError")])
        assert got[0] == "compile"

    def test_error_message_field_contributes(self):
        got = _classify(_Run("runtime_error", error_message="IndexError"), [])
        assert got[0] == "runtime"
        assert "INDEX_LIKE" in got[2]

    def test_matching_is_case_insensitive(self):
        got = _classify(_Run("compilation_error", compile_message="INDENT ERROR"), [])
        assert got[0] == "syntax"


class TestDebugSteps:
    """`_debug_steps` 7 个具名分支 + 1 个兜底，每条文案逐字钉住。"""

    @pytest.mark.parametrize(
        "error_class,first_step",
        [
            ("syntax", "先查看编译器指出的行附近代码"),
            ("compile", "确认语言版本和入口函数符合题目要求"),
            ("runtime", "用最小输入复现错误"),
            ("logic", "找一个最小反例"),
            ("complexity", "估算主要循环或递归的时间复杂度"),
            ("environment", "稍后重试沙箱执行"),
            ("none", "可以查看隐藏边界条件并尝试解释每一步"),
        ],
    )
    def test_named_branches(self, error_class, first_step):
        steps = _debug_steps(error_class)
        assert isinstance(steps, list)
        assert steps[0] == first_step

    def test_unknown_class_falls_back(self):
        steps = _debug_steps("no_such_class")
        assert steps == [
            "等待一次有效执行结果后再诊断",
            "不要根据猜测修改多个地方",
            "保留最小复现样例",
        ]

    def test_none_branch_has_only_two_steps(self):
        """`none`（accepted）是唯一只有 2 条的分支 —— 不要"顺手补齐成 3 条"。

        通过时不需要修错指引，两条就够。实测确认（2026-09-11）。
        这条断言的存在就是为了拦住后来者对称化这个不对称。
        """
        assert _debug_steps("none") == [
            "可以查看隐藏边界条件并尝试解释每一步",
            "如需提升难度，请请求下一道课程练习",
        ]

    def test_step_counts_per_branch(self):
        """逐分支钉住条数：7 个分支 3 条，`none` 2 条，兜底 3 条。"""
        expected = {
            "syntax": 3, "compile": 3, "runtime": 3, "logic": 3,
            "complexity": 3, "environment": 3, "none": 2, "?": 3,
        }
        for name, count in expected.items():
            assert len(_debug_steps(name)) == count, f"{name} 的条数变了"


class TestLineRegex:
    """行号抽取：`_LINE_RE` 在域层，`line_from_text` 是它的公开包装。

    PR-06 后正则从 service 搬进 `domain/oj/intelligence/rules.py`，
    本组同时守住「正则行为不变」与「包装函数返回 int 而非 str」。
    """

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("line 42", "42"),
            ("Line: 7", "7"),
            ("line=13", "13"),
            ("行 99", "99"),
            ("行:5", "5"),
            ("no number here", None),
        ],
    )
    def test_extracts_or_returns_none(self, text, expected):
        m = DOMAIN_LINE_RE.search(text)
        assert (m.group(1) if m else None) == expected

    def test_is_case_insensitive(self):
        assert re.search(DOMAIN_LINE_RE.pattern, "LINE 3", DOMAIN_LINE_RE.flags) is not None

    def test_line_from_text_returns_int(self):
        from app.domain.oj.intelligence.rules import line_from_text

        assert line_from_text("line 42") == 42
        assert isinstance(line_from_text("line 42"), int)

    def test_line_from_text_scans_first_match_across_segments(self):
        """按传入顺序扫描，取**第一个**命中——顺序变了行号就变了。"""
        from app.domain.oj.intelligence.rules import line_from_text

        assert line_from_text("", "line 7") == 7
        assert line_from_text("line 7", "line 99") == 7

    def test_line_from_text_handles_none_segments(self):
        from app.domain.oj.intelligence.rules import line_from_text

        assert line_from_text(None, "", "line 5") == 5

    def test_line_from_text_returns_none_when_absent(self):
        from app.domain.oj.intelligence.rules import line_from_text

        assert line_from_text("no line here", "") is None


class TestExplanationContract:
    """`build_rule_explanation` 的输出形状 —— 公开端点直接透传，键名不能改。"""

    def test_exact_key_set_and_values(self):
        class _Record:
            run_id = "run-1"
            outcome = "wrong_answer"
            error_class = "logic"
            summary = "输出不一致"
            debug_steps: ClassVar[list] = ["a", "b"]
            reason_codes: ClassVar[list] = ["WRONG_ANSWER"]

        got = build_rule_explanation(_Record())
        assert set(got) == {
            "run_id", "outcome", "error_class", "summary",
            "next_steps", "reason_codes", "source",
        }
        assert got["source"] == "coding-rules"
        assert got["next_steps"] == ["a", "b"]
        assert got["reason_codes"] == ["WRONG_ANSWER"]

    def test_none_lists_become_empty_lists(self):
        class _Record:
            run_id = "r"
            outcome = "accepted"
            error_class = "none"
            summary = "s"
            debug_steps: ClassVar = None
            reason_codes: ClassVar = None

        got = build_rule_explanation(_Record())
        assert got["next_steps"] == []
        assert got["reason_codes"] == []

    def test_returns_a_copy_not_the_same_list(self):
        source = ["x"]

        class _Record:
            run_id = "r"
            outcome = "accepted"
            error_class = "none"
            summary = "s"
            debug_steps: ClassVar = source
            reason_codes: ClassVar = source

        got = build_rule_explanation(_Record())
        got["next_steps"].append("mutated")
        assert source == ["x"], "必须复制，不能把 record 的 list 直接暴露给调用方"


class TestSerializeDiagnosisContract:
    """`serialize_diagnosis` 的 18 个键，前端契约依赖它。"""

    def test_exact_key_set(self):
        class _Record:
            diagnosis_id = "cd_1"
            run_id = "r"
            course_id = 1
            student_id = 2
            status = "ready"
            outcome = "accepted"
            error_class = "none"
            line = None
            column = None
            summary = "s"
            debug_steps: ClassVar[list] = []
            hints: ClassVar[list] = []
            confidence = 0.95
            evidence_refs: ClassVar[list] = []
            reason_codes: ClassVar[list] = []
            policy_version = "coding-diagnosis/rule-v1"
            generated_by = "coding-rules"
            created_at = None

        got = serialize_diagnosis(_Record())
        assert set(got) == {
            "diagnosis_id", "run_id", "course_id", "student_id", "status",
            "outcome", "error_class", "line", "column", "summary",
            "debug_steps", "hints", "confidence", "evidence_refs",
            "reason_codes", "policy_version", "generated_by", "created_at",
        }

    def test_created_at_is_iso_or_none(self):
        class _Record:
            diagnosis_id = "cd_1"
            run_id = "r"
            course_id = 1
            student_id = 2
            status = "ready"
            outcome = "accepted"
            error_class = "none"
            line = None
            column = None
            summary = "s"
            debug_steps: ClassVar[list] = []
            hints: ClassVar[list] = []
            confidence = 0.0
            evidence_refs: ClassVar[list] = []
            reason_codes: ClassVar[list] = []
            policy_version = "v"
            generated_by = "g"
            created_at = None

        assert serialize_diagnosis(_Record())["created_at"] is None


class TestDiagnosisRulesArePure:
    """搬迁后的硬约束：判定规则本体在 domain/，service 只留委托壳。

    `domain/` 层现有 5 个模块全部不 import `app.models` / `app.services`（实测零命中）。
    这条惯例保证域层可脱离数据库独立测试与复用。

    PR-06 后 `_classify` / `_debug_steps` 是**委托壳**（函数体内只调用域函数），
    真正的规则在 `domain/oj/intelligence/rules.py` —— 本组同时守两者。
    """

    def test_domain_rules_import_nothing_from_models_or_services(self):
        """域规则模块本身必须零 ORM / 零服务依赖。"""
        import ast

        module_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "domain" / "oj" / "intelligence" / "rules.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))

        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)

        forbidden_modules = ("app.models", "app.services", "sqlmodel", "sqlalchemy")
        for mod in imported:
            for forbidden in forbidden_modules:
                assert not (mod == forbidden or mod.startswith(forbidden + ".")), (
                    f"域规则模块 import 了 `{mod}`——域层不得依赖 ORM / 服务层"
                )

    def test_service_shells_do_not_own_the_rules(self):
        """service 的委托壳里不该再出现判定分支或文案字面量。

        若有人把规则抄回 service，本断言会红——拦的是「以后又错」。
        """
        module_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "coding_eduagent_service.py"
        )
        source = module_path.read_text(encoding="utf-8")
        for literal in ("编译阶段发现语法或缩进问题", "运行时发生除零错误", "找一个最小反例"):
            assert literal not in source, (
                f"`{literal}` 又出现在 service 里了——规则应只在 domain/oj/intelligence/"
            )

    def test_classify_and_debug_steps_are_thin_delegates(self):
        """两个壳的函数体必须**只有一条 return**（无分支、无字面量）。

        用 AST 判定而非数行数——行数会被 docstring 长度干扰。
        """
        import ast

        module_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "coding_eduagent_service.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        found = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

        for name in ("_classify", "_debug_steps"):
            assert name in found, f"{name} 壳不见了"
            body = [n for n in found[name].body if not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)]
            assert len(body) == 1, f"{name} 的函数体有 {len(body)} 条语句，应只有 1 条 return"
            assert isinstance(body[0], ast.Return), f"{name} 的唯一语句不是 return"
            # 不得含任何比较/分支——那意味着判定逻辑被抄回来了
            for node in ast.walk(found[name]):
                assert not isinstance(node, (ast.If, ast.Compare, ast.For, ast.While)), (
                    f"{name} 里出现了分支或比较——判定逻辑不该在 service 里"
                )

    def test_diagnosis_rules_do_not_take_a_session(self):
        import inspect

        for fn in (_classify, _debug_steps):
            params = inspect.signature(fn).parameters
            assert "session" not in params, f"{fn.__name__} 不该接收 session"

    def test_policy_version_constants_agree(self):
        """模型层与域层的 policy version **必须同值**。

        两处独立定义、值目前相同（`coding-diagnosis/rule-v1`）。
        若有人只改一处，历史诊断记录的版本口径就会分裂——本断言拦住它。
        """
        from app.domain.oj.intelligence.rules import DIAGNOSIS_POLICY_VERSION
        from app.models.coding_diagnosis_model import CODING_DIAGNOSIS_POLICY_VERSION

        assert DIAGNOSIS_POLICY_VERSION == CODING_DIAGNOSIS_POLICY_VERSION


class TestDomainRuleReuse:
    """域规则可直接使用，无需 session —— 这是搬迁的收益，断言它成立。"""

    def test_classify_runs_without_any_session(self):
        from app.domain.oj.intelligence import DiagnosisInput, classify_run

        got = classify_run(DiagnosisInput(outcome="wrong_answer"))
        assert got[0] == "logic"

    def test_hints_never_include_full_solution(self):
        """分层提示的硬约束：`full_solution` 恒为 False，落在域层而非调用方自觉。"""
        from app.domain.oj.intelligence import hints_for

        for error_class in ("syntax", "compile", "runtime", "logic", "complexity", "environment", "none", "?"):
            for hint in hints_for(error_class):
                assert hint["full_solution"] is False
                assert hint["level"] == "concept"

    def test_hints_are_at_most_two_and_derived_from_steps(self):
        from app.domain.oj.intelligence import debug_steps_for, hints_for

        steps = debug_steps_for("logic")
        hints = hints_for("logic")
        assert len(hints) == min(2, len(steps))
        assert [h["text"] for h in hints] == steps[:2]

    def test_none_class_yields_two_hints_not_three(self):
        from app.domain.oj.intelligence import hints_for

        assert len(hints_for("none")) == 2

    def test_confidence_high_only_for_classifiable_terminal_outcomes(self):
        from app.domain.oj.intelligence import confidence_for

        for outcome in (
            "accepted", "compilation_error", "runtime_error",
            "wrong_answer", "time_limit_exceeded", "memory_limit_exceeded",
        ):
            assert confidence_for(outcome) == 0.95, outcome
        for outcome in ("sandbox_unavailable", "pending", "unknown", "", None):
            assert confidence_for(outcome) == 0.35, outcome
