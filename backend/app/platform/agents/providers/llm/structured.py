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

import json
import logging
import time
import hashlib
from typing import Any, Mapping

from pydantic import BaseModel, ValidationError

from app.common.llm_client import LLMResponse as SharedLLMResponse, Message, llm_client

from ...contracts.llm import (
    LLMOptions,
    LLMResponse,
    LLMTraceContext,
    StructuredOutputError,
)
from ...runtime.diagnostic_context import current_diagnostic_context

logger = logging.getLogger(__name__)

# Repair prompt sent when the first response fails schema validation.
_REPAIR_SYSTEM = (
    "Your previous response did not match the expected JSON schema. "
    "Return ONLY valid JSON matching this schema. Do not include any "
    "explanation, markdown, or code fences."
)

_RESPONSE_FORMAT_FALLBACK_SYSTEM = (
    "The model gateway does not support response_format for this request. "
    "Return ONLY one valid JSON object. Do not include an explanation, markdown, or code fences."
)


class SharedLLMStructuredProvider:
    """Structured LLM provider delegating to the shared ``llm_client``.

    This provider wraps ``app.common.llm_client.llm_client`` (the single
    shared LLM gateway) and adds schema validation + one repair retry.
    It does NOT create its own HTTP client, ensuring configuration stays
    single-sourced.

    The provider keeps only the gateway's response-format capability. It never
    stores course content, prompts, or responses; the capability cache avoids
    paying for the same rejected request at every preparation stage.
    """

    def __init__(self, *, client: Any | None = None, diagnostic_sink: Any | None = None) -> None:
        # Allow injecting a mock client for tests; default to the shared client.
        self._client = client or llm_client
        self._response_format_supported: bool | None = None
        self._diagnostic_sink = diagnostic_sink

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

        # Build kwargs for the shared client from LLMOptions.  A number of
        # OpenAI-compatible gateways implement chat completions but reject all
        # response_format variants.  Once detected, omit it for the remaining
        # calls through this provider and rely on the schema validator/repair
        # loop below instead.
        kwargs: dict[str, Any] = {"temperature": options.temperature}
        if options.max_tokens is not None:
            kwargs["max_tokens"] = options.max_tokens
        if options.provider_options:
            # These are bounded provider request knobs (for example disabling
            # hidden reasoning on a tiny JSON compiler call). Keep them out of
            # diagnostics and do not merge them into the prompt.
            kwargs.update(dict(options.provider_options))
        use_response_format = (
            options.response_format is not None
            and self._response_format_supported is not False
        )
        if use_response_format:
            kwargs["response_format"] = dict(options.response_format)

        request_messages = shared_messages
        response_format_fallback = False
        try:
            # First attempt via the shared client.
            first_response = await self._call_shared(
                messages=request_messages,
                kwargs=kwargs,
                trace_context=trace_context,
            )
        except StructuredOutputError as error:
            if not use_response_format or not _response_format_unsupported(error):
                raise
            self._response_format_supported = False
            response_format_fallback = True
            request_messages = [
                *shared_messages,
                Message(
                    role="system",
                    content=_response_format_fallback_instruction(output_schema),
                ),
            ]
            kwargs = {key: value for key, value in kwargs.items() if key != "response_format"}
            logger.info(
                "StructuredLLM[%s]: gateway rejected response_format; "
                "using prompt-constrained JSON fallback.",
                trace_context.purpose or "unknown",
            )
            first_response = await self._call_shared(
                messages=request_messages,
                kwargs=kwargs,
                trace_context=trace_context,
            )

        # If no schema, return raw text.
        if output_schema is None:
            await self._record_diagnostic(response=first_response, trace_context=trace_context, options=options, output_schema=output_schema, attempt=1, repaired=False, response_format_fallback=response_format_fallback, input_chars=sum(len(item.content) for item in request_messages))
            return _to_structured_response(first_response, started, repaired=False, response_format_fallback=response_format_fallback)

        if _is_truncated(first_response.finish_reason):
            await self._record_diagnostic(response=first_response, trace_context=trace_context, options=options, output_schema=output_schema, attempt=1, repaired=False, response_format_fallback=response_format_fallback, input_chars=sum(len(item.content) for item in request_messages))
            raise StructuredOutputError(
                "LLM structured output was truncated before validation",
                reason_code="MODEL_OUTPUT_TRUNCATED",
                stage=trace_context.node,
                attempts=1,
                schema_name=output_schema.__name__,
                finish_reason=first_response.finish_reason,
                usage=first_response.usage,
                model=first_response.model,
                output_chars=len(first_response.content or ""),
                truncated=True,
                response_format_fallback=response_format_fallback,
            )

        # Validate against schema; repair once if needed.
        try:
            parsed = output_schema.model_validate_json(first_response.content)
            await self._record_diagnostic(response=first_response, trace_context=trace_context, options=options, output_schema=output_schema, attempt=1, repaired=False, response_format_fallback=response_format_fallback, input_chars=sum(len(item.content) for item in request_messages))
            return _to_structured_response(first_response, started, repaired=False, parsed=parsed, response_format_fallback=response_format_fallback)
        except ValidationError as first_error:
            await self._record_diagnostic(
                response=first_response,
                trace_context=trace_context,
                options=options,
                output_schema=output_schema,
                attempt=1,
                repaired=False,
                response_format_fallback=response_format_fallback,
                validation_errors=_validation_errors(first_error),
                input_chars=sum(len(item.content) for item in request_messages),
            )
            repair_instruction = _repair_instruction(
                output_schema=output_schema,
                validation_error=first_error,
                trace_context=trace_context,
            )
            logger.warning(
                "StructuredLLM[%s]: first response failed schema validation (%s); "
                "attempting one repair retry.",
                trace_context.purpose or "unknown",
                first_error.__class__.__name__,
            )

        # Repair retry: send the original messages + repair instruction.
        repair_messages = [
            *request_messages,
            Message(role="system", content=repair_instruction),
        ]
        # Preserve the successful request's capability set.  In particular,
        # do not re-add json_object after the compatibility fallback.
        repair_kwargs = dict(kwargs)

        repair_response = await self._call_shared(
            messages=repair_messages,
            kwargs=repair_kwargs,
            trace_context=trace_context,
        )
        if _is_truncated(repair_response.finish_reason):
            await self._record_diagnostic(response=repair_response, trace_context=trace_context, options=options, output_schema=output_schema, attempt=2, repaired=True, response_format_fallback=response_format_fallback, input_chars=sum(len(item.content) for item in repair_messages))
            raise StructuredOutputError(
                "LLM structured output repair was truncated before validation",
                reason_code="MODEL_OUTPUT_TRUNCATED",
                stage=trace_context.node,
                attempts=2,
                schema_name=output_schema.__name__,
                finish_reason=repair_response.finish_reason,
                usage=_merge_usage(first_response.usage, repair_response.usage),
                model=repair_response.model or first_response.model,
                output_chars=len(repair_response.content or ""),
                truncated=True,
                response_format_fallback=response_format_fallback,
            )
        try:
            parsed = output_schema.model_validate_json(repair_response.content)
        except ValidationError as second_error:
            await self._record_diagnostic(
                response=repair_response,
                trace_context=trace_context,
                options=options,
                output_schema=output_schema,
                attempt=2,
                repaired=True,
                response_format_fallback=response_format_fallback,
                validation_errors=_validation_errors(second_error),
                input_chars=sum(len(item.content) for item in repair_messages),
            )
            logger.warning(
                "StructuredLLM[%s]: repair retry also failed schema validation: %s",
                trace_context.purpose or "unknown",
                second_error.errors(include_input=False),
            )
            raise StructuredOutputError(
                f"LLM response did not match schema after one repair retry: "
                f"{second_error.__class__.__name__}",
                reason_code="structured_output_invalid",
                stage=trace_context.node,
                validation_errors=_validation_errors(second_error),
                attempts=2,
                schema_name=output_schema.__name__,
                finish_reason=repair_response.finish_reason or first_response.finish_reason,
                usage=_merge_usage(first_response.usage, repair_response.usage),
                model=repair_response.model or first_response.model,
                input_chars=sum(len(item.content) for item in repair_messages),
                output_chars=len(repair_response.content or ""),
                truncated=_is_truncated(repair_response.finish_reason),
                response_format_fallback=response_format_fallback,
            ) from second_error

        await self._record_diagnostic(response=repair_response, trace_context=trace_context, options=options, output_schema=output_schema, attempt=2, repaired=True, response_format_fallback=response_format_fallback, input_chars=sum(len(item.content) for item in repair_messages))
        # Merge usage from both calls.
        merged_response = _merge_responses(first_response, repair_response)
        return _to_structured_response(merged_response, started, repaired=True, parsed=parsed, response_format_fallback=response_format_fallback)

    async def _record_diagnostic(self, *, response: SharedLLMResponse,
                                 trace_context: LLMTraceContext, options: LLMOptions,
                                 output_schema: type[BaseModel] | None = None,
                                 attempt: int, repaired: bool,
                                 response_format_fallback: bool,
                                 validation_errors: list[Mapping[str, Any]] | None = None,
                                 input_chars: int = 0) -> None:
        if self._diagnostic_sink is None or not hasattr(self._diagnostic_sink, "record"):
            return
        context = current_diagnostic_context.get()
        usage = dict(response.usage or {})
        # Keep the provider response usage plus the bounded request budget so
        # a diagnostic can prove which code path handled a request. No prompt,
        # response text, or provider option values are persisted.
        usage.setdefault("requested_max_tokens", options.max_tokens)
        usage.setdefault("provider_option_keys", sorted(options.provider_options.keys()))
        await self._diagnostic_sink.record(
            run_id=trace_context.run_id or context.run_id,
            trace_id=trace_context.trace_id or context.trace_id,
            course_id=trace_context.course_id or context.course_id or None,
            agent_type=trace_context.agent_type or "prep",
            stage=trace_context.node,
            node=trace_context.node,
            purpose=trace_context.purpose,
            prompt_version=options.prompt_version,
            schema_name=getattr(output_schema, "__name__", ""),
            model=response.model,
            attempt=attempt,
            repaired=repaired,
            finish_reason=response.finish_reason or "",
            input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
            output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
            input_chars=input_chars,
            output_chars=len(response.content or ""),
            response_hash=hashlib.sha256((response.content or "").encode("utf-8")).hexdigest(),
            truncated=_is_truncated(response.finish_reason),
            response_format_requested=bool(options.response_format),
            response_format_fallback=response_format_fallback,
            validation_errors=list(validation_errors or []),
            usage_metadata=usage,
            latency_ms=float(getattr(response, "latency_ms", 0.0) or 0.0),
        )

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
    response_format_fallback: bool = False,
) -> LLMResponse:
    """Convert the shared client's LLMResponse to the contracts LLMResponse."""
    return LLMResponse(
        content=shared.content,
        parsed=parsed,
        model=shared.model,
        latency_ms=(time.monotonic() - started) * 1000,
        usage=dict(shared.usage) if shared.usage else {},
        repaired=repaired,
        finish_reason=shared.finish_reason,
        response_format_fallback=response_format_fallback,
        input_chars=0,
        output_chars=len(shared.content or ""),
        truncated=_is_truncated(shared.finish_reason),
    )


def _merge_responses(first: SharedLLMResponse, second: SharedLLMResponse) -> SharedLLMResponse:
    """Merge two shared responses for usage aggregation.

    Returns the second response (the successful one) with merged usage.

    OpenAI-compatible gateways do not agree on the shape of ``usage``.  The
    top-level token counters are numeric, while fields such as
    ``prompt_tokens_details`` and ``completion_tokens_details`` are nested
    mappings.  Merge numeric counters arithmetically, recurse into mappings,
    and keep the successful response's value for incompatible shapes.
    """
    merged_usage: dict[str, Any] = dict(first.usage) if first.usage else {}
    if second.usage:
        for key, value in second.usage.items():
            if key not in merged_usage:
                merged_usage[key] = value
            else:
                merged_usage[key] = _merge_usage_values(merged_usage[key], value)
    return SharedLLMResponse(
        content=second.content,
        usage=merged_usage,
        model=second.model,
        finish_reason=second.finish_reason,
        latency_ms=first.latency_ms + second.latency_ms,
    )


def _merge_usage_values(first: Any, second: Any) -> Any:
    """Merge one usage field without assuming that it is numeric."""
    if isinstance(first, Mapping) and isinstance(second, Mapping):
        merged: dict[str, Any] = dict(first)
        for key, value in second.items():
            merged[key] = (
                value
                if key not in merged
                else _merge_usage_values(merged[key], value)
            )
        return merged
    if (
        isinstance(first, (int, float))
        and not isinstance(first, bool)
        and isinstance(second, (int, float))
        and not isinstance(second, bool)
    ):
        return first + second
    # The successful response is the safest value when a provider changes the
    # type of an optional usage field between attempts.
    return second


def _response_format_unsupported(error: BaseException) -> bool:
    """Read only the safe reason classification preserved in an error chain."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if getattr(current, "reason_code", "") == "response_format_unsupported":
            return True
        message = str(current).lower()
        if "response_format" in message and any(
            marker in message
            for marker in ("unavailable", "unsupported", "not support", "invalid_request")
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _response_format_fallback_instruction(output_schema: type[BaseModel] | None) -> str:
    """Build a JSON-only fallback instruction without retaining gateway text."""
    if output_schema is None:
        return _RESPONSE_FORMAT_FALLBACK_SYSTEM
    schema = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
    return f"{_RESPONSE_FORMAT_FALLBACK_SYSTEM}\nJSON Schema:\n{schema}"


def _validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    """Return a compact, input-redacted form of Pydantic errors."""
    items: list[dict[str, Any]] = []
    for item in error.errors(include_input=False):
        items.append({
            "loc": [str(part) for part in item.get("loc", ())],
            "type": str(item.get("type", "validation_error")),
            "msg": str(item.get("msg", "invalid value"))[:240],
        })
    return items[:20]


def _is_truncated(finish_reason: str | None) -> bool:
    return str(finish_reason or "").lower() in {"length", "max_tokens", "token_limit"}


def _merge_usage(first: Mapping[str, Any] | None, second: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = dict(first or {})
    for key, value in (second or {}).items():
        if isinstance(value, (int, float)) and isinstance(merged.get(key), (int, float)):
            merged[key] += value
        else:
            merged[key] = value
    return merged


def _repair_instruction(
    *,
    output_schema: type[BaseModel],
    validation_error: ValidationError,
    trace_context: LLMTraceContext,
) -> str:
    """Give the repair call the exact contract and field-level failures."""
    schema = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
    errors = json.dumps(_validation_errors(validation_error), ensure_ascii=False)
    stage = trace_context.node or trace_context.purpose or "structured output"
    return (
        f"{_REPAIR_SYSTEM}\n"
        f"Failed stage: {stage}\n"
        f"JSON Schema:\n{schema}\n"
        f"Validation errors from the previous response:\n{errors}\n"
        "Rebuild the complete object. Do not omit required fields and do not "
        "return a partial object."
    )


__all__ = ["SharedLLMStructuredProvider"]
