"""Compatibility shim: web-research port now lives in providers/research/web_research."""

from __future__ import annotations

from ..providers.research.web_research import (
    CallableWebResearchPort,
    make_session_scoped_web_research_port,
)
