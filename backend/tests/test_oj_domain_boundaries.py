"""契约：`domain/oj/**` 的依赖方向守卫。

**这条边界的含义**：域层定义「规则是什么」，服务层决定「何时读写数据库」。
域层若 import `app.models` / `app.services` / ORM 库，就会：

1. 无法脱离数据库单独测试（起一个 session 才能验一条规则）；
2. 形成 `domain → services → domain` 的循环依赖风险；
3. 与 `domain/` 下既有 5 个模块
   （`learning` / `safety` / `student_memory` / `knowledge_bundle` / `education_graph`）
   的惯例不一致 —— 实测这 5 个模块对本约束**零违反**。

**为什么需要它**：`domain/oj/` 是新建目录，正在快速长大（PR-01/02/05/06 已落地，
PR-07/11/14/15 还要往里加 Activity / Scoreboard / Analytics）。
没有这条门禁，「顺手在域里查一下库」是最容易被接受的坏改动。

**豁免**：`domain/oj/judging/providers/` 是本域**唯一**允许持有传输细节的目录
（ADR-0001 决定 3：Judge0 HTTP 出口收拢于此）。它不 import `app.models` /
`app.services`，但允许 import `httpx` 等。因此：
- `app.models` / `app.services` 的禁令对**整个** `domain/oj/**` 生效（含 providers）；
- ORM / HTTP 库的禁令只对 providers **之外**的部分生效。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_DOMAIN_OJ = Path(__file__).resolve().parents[1] / "app" / "domain" / "oj"

#: 任何情况下都不允许 import 的业务层模块（整域适用，含 providers/）
_FORBIDDEN_EVERYWHERE = ("app.models", "app.services")

#: ORM / 传输库——providers/ 之外禁止
_FORBIDDEN_OUTSIDE_PROVIDERS = ("sqlmodel", "sqlalchemy", "httpx", "requests")

#: providers/ 允许携带传输细节（ADR-0001 决定 3）
_PROVIDERS_MARKER = "providers"


def _iter_domain_modules() -> list[Path]:
    return sorted(p for p in _DOMAIN_OJ.rglob("*.py") if "__pycache__" not in p.parts)


def _is_under_providers(path: Path) -> bool:
    rel = path.relative_to(_DOMAIN_OJ)
    return _PROVIDERS_MARKER in rel.parts


def _read_source(path: Path) -> str:
    """按 `utf-8-sig` 读取——容忍 BOM。

    本仓部分 `.py` 带 UTF-8 BOM（实测 `domain/oj/` 下 5 个）。Python 解释器容忍 BOM，
    但 `ast.parse` **不容忍**（`SyntaxError: invalid non-printable character U+FEFF`）。
    测试读文件一律走这里，避免因 BOM 假红。
    """
    return path.read_text(encoding="utf-8-sig")


def _imported_modules(path: Path) -> list[tuple[str, int]]:
    """返回 `(module, lineno)` —— 行号便于报错时定位。"""
    tree = ast.parse(_read_source(path))
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append((node.module, node.lineno))
        elif isinstance(node, ast.Import):
            out.extend((alias.name, node.lineno) for alias in node.names)
    return out


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


@pytest.fixture(scope="module")
def domain_modules() -> list[Path]:
    modules = _iter_domain_modules()
    assert modules, f"没有扫到任何模块：{_DOMAIN_OJ}"
    return modules


class TestDomainOjDependencyDirection:
    def test_no_models_or_services_imports_anywhere(self, domain_modules):
        """整域（含 providers/）不得 import `app.models` / `app.services`。"""
        violations: list[str] = []
        for path in domain_modules:
            for module, lineno in _imported_modules(path):
                for forbidden in _FORBIDDEN_EVERYWHERE:
                    if _matches(module, forbidden):
                        rel = path.relative_to(_DOMAIN_OJ.parents[2])
                        violations.append(f"{rel}:{lineno} imports {module}")
        assert not violations, (
            "domain/oj/ 出现了业务层依赖——域层不得依赖 models / services：\n  "
            + "\n  ".join(violations)
        )

    def test_orm_and_transport_only_inside_providers(self, domain_modules):
        """ORM / HTTP 库只允许出现在 `providers/` 内。"""
        violations: list[str] = []
        for path in domain_modules:
            if _is_under_providers(path):
                continue
            for module, lineno in _imported_modules(path):
                for forbidden in _FORBIDDEN_OUTSIDE_PROVIDERS:
                    if _matches(module, forbidden):
                        rel = path.relative_to(_DOMAIN_OJ.parents[2])
                        violations.append(f"{rel}:{lineno} imports {module}")
        assert not violations, (
            "providers/ 之外出现了 ORM / 传输库依赖：\n  " + "\n  ".join(violations)
        )

    def test_the_guard_actually_scans_something(self, domain_modules):
        """防空跑：门禁必须真的扫到了文件与 import。

        若路径写错导致 `domain_modules` 为空或解析不到 import，
        上面两条会「静静地全绿」——这条断言拦住那种假绿。
        """
        assert len(domain_modules) >= 5, f"只扫到 {len(domain_modules)} 个模块，路径可能错了"
        total_imports = sum(len(_imported_modules(p)) for p in domain_modules)
        assert total_imports > 0, "一个 import 都没解析出来，AST 解析逻辑可能坏了"

    def test_providers_directory_still_exists(self):
        """`providers/` 是 Judge0 唯一出口，别被顺手删掉。"""
        providers = _DOMAIN_OJ / "judging" / "providers"
        assert providers.is_dir(), "judging/providers/ 消失了——Judge0 出口收拢的前提被破坏"
        assert (providers / "judge0.py").is_file(), "providers/judge0.py 不见了"


class TestDomainOjLayout:
    """目录骨架的存在性守卫——后续 PR 会往里加子域，别让它们落在别处。"""

    @pytest.mark.parametrize(
        "subpackage",
        ["judging", "submissions", "intelligence"],
    )
    def test_expected_subpackages_exist(self, subpackage):
        path = _DOMAIN_OJ / subpackage
        assert path.is_dir(), f"domain/oj/{subpackage}/ 不存在"
        assert (path / "__init__.py").is_file(), f"domain/oj/{subpackage}/ 缺 __init__.py"

    def test_no_third_directory_convention_introduced(self):
        """不新增 `backend/app/modules/`（ADR-0001 决定 2）。

        仓库已有两套约定：分层与 `platform/agents/<agent>/`。引入第三套
        会让「逻辑该放哪」失去唯一答案。
        """
        backend_app = _DOMAIN_OJ.parents[2]
        assert not (backend_app / "modules").exists(), (
            "出现了 backend/app/modules/ —— 这是 ADR-0001 决定 2 明确放弃的第三套目录约定"
        )

    def test_domain_package_has_docstring(self):
        """域入口要有说明，避免下一个人不知道该往这里放什么。"""
        init = _DOMAIN_OJ / "__init__.py"
        tree = ast.parse(_read_source(init))
        assert ast.get_docstring(tree), "domain/oj/__init__.py 缺模块 docstring"

    def test_no_utf8_bom_in_domain_modules(self, domain_modules):
        """`domain/oj/**` 下不得有 UTF-8 BOM。

        BOM 本身被 Python 解释器容忍，但会让 `ast.parse` 直接抛
        `SyntaxError: invalid non-printable character U+FEFF` ——
        任何依赖 AST 的工具（本文件、静态分析、未来可能的代码生成）都会踩。
        它是**工具链地雷**，不是风格问题。
        """
        offenders = [
            str(p.relative_to(_DOMAIN_OJ.parents[2]))
            for p in domain_modules
            if p.read_bytes()[:3] == b"\xef\xbb\xbf"
        ]
        assert not offenders, (
            "以下模块带 UTF-8 BOM，会让 ast.parse 报错，请去掉：\n  " + "\n  ".join(offenders)
        )
