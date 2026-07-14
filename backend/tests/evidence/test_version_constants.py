"""
Version constant tests (P1-03 G2.1).

Verifies each module-level version constant matches the registry-registered
value. These constants are the single source of truth for contract version
semantics used by the evidence/citation/text-transform/retrieval-provider
subsystems.

Registry-registered values (from P1-00 contract registry):
- ``evidence/1.0``
- ``citation/1.0``
- ``text-transform/1.0``
- ``retrieval-provider/1.0``
"""

import pytest

from app.platform.evidence.contracts import EVIDENCE_VERSION
from app.platform.evidence.citation import CITATION_VERSION
from app.platform.evidence.text_transform import TEXT_TRANSFORM_VERSION
from app.platform.retrieval.providers.contracts import RETRIEVAL_PROVIDER_VERSION


class TestEvidenceVersion:
    def test_evidence_version_matches_registry(self):
        assert EVIDENCE_VERSION == "evidence/1.0"

    def test_evidence_version_format(self):
        # Must match pattern: ``<name>/<major>.<minor>``
        parts = EVIDENCE_VERSION.split("/")
        assert len(parts) == 2
        assert parts[0] == "evidence"
        version_parts = parts[1].split(".")
        assert len(version_parts) == 2
        assert version_parts[0].isdigit()
        assert version_parts[1].isdigit()


class TestCitationVersion:
    def test_citation_version_matches_registry(self):
        assert CITATION_VERSION == "citation/1.0"

    def test_citation_version_format(self):
        parts = CITATION_VERSION.split("/")
        assert len(parts) == 2
        assert parts[0] == "citation"
        version_parts = parts[1].split(".")
        assert len(version_parts) == 2
        assert version_parts[0].isdigit()
        assert version_parts[1].isdigit()


class TestTextTransformVersion:
    def test_text_transform_version_matches_registry(self):
        assert TEXT_TRANSFORM_VERSION == "text-transform/1.0"

    def test_text_transform_version_format(self):
        parts = TEXT_TRANSFORM_VERSION.split("/")
        assert len(parts) == 2
        assert parts[0] == "text-transform"
        version_parts = parts[1].split(".")
        assert len(version_parts) == 2
        assert version_parts[0].isdigit()
        assert version_parts[1].isdigit()


class TestRetrievalProviderVersion:
    def test_retrieval_provider_version_matches_registry(self):
        assert RETRIEVAL_PROVIDER_VERSION == "retrieval-provider/1.0"

    def test_retrieval_provider_version_format(self):
        parts = RETRIEVAL_PROVIDER_VERSION.split("/")
        assert len(parts) == 2
        assert parts[0] == "retrieval-provider"
        version_parts = parts[1].split(".")
        assert len(version_parts) == 2
        assert version_parts[0].isdigit()
        assert version_parts[1].isdigit()
