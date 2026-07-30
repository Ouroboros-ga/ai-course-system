"""StructuredLLM provider wrapping the existing shared LLM client.

This provider implements ``StructuredLLMPort`` by delegating to the
existing ``app.common.llm_client.llm_client`` — the single shared LLM
gateway used by Edu (via ``OpenAICompatibleTeachingLLM``) and Prep (via
direct ``llm_client.chat`` calls). It does NOT create a second HTTP
client or a parallel network stack.

Why wrap instead of re-implement:
    The audit identified the risk of two LLM stacks drifting in API
    address, timeout, retry, token accounting, secret loading, and
    response_format behavior. By delegating to the existing client,
    configuration stays single-sourced.

What this adds:
    - Pydantic schema validation (when ``output_schema`` is provided)
    - One repair retry: if the first response fails validation, a
      repair prompt is sent and the response is retried once
    - Normalized ``LLMResponse`` (contracts/llm.py) with ``parsed``
      field for structured output
    - Token/cost aggregation across the first + repair call
    - Prompt version tagging in trace context

Design rules:
    - The provider does NOT know about teaching, prep, or coding.
    - A second validation failure raises ``StructuredOutputError``.
    - The provider is stateless and process-level safe; it holds no
      per-request state.
    - API keys, timeouts, and model selection are handled by the shared
      ``llm_client``; this provider does NOT read settings directly.

Backward compatibility:
    The existing ``OpenAICompatibleTeachingLLM`` (in ``providers/teaching/llm.py``)
    continues to work for the EDU agent. This new provider is the preferred
    abstraction for new code that needs structured output.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from pydantic import BaseModel, ValidationError

from app.common.llm_client import LLMResponse as SharedLLMResponse, Message, llm_client

from ...contracts.llm import (
    LLMOptions,
    LLMResponse,
    LLMTraceContext,
    StructuredOutputError,
)

logger = logging.getLogger(__name__)

# Repair prompt sent when the first response fails schema validation.
_REPAIR_SYSTEM = (
    "Your previous response did not match the expected JSON schema. "
    "Return ONLY valid JSON matching this schema. Do not include any "
    "explanation, markdown, or code fences."
)


class SharedLLMStructuredProvider:
    """Structured LLM provider delegating to the shared ``llm_client``.

    This provider wraps ``app.common.llm_client.llm_client`` (the single
    shared LLM gateway) and adds schema validation + one repair retry.
    It does NOT create its own HTTP client, ensuring configuration stays
    single-sourced.

    The provider is stateless and safe for concurrent use. The underlying
    ``llm_client`` manages its own HTTP connection pool.
    """

    def __init__(self, *, client: Any | None = None) -> None:
        # Allow injecting a mock client for tests; default to the shared client.
        self._client = client or llm_client

    async def complete(
        self,
        *,
        messages: list[Mapping[str, str]],
        output_schema: type[BaseModel] | None = None,
        options: LLMOptions,
        trace_context: LLMTraceContext,
    ) -> LLMResponse:
        """Complete a chat exchange with optional structured output."""
        started = time.monotonic()

        # Convert generic message dicts to the shared client's Message type.
        shared_messages = [
            Message(role=msg["role"], content=msg["content"])
            for msg in messages
        ]

        # Build kwargs for the shared client from LLMOptions.
        kwargs: dict[str, Any] = {"temperature": options.temperature}
        if options.max_tokens is not None:
            kwargs["max_tokens"] = options.max_tokens
        if options.response_format is not None:
            kwargs["response_format"] = dict(options.response_format)

        # First attempt via the shared client.
        first_response = await self._call_shared(
            messages=shared_messages,
            kwargs=kwargs,
            trace_context=trace_context,
        )

        # If no schema, return raw text.
        if output_schema is None:
            return _to_structured_response(first_response, started, repaired=False)

        # Validate against schema; repair once if needed.
        try:
            parsed = output_schema.model_validate_json(first_response.content)
            return _to_structured_response(first_response, started, repaired=False, parsed=parsed)
        except ValidationError as first_error:
            logger.warning(
                "StructuredLLM[%s]: first response failed schema validation (%s); "
                "attempting one repair retry.",
                trace_context.purpose or "unknown",
                first_error.__class__.__name__,
            )

        # Repair retry: send the original messages + repair instruction.
        repair_messages = [*shared_messages, Message(role="system", content=_REPAIR_SYSTEM)]
        if options.response_format is None:
            repair_kwargs = dict(kwargs)
            repair_kwargs["response_format"] = {"type": "json_object"}
        else:
            repair_kwargs = kwargs

        repair_response = await self._call_shared(
            messages=repair_messages,
            kwargs=repair_kwargs,
            trace_context=trace_context,
        )

        try:
            parsed = output_schema.model_validate_json(repair_response.content)
        except ValidationError as second_error:
            logger.warning(
                "StructuredLLM[%s]: repair retry also failed schema validation: %s",
                trace_context.purpose or "unknown",
                second_error.errors(include_input=False),
            )
            raise StructuredOutputError(
                f"LLM response did not match schema after one repair retry: "
                f"{second_error.__class__.__name__}",
            ) from second_error

        # Merge usage from both calls.
        merged_response = _merge_responses(first_response, repair_response)
        return _to_structured_response(merged_response, started, repaired=True, parsed=parsed)

    async def _call_shared(
        self,
        *,
        messages: list[Message],
        kwargs: dict[str, Any],
        trace_context: LLMTraceContext,
    ) -> SharedLLMResponse:
        """Call the shared llm_client with error normalization."""
        try:
            return await self._client.chat(messages, **kwargs)
        except Exception as error:
            # Normalize shared client errors into StructuredOutputError so
            # callers have a single error type to handle.
            raise StructuredOutputError(
                f"Shared LLM client call failed: {type(error).__name__}: {error}",
            ) from error


def _to_structured_response(
    shared: SharedLLMResponse,
    started: float,
    *,
    repaired: bool,
    parsed: BaseModel | None = None,
) -> LLMResponse:
    """Convert the shared client's LLMResponse to the contracts LLMResponse."""
    return LLMResponse(
        content=shared.content,
        parsed=parsed,
        model=shared.model,
        latency_ms=(time.monotonic() - started) * 1000,
        usage=dict(shared.usage) if shared.usage else {},
        repaired=repaired,
    )


def _merge_responses(first: SharedLLMResponse, second: SharedLLMResponse) -> SharedLLMResponse:
    """Merge two shared responses for usage aggregation.

    Returns the second response (the successful one) with merged usage.
    """
    merged_usage: dict[str, int] = dict(first.usage) if first.usage else {}
    if second.usage:
        for key, value in second.usage.items():
            merged_usage[key] = merged_usage.get(key, 0) + value
    return SharedLLMResponse(
        content=second.content,
        usage=merged_usage,
        model=second.model,
        finish_reason=second.finish_reason,
        latency_ms=first.latency_ms + second.latency_ms,
    )


__all__ = ["SharedLLMStructuredProvider"]
