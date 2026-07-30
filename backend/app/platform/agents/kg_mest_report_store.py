"""Compatibility shim: ``KGMestShadowReportStore`` now lives in ``edu/kg_mest_report_store``."""

from __future__ import annotations

from .edu.kg_mest_report_store import DEFAULT_REPORT_ROOT, KGMestShadowReportStore

__all__ = ["KGMestShadowReportStore", "DEFAULT_REPORT_ROOT"]
