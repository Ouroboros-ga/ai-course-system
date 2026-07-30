"""Output safety helpers: validation and desensitization.

These helpers are used by ``ToolInvoker`` and by agent nodes before
returning results to the caller or persisting to audit.

Design rules:
    - ``redact_sensitive_keys`` removes API keys, tokens, and credentials
      from any dict before it enters logs or audit records.
    - ``truncate_for_audit`` limits string length to prevent audit bloat
      from large LLM traces or code submissions.
    - ``validate_output_size`` guards against oversized payloads.
    - These helpers are pure functions; they never raise.

Domain-specific safety rules (e.g. Coding's hidden-test stripping) do NOT
belong here. They live in the agent's own ``validation.py`` so the shared
layer does not reverse-depend on a specific agent's domain.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

# Keys whose values must never appear in logs or audit records.
_SENSITIVE_KEY_PATTERNS = re.compile(
    r"(api[_-]?key|secret|token|password|credential|auth[_-]?header)",
    re.IGNORECASE,
)

# Maximum string length for audit-truncated fields.
_AUDIT_MAX_STRING = 2000

# Maximum payload size (bytes) for audit records.
_AUDIT_MAX_PAYLOAD_BYTES = 64 * 1024


def redact_sensitive_keys(data: Any) -> Any:
    """Recursively redact values whose keys look sensitive.

    Returns a new structure; the input is not mutated. Values under
    sensitive keys are replaced with ``"[REDACTED]"``.
    """
    if isinstance(data, Mapping):
        return {
            key: ("[REDACTED]" if _SENSITIVE_KEY_PATTERNS.search(str(key)) else redact_sensitive_keys(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_sensitive_keys(item) for item in data]
    return data


def truncate_for_audit(value: Any, max_length: int = _AUDIT_MAX_STRING) -> Any:
    """Truncate long strings for audit records.

    Non-string values are returned unchanged. Strings longer than
    ``max_length`` are truncated with a ``"…[truncated]"`` suffix.
    """
    if isinstance(value, str) and len(value) > max_length:
        return value[:max_length] + "…[truncated]"
    return value


def validate_output_size(payload: Any, *, max_bytes: int = _AUDIT_MAX_PAYLOAD_BYTES) -> bool:
    """Check that a payload is within the audit size limit.

    Returns True if the payload's JSON serialization is under ``max_bytes``.
    Use this before writing large results (e.g. full LLM traces, code
    submissions) to audit storage.
    """
    import json
    try:
        serialized = json.dumps(payload, default=str, ensure_ascii=False)
        return len(serialized.encode("utf-8")) <= max_bytes
    except (TypeError, ValueError):
        return False


def sanitize_for_audit(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Full audit sanitization: redact + truncate in one pass.

    Use this before writing any agent trace or tool invocation to the
    audit store.
    """
    redacted = redact_sensitive_keys(dict(payload))
    if isinstance(redacted, dict):
        return {
            key: truncate_for_audit(value) if isinstance(value, str) else value
            for key, value in redacted.items()
        }
    return redacted  # type: ignore[return-value]


__all__ = [
    "redact_sensitive_keys",
    "truncate_for_audit",
    "validate_output_size",
    "sanitize_for_audit",
]
