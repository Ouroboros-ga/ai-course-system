"""Compatibility shim: retrieval-demo ports now live in providers/retrieval/demo."""

from __future__ import annotations

from ..providers.retrieval.demo import (
    CallableLearningEventPort,
    CallableRecommendationPort,
    CallableStudentModelingPort,
    Judge0SandboxPort,
    RetrievalDemoEvidencePort,
    RetrievalDemoKnowledgeGraphPort,
    RetrievalDemoScopePort,
    UnavailableSandboxPort,
)
