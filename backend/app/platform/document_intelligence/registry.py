"""Parser provider protocol and registry.

Defines the ``ParserProvider`` protocol that all parsing providers must satisfy,
and the ``ParserRegistry`` that manages available providers and their capabilities.

Contract version
----------------
The parser-provider contract is versioned as ``parser-provider/X.Y``, registered
in ``docs/refactor/product1/contracts/registry.md``.  The module-level constant
``PARSER_PROVIDER_VERSION`` is the single canonical source of truth for this
contract identifier.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from ..document_intelligence.source_artifact import SourceArtifact
from .probe import ProbeResult
from .planner import ParsePlan

# ---------------------------------------------------------------------------
# Contract version
# ---------------------------------------------------------------------------

PARSER_PROVIDER_VERSION: str = "parser-provider/1.0"
"""Canonical contract version for the ParserProvider / QualityDecision / ParsePlan
interface bundle, matching the registry entry in
``docs/refactor/product1/contracts/registry.md``."""


# ---------------------------------------------------------------------------
# ParserCapabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParserCapabilities:
    """Declared capabilities of a parser provider.

    These are used by the planner to select appropriate providers for a
    given document type and quality target.
    """

    supported_formats: Tuple[str, ...] = field(default_factory=tuple)
    supports_tables: bool = False
    supports_formulas: bool = False
    supports_ocr: bool = False
    supports_notes: bool = False
    supports_reading_order: bool = False
    supports_heading_detection: bool = False
    supports_visual_assets: bool = False
    supports_coordinates: bool = False
    supports_provenance: bool = False
    requires_network: bool = False
    requires_gpu: bool = False
    max_file_size_bytes: int = 500 * 1024 * 1024  # 500 MB default
    max_pages: int = 500


# ---------------------------------------------------------------------------
# ParserOutput
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParserOutput:
    """Raw output from a ParserProvider.

    This is the provider-specific result before mapping to DocumentIR.
    The provider is responsible for populating structured fields; the
    IR mapper converts this to canonical DocumentIR blocks.
    """

    provider: str
    provider_version: str
    pages: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_data: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ParserProvider Protocol
# ---------------------------------------------------------------------------


class ParserProvider(Protocol):
    """Protocol that all parser providers must satisfy.

    Providers are stateless and should be registered once per application
    lifecycle.  The ``parse`` method is the single entry point for all
    parsing work.
    """

    name: str
    version: str
    capabilities: ParserCapabilities

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        """Parse the given source artifact according to the parse plan.

        Args:
            source: The source artifact to parse.
            plan: The parse plan with configuration and context.

        Returns:
            A ParserOutput with structured page/slide data.

        Raises:
            ParseTimeoutError: If parsing exceeds the configured timeout.
            ParseUnavailableError: If the provider's engine is unavailable.
            ParseMalformedError: If the input is malformed.
        """
        ...


# ---------------------------------------------------------------------------
# Parse errors (runtime failures)
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Base class for parse errors."""
    code: str = "PARSE_ERROR"

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class ParseTimeoutError(ParseError):
    """Parsing exceeded the configured timeout."""
    code = "TIMEOUT"


class ParseUnavailableError(ParseError):
    """Provider engine is unavailable (not installed, missing deps, etc.)."""
    code = "UNAVAILABLE"


class ParseMalformedError(ParseError):
    """Input is malformed or corrupted."""
    code = "MALFORMED"


# ---------------------------------------------------------------------------
# ParserRegistry
# ---------------------------------------------------------------------------


class ParserRegistry:
    """Registry of available parser providers.

    Providers are registered by name.  The registry supports lookup by
    capability for the planner.
    """

    def __init__(self) -> None:
        self._providers: Dict[str, ParserProvider] = {}
        self._capability_index: Dict[str, List[str]] = {}

    def register(self, provider: ParserProvider) -> None:
        """Register a parser provider.

        Args:
            provider: The provider instance to register.

        Raises:
            ValueError: If a provider with the same name is already registered.
        """
        if provider.name in self._providers:
            raise ValueError(
                f"Provider {provider.name!r} is already registered"
            )
        self._providers[provider.name] = provider
        self._rebuild_index()

    def unregister(self, name: str) -> None:
        """Remove a provider by name."""
        self._providers.pop(name, None)
        self._rebuild_index()

    def get(self, name: str) -> Optional[ParserProvider]:
        """Get a provider by name."""
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        """List all registered provider names."""
        return list(self._providers.keys())

    def find_by_format(self, fmt: str) -> List[ParserProvider]:
        """Find providers that support a given format."""
        results: List[ParserProvider] = []
        for provider in self._providers.values():
            if fmt in provider.capabilities.supported_formats:
                results.append(provider)
        return results

    def find_by_capability(self, **kwargs: bool) -> List[ParserProvider]:
        """Find providers matching specific capability flags.

        Example: ``registry.find_by_capability(supports_tables=True)``
        """
        results: List[ParserProvider] = []
        for provider in self._providers.values():
            matches = True
            for key, val in kwargs.items():
                if getattr(provider.capabilities, key, None) != val:
                    matches = False
                    break
            if matches:
                results.append(provider)
        return results

    def provider_count(self) -> int:
        return len(self._providers)

    def get_probe_hints(self, probe: ProbeResult) -> List[str]:
        """Return provider names that can handle the probed document."""
        candidates: List[str] = []
        fmt = probe.detected_format.value
        for name, provider in self._providers.items():
            if fmt in provider.capabilities.supported_formats:
                candidates.append(name)
        return candidates

    def _rebuild_index(self) -> None:
        self._capability_index.clear()
        for name, provider in self._providers.items():
            for fmt in provider.capabilities.supported_formats:
                self._capability_index.setdefault(fmt, []).append(name)
