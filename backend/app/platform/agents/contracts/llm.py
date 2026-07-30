"""StructuredLLMPort: low-level LLM abstraction shared across all agents.

This is the bottom layer of the two-layer LLM design (migration design
section 11). It unifies JSON schema enforcement, structured output,
one-shot repair retry, model configuration, token/cost tracking, timeout,
log redaction, and prompt versioning.

The upper layer (business LLM adapters) builds on top of this:
    - ``EduLLMPort`` (existing ``TeachingLLMPort``): detect_intent,
      resolve_concept, generate_teaching_response
    - ``PrepLLMPort`` (future): segment_evidence, plan_outline,
      write_script, generate_patch_operations
    - ``CodingLLMPort`` (future): classify_misconception,
      select_hint_strategy, generate_feedback

Design rules:
    - ``StructuredLLMPort`` does NOT know about teaching, prep, or coding.
      It only knows about messages, schemas, and structured output.
    - One repair retry: if the first response fails schema validation,
      the provider sends a repair prompt and retries once. A second
      failure raises ``StructuredOutputError``.
    - Sensitive data (API keys, full prompts) is redacted in logs and
      traces; see ``tools/safety.py``.
    - The existing ``TeachingLLMPort`` and Prep's ``llm_client`` are NOT
      replaced in Phase 1; they are wrapped by adapters in Phase 2a/3/4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMOptions:
    """Options for a single LLM completion call.

    - ``temperature``: sampling temperature (0.0-2.0).
    - ``max_tokens``: max output tokens.
    - ``timeout_seconds``: per-call timeout.
    - ``response_format``: ``{"type": "json_object"}`` for JSON mode.
    - ``prompt_version``: version tag for audit/metrics.
    """

    temperature: float = 0.2
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    response_format: Mapping[str, Any] | None = None
    prompt_version: str = ""


@dataclass(frozen=True)
class LLMTraceContext:
    """Trace context for a single LLM call.

    - ``run_id`` / ``trace_id``: correlation with the agent run.
    - ``agent_type``: which agent initiated the call.
    - ``node``: which workflow node initiated the call.
    - ``purpose``: human-readable purpose (e.g. ``"detect_intent"``).
    """

    run_id: str = ""
    trace_id: str = ""
    agent_type: str = ""
    node: str = ""
    purpose: str = ""


@dataclass(frozen=True)
class LLMResponse:
    """Structured LLM response with metadata.

    - ``content``: raw text content from the model.
    - ``parsed``: parsed pydantic model (when ``output_schema`` was provided).
    - ``model``: model identifier that produced the response.
    - ``latency_ms``: round-trip latency.
    - ``usage``: token usage dict (``prompt_tokens``, ``completion_tokens``).
    - ``repaired``: whether a repair retry was used.
    """

    content: str
    parsed: BaseModel | None = None
    model: str = ""
    latency_ms: float = 0.0
    usage: Mapping[str, Any] = field(default_factory=dict)
    repaired: bool = False


class StructuredOutputError(Exception):
    """The LLM response could not satisfy the output schema after one retry.

    This is a hard-gate error (``ErrorCode.INVALID_MODEL_OUTPUT``). The
    caller should surface it as a user-facing error, not retry silently.
    """


@runtime_checkable
class StructuredLLMPort(Protocol):
    """Low-level structured LLM abstraction.

    All three agents' business LLM adapters call this port. The port
    handles:
        - JSON schema enforcement (via ``response_format`` or prompt)
        - One repair retry on schema validation failure
        - Token/cost tracking
        - Timeout enforcement
        - Log redaction
        - Prompt version tagging

    The port does NOT handle:
        - Business logic (intent detection, outline planning, etc.)
        - Retrieval or evidence (that's the caller's job)
        - Conversation history (that's ConversationContextPort)
    """

    async def complete(
        self,
        *,
        messages: list[Mapping[str, str]],
        output_schema: type[BaseModel] | None = None,
        options: LLMOptions,
        trace_context: LLMTraceContext,
    ) -> LLMResponse:
        """Complete a chat exchange with optional structured output.

        When ``output_schema`` is provided, the response is validated
        against it. If validation fails, a repair prompt is sent and the
        response is retried once. A second failure raises
        ``StructuredOutputError``.

        When ``output_schema`` is None, ``LLMResponse.parsed`` is None
        and ``LLMResponse.content`` holds the raw text.
        """
        ...


__all__ = [
    "LLMOptions",
    "LLMTraceContext",
    "LLMResponse",
    "StructuredOutputError",
    "StructuredLLMPort",
]
