"""Stable error classes for the teaching-agent boundary."""


class TeachingAgentError(Exception):
    code = "TEACHING_AGENT_ERROR"


class RequestValidationError(TeachingAgentError):
    code = "INVALID_TEACHING_REQUEST"


class ScopeRejectedError(TeachingAgentError):
    code = "TEACHING_SCOPE_REJECTED"


class ServiceUnavailableError(TeachingAgentError):
    code = "TEACHING_SERVICE_UNAVAILABLE"


class LLMUnavailableError(ServiceUnavailableError):
    code = "TEACHING_LLM_UNAVAILABLE"
