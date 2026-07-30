"""Compatibility shim: teaching prompts now live in ``edu/prompts``."""

from __future__ import annotations

from ..edu.prompts import (
    CONCEPT_SYSTEM,
    INTENT_SYSTEM,
    PROMPT_VERSION,
    RESPONSE_SYSTEM,
)

__all__ = ["PROMPT_VERSION", "INTENT_SYSTEM", "CONCEPT_SYSTEM", "RESPONSE_SYSTEM"]
