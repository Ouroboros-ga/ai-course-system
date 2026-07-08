from enum import Enum


class AdapterErrorCode(str, Enum):
    TIMEOUT = "timeout"
    SERVICE_UNAVAILABLE = "service_unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    BUSINESS_FAILURE = "business_failure"
    UNKNOWN_ERROR = "unknown_error"


class AdapterError(RuntimeError):
    def __init__(self, error_code: AdapterErrorCode, message: str):
        self.error_code = error_code
        super().__init__(message)
