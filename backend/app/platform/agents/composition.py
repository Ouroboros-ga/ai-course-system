"""Compatibility shim: composition roots now live in ``edu/composition``."""

from __future__ import annotations

from .edu.composition import (
    build_course_sidecar_runtime,
    build_kg_mest_shadow_sidecar_runtime,
    build_teaching_runtime,
)

__all__ = [
    "build_teaching_runtime",
    "build_course_sidecar_runtime",
    "build_kg_mest_shadow_sidecar_runtime",
]
