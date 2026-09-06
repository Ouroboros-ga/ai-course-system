"""M2 请求作用域：把代理层注入的用户身份与课程上下文传给工具。

安全设计（P2 计划 §6.1 M2-B2）：``search_course_materials`` 的 course_id 由
Backend 反代从请求 ``context`` 固定注入（ContextVar），**工具内不信任模型
传参**——模型无法通过构造参数越权检索其他课程。
"""
from __future__ import annotations

from contextvars import ContextVar, Token

_user_id_var: ContextVar[str | None] = ContextVar("nexus_user_id", default=None)
_course_id_var: ContextVar[int | None] = ContextVar("nexus_course_id", default=None)
# NX-G2：执行审批绑定的会话与票据。独立变量——set_scope(user, course) 签名
# 保持不变（既有工具/测试不感知审批），审批链路显式 set/reset。
_session_id_var: ContextVar[str | None] = ContextVar("nexus_session_id", default=None)
_approval_id_var: ContextVar[str | None] = ContextVar("nexus_approval_id", default=None)
# NX-A1：本次对话绑定的附件 id（Backend 验主+绑定后注入执行上下文）。
_attachments_var: ContextVar[tuple[str, ...]] = ContextVar("nexus_attachments", default=())


def set_scope(user_id: str | None, course_id: int | None) -> tuple[Token, Token]:
    return (_user_id_var.set(user_id), _course_id_var.set(course_id))


def reset_scope(tokens: tuple[Token, Token]) -> None:
    _user_id_var.reset(tokens[0])
    _course_id_var.reset(tokens[1])


def current_user_id() -> str | None:
    return _user_id_var.get()


def current_course_id() -> int | None:
    return _course_id_var.get()


def set_execution_scope(
    session_id: str | None, approval_id: str | None
) -> tuple[Token, Token]:
    """NX-G2：注入审批绑定的会话与票据（请求上下文，非模型可写参数）。"""
    return (_session_id_var.set(session_id), _approval_id_var.set(approval_id))


def reset_execution_scope(tokens: tuple[Token, Token]) -> None:
    _session_id_var.reset(tokens[0])
    _approval_id_var.reset(tokens[1])


def current_session_id() -> str | None:
    return _session_id_var.get()


def current_approval_id() -> str | None:
    return _approval_id_var.get()


def set_attachments(attachment_ids: list[str] | tuple[str, ...] | None) -> Token:
    """NX-A1：注入本次对话绑定的附件 id（已由 Backend 验主+绑定，去重保序）。"""
    clean: list[str] = []
    for raw in attachment_ids or []:
        aid = (raw or "").strip()[:16]
        if aid and aid not in clean:
            clean.append(aid)
    return _attachments_var.set(tuple(clean))


def reset_attachments(token: Token) -> None:
    _attachments_var.reset(token)


def current_attachments() -> tuple[str, ...]:
    return _attachments_var.get()
