"""Safe, user-facing error messages shared by agent workflows.

Provider exceptions keep their detailed metadata for logs and audit records,
but the teacher-facing API must not expose raw gateway or Pydantic messages.
"""

from __future__ import annotations

from typing import Any


_PREP_STAGE_LABELS = {
    "segment_evidence": "材料证据整理",
    "plan_outline": "课程结构规划",
    "write_script": "讲授脚本生成",
    "write_scripts_batch": "批量讲授脚本生成",
    "verify_script": "讲授脚本核验",
    "plan_incremental": "课程节点优化",
    "execute_incremental_plan": "课程节点优化",
}


def iter_exception_chain(error: BaseException):
    """Yield an exception and its causes without looping forever."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def safe_prep_error_message(error: BaseException, *, default: str = "备课智能体执行失败，请稍后重试") -> str:
    """Translate internal Prep/LLM failures into an actionable safe message."""
    for current in iter_exception_chain(error):
        reason_code = getattr(current, "reason_code", "")
        if reason_code == "MODEL_OUTPUT_TRUNCATED":
            return "模型输出达到长度上限，系统未写入课程草稿；请缩小整理范围后重试。"
        if reason_code == "response_format_unsupported":
            return "当前模型网关不支持结构化输出，系统已尝试兼容模式但仍未完成；请检查模型网关配置后重试。"
        if reason_code == "structured_output_invalid":
            stage = getattr(current, "stage", "") or ""
            stage_label = _PREP_STAGE_LABELS.get(stage, stage or "当前备课步骤")
            attempts = int(getattr(current, "attempts", 0) or 0)
            repair_count = max(0, attempts - 1)
            retry_text = f"系统已自动重试 {repair_count} 次" if repair_count else "系统已进行自动修复"
            return (
                f"模型返回内容不符合预期格式，{retry_text}但仍未完成；"
                f"失败阶段：{stage_label}。原课程内容未改变，请稍后重试。"
            )

    # ValueError and the service's planning errors are already business-level
    # messages in the current implementation. Hide only unmistakable raw
    # provider/schema text that may come through legacy compatibility paths.
    message = str(error).strip()
    lowered = message.lower()
    if message and not any(marker in lowered for marker in (
        "validationerror",
        "llm response did not match schema",
        "pydantic",
        "jsondecodeerror",
    )):
        return message[:500]
    return default


def prep_error_details(
    error: BaseException,
    *,
    code: str,
    node: str,
) -> dict[str, Any]:
    """Build a fail-closed workflow error while retaining safe diagnostics."""
    details: dict[str, Any] = {
        "code": code,
        "message": safe_prep_error_message(error),
        "node": node,
        "error_type": type(error).__name__,
    }
    for current in iter_exception_chain(error):
        reason_code = getattr(current, "reason_code", "")
        if reason_code:
            details["reason_code"] = reason_code
            break
    for current in iter_exception_chain(error):
        finish_reason = getattr(current, "finish_reason", "")
        if finish_reason:
            details["finish_reason"] = str(finish_reason)[:64]
            break
    for current in iter_exception_chain(error):
        if getattr(current, "truncated", False):
            details["truncated"] = True
            break
    for current in iter_exception_chain(error):
        stage = getattr(current, "stage", "")
        if stage:
            details["stage"] = stage
            break
    for current in iter_exception_chain(error):
        attempts = getattr(current, "attempts", 0)
        if attempts:
            details["attempts"] = attempts
            schema_name = getattr(current, "schema_name", "")
            if schema_name:
                details["schema_name"] = schema_name
            validation_errors = getattr(current, "validation_errors", None)
            if validation_errors:
                details["validation_errors"] = list(validation_errors)
            break
    return details


__all__ = ["iter_exception_chain", "safe_prep_error_message", "prep_error_details"]
