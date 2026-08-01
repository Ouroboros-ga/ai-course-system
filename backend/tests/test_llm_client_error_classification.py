from app.common.llm_client import LLMError, _llm_http_error_reason
from app.platform.agents.contracts.llm import StructuredOutputError
from app.platform.tasks.handlers import _course_build_failure_message


def test_response_format_400_is_classified_without_retaining_body():
    body = '{"error":{"message":"response_format json_schema is unsupported"}}'

    reason = _llm_http_error_reason(status_code=400, body=body)
    error = LLMError("LLM API请求失败: 400", status_code=400, reason_code=reason)

    assert error.reason_code == "response_format_unsupported"
    assert body not in str(error)


def test_unrelated_400_is_not_treated_as_response_format_rejection():
    assert _llm_http_error_reason(status_code=400, body='{"error":"invalid model"}') == ""


def test_course_build_surfaces_an_actionable_message_for_unknown_llm_400():
    try:
        raise LLMError("LLM API请求失败: 400", status_code=400)
    except LLMError as cause:
        wrapped = StructuredOutputError("Shared LLM client call failed: LLMError: LLM API请求失败: 400")
        wrapped.__cause__ = cause

    message = _course_build_failure_message(wrapped)

    assert "HTTP 400" in message
    assert "模型名称" in message
