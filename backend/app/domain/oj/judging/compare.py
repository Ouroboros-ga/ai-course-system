"""输出比对：Judge0 只执行，比对归本域。

背景
----
Judge0 的 ``expected_output`` 是严格（逐字节）比对，无 token/浮点容错
（上游 #224 "Flexible expected output comparison" 至今 open，原生不支持）。
直接透传它意味着：末尾换行、多余空格、``0.333333`` vs ``0.3333333``
都会判 WA —— 学生"明明做对"却不过，且隐藏用例只返回 passed/reason，
死都不知道差在哪。

本模块实施 Hydro/QDUOJ/DMOJ 的默认档：

1. 空白归一：按任意空白切分逐 token 比，行尾空格/多余换行/CRLF 不再致死；
2. 整数精确：双方都是整数形 token 时按大整数精确相等（防 float 精度吞大数）；
3. 浮点容差：其余可解析为浮点的 token 按 ``rel_tol=1e-6 / abs_tol=1e-6``；
4. 其余字符串精确相等。

不在本模块做的（诚实边界）：多解题（任意合法解/构造题）仍判不了，
那需要 checker 程序（Special Judge），见审计表 2026-09-13 条目。
空期望字符串 = 教师未表达输出断言 = 只验执行是否跑通（与 Judge0
不传 expected 时的历史语义一致），由调用方经 ``is_expected_output_asserted``
显式表达，不在本函数里 silently 通过。

依赖：仅标准库。域边界门禁（``test_oj_domain_boundaries``）要求
``domain/oj`` 不 import ``app.models`` / ``app.services``，本模块零应用依赖。
"""
from __future__ import annotations

import math
import re

#: 浮点 token 的相对/绝对容差（教学题常见"保留 6 位小数"：末位差 < 1e-6 可过）。
REL_TOL = 1e-6
ABS_TOL = 1e-6

_INT_RE = re.compile(r"^[+-]?\d+$")


def is_expected_output_asserted(expected: str | None) -> bool:
    """教师是否表达了输出断言。空/全空白 = 只验执行。"""
    return bool((expected or "").strip())


def tokenize(text: str | None) -> list[str]:
    """按任意空白切分。``None`` 视为空输出。"""
    if not text:
        return []
    return str(text).split()


def _tokens_equal(want: str, got: str) -> bool:
    """单个 token 相等：整数精确 → 浮点容差 → 字符串精确，依次降级。"""
    if want == got:
        return True
    if _INT_RE.match(want) and _INT_RE.match(got):
        # 大整数不能过 float（精度吞尾数），Python int 任意精度直接比。
        try:
            return int(want) == int(got)
        except ValueError:
            return False
    try:
        want_f, got_f = float(want), float(got)
    except ValueError:
        return False
    if not (math.isfinite(want_f) and math.isfinite(got_f)):
        # inf/nan：字符串已不等，按不等处理（nan != nan 恒成立，符合直觉）。
        return False
    return math.isclose(want_f, got_f, rel_tol=REL_TOL, abs_tol=ABS_TOL)


def compare_outputs(expected: str | None, actual: str | None) -> bool:
    """程序输出是否通过。token 数量必须一致（多/少输出都是错）。

    纯函数：空期望 vs 空输出 → True；空期望 vs 有输出 → False。
    「空期望只验执行」的产品 shortcut 不在这里，由调用方经
    ``is_expected_output_asserted`` 显式分支（见模块 docstring）。
    """
    want_tokens = tokenize(expected)
    got_tokens = tokenize(actual)
    if len(want_tokens) != len(got_tokens):
        return False
    return all(_tokens_equal(w, g) for w, g in zip(want_tokens, got_tokens))
