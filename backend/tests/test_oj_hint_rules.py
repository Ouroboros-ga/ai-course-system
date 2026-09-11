"""契约：分层提示的域规则（PR-06b 归位）+ 域边界复查。

覆盖 `domain/oj/intelligence/hints.py`：
- full_solution 门禁是**教学安全不变式**，任何产生提示的路径都过同一道门；
- 审核决定值域收窄（approved / rejected），不收拼写变体；
- 策略版本常量的跨层一致性（模型枚举 ↔ 域层字面量）。

CRUD（建记录 / 列表 / 审核落库）留在 `CodingHintService`，本文件不测。
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

from app.domain.oj.intelligence import (
    CODING_HINT_POLICY_VERSION,
    FULL_SOLUTION_LEVEL,
    HINT_REVIEW_DECISIONS,
    assert_full_solution_allowed,
    normalize_review_decision,
)


class TestFullSolutionGate:
    def test_full_solution_requires_teacher_policy(self):
        with pytest.raises(ValueError, match="full_solution"):
            assert_full_solution_allowed("full_solution", full_solution_allowed=False)

    def test_full_solution_allowed_when_policy_permits(self):
        assert_full_solution_allowed("full_solution", full_solution_allowed=True)  # 不抛

    def test_other_levels_never_gated(self):
        """concept/approach/scaffold/partial 不需要教师策略 —— 分层提示的意义就在此。"""
        for level in ("concept", "approach", "scaffold", "partial"):
            assert_full_solution_allowed(level, full_solution_allowed=False)  # 不抛

    def test_accepts_enum_member(self):
        """域层不 import ORM，枚举经 `getattr(value, 'value')` 双接受。"""
        from app.models.experiment_model import CodingHintLevel

        assert_full_solution_allowed(
            CodingHintLevel.FULL_SOLUTION, full_solution_allowed=True
        )
        with pytest.raises(ValueError):
            assert_full_solution_allowed(
                CodingHintLevel.FULL_SOLUTION, full_solution_allowed=False
            )

    def test_unknown_level_not_gated_here(self):
        """层级合法性是 ORM 枚举的职责；本门只管 full_solution 这一道。"""
        assert_full_solution_allowed("mystery_level", full_solution_allowed=False)  # 不抛


class TestReviewDecision:
    @pytest.mark.parametrize("given,expected", [
        ("approved", "approved"),
        ("REJECTED", "rejected"),
        ("  approved ", "approved"),
    ])
    def test_valid_decisions(self, given, expected):
        assert normalize_review_decision(given) == expected

    @pytest.mark.parametrize("bad", ["ok", "pass", "", None, "approve"])
    def test_spelling_variants_rejected(self, bad):
        """审核态决定 hint 是否继续展示 —— 拼写变体会让前端分支失控。"""
        with pytest.raises(ValueError, match="审核决定"):
            normalize_review_decision(bad)

    def test_vocabulary_is_exactly_two(self):
        assert HINT_REVIEW_DECISIONS == {"approved", "rejected"}


class TestPolicyVersionContract:
    def test_version_literal_unchanged(self):
        """策略版本号是审计字段的一部分：变更必须是有意为之（递增），不是漂移。"""
        assert CODING_HINT_POLICY_VERSION == "coding-hint-v1.0"

    def test_level_literal_matches_model_enum(self):
        """域层字面量 ↔ `CodingHintLevel.FULL_SOLUTION` 取值一致（两域独立定义）。"""
        from app.models.experiment_model import CodingHintLevel

        assert FULL_SOLUTION_LEVEL == CodingHintLevel.FULL_SOLUTION.value

    def test_service_uses_domain_version_not_private_copy(self):
        """服务层的策略版本必须**来自域层**——防止出现两份各自漂移的版本号。"""
        service_src = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "experiment_service.py"
        ).read_text(encoding="utf-8-sig")
        assert 'CODING_HINT_POLICY_VERSION = "coding-hint' not in service_src, (
            "策略版本号在服务层又出现了字面量 —— 应从 domain/oj/intelligence 导入"
        )


class TestHintDomainPurity:
    def test_hints_module_imports_nothing_from_models_or_services(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "app" / "domain" / "oj" / "intelligence" / "hints.py"
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

    def test_no_session_parameter_in_public_api(self):
        import inspect

        for fn in (assert_full_solution_allowed, normalize_review_decision):
            assert "session" not in inspect.signature(fn).parameters

    def test_no_utf8_bom(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "app" / "domain" / "oj" / "intelligence" / "hints.py"
        )
        assert path.read_bytes()[:3] != b"\xef\xbb\xbf", "hints.py 带了 UTF-8 BOM"

    def test_domain_oj_stays_clean_of_business_imports(self):
        """随拆分增长，域边界门禁（test_oj_domain_boundaries）之外再扫一次三个服务模块
        拆分后的域目录：确保没有人在搬运时顺手把业务依赖带进域层。"""
        domain_dir = Path(__file__).resolve().parents[1] / "app" / "domain" / "oj"
        for py in domain_dir.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            src = py.read_text(encoding="utf-8-sig")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", None) or ""
                    names = [a.name for a in node.names]
                    bad = [n for n in names if n.split(".")[0] in ("app.models", "app.services")]
                    assert not mod.startswith(("app.models", "app.services")), (
                        f"{py.name} 引用了业务层 {mod}"
                    )
                    assert not bad, f"{py.name} 引用了业务层 {bad}"
                # builtins 白名单跳过
                _ = builtins
