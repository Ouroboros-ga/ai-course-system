"""M2 请求作用域：把代理层注入的用户身份与课程上下文传给工具。

安全设计（P2 计划 §6.1 M2-B2）：``search_course_materials`` 的 course_id 由
Backend 反代从请求 ``context`` 固定注入（ContextVar），**工具内不信任模型
传参**——模型无法通过构造参数越权检索其他课程。
"""
from __future__ import annotations

from contextvars import ContextVar, Token

_user_id_var: ContextVar[str | None] = ContextVar("nexus_user_id", default=None)
_course_id_var: ContextVar[int | None] = ContextVar("nexus_course_id", default=None)


def set_scope(user_id: str | None, course_id: int | None) -> tuple[Token, Token]:
    return (_user_id_var.set(user_id), _course_id_var.set(course_id))


def reset_scope(tokens: tuple[Token, Token]) -> None:
    _user_id_var.reset(tokens[0])
    _course_id_var.reset(tokens[1])


def current_user_id() -> str | None:
    return _user_id_var.get()


def current_course_id() -> int | None:
    return _course_id_var.get()
