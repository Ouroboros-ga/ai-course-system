"""Orchestration for user-visible Shadow-1 runs, without touching V1."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Any

from .mode import GRAPH_EXPANSION_PRODUCTION_CANDIDATE_ENABLED, DemoModeState, resolve_demo_mode
from .course_provider import CourseSidecarR2Provider
from .provider import ResearchR2Provider
from .store import DemoRunStore


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_ROOT = PROJECT_ROOT / "research" / "product1_graph_retrieval"


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    point = (len(ordered) - 1) * percentile
    low, high = math.floor(point), math.ceil(point)
    return ordered[low] + (ordered[high] - ordered[low]) * (point - low)


class DemoService:
    def __init__(self, *, configured_mode: str, environment: str, provider: Any | None = None, store: DemoRunStore | None = None, fallback_provider: Any | None = None) -> None:
        self.configured_mode = configured_mode
        self.environment = environment
        self.provider = provider or CourseSidecarR2Provider()
        self._fallback_provider = fallback_provider
        self.runtime_source = "course_sidecar"
        self.store = store or DemoRunStore(RESEARCH_ROOT / "demo_runs")
        self.runtime_override: str | None = None
        self._latencies: list[float] = []
        self._lock = threading.Lock()

    @property
    def active_provider(self) -> Any:
        if self.runtime_source == "course_sidecar":
            return self.provider
        if self._fallback_provider is None:
            # This legacy provider is instantiated only after an explicit
            # operator rollback. It is never consulted by the normal path.
            self._fallback_provider = ResearchR2Provider()
        return self._fallback_provider

    def mode_state(self) -> DemoModeState:
        return resolve_demo_mode(configured_mode=self.configured_mode, environment=self.environment, runtime_override=self.runtime_override)

    def rollback_to_v1_only(self) -> DemoModeState:
        self.runtime_override = "v1_only"
        return self.mode_state()

    def rollback_to_fixture(self) -> None:
        """Immediate process-local rollback for a broken sidecar path.

        The response exposes its source as ``research_fixture_rollback`` so
        callers cannot mistake it for parsed-course retrieval.
        """
        self.runtime_source = "research_fixture_rollback"

    def status(self) -> dict[str, Any]:
        mode = self.mode_state()
        return {
            "configured_mode": mode.configured_mode,
            "effective_mode": mode.effective_mode,
            "enabled": mode.enabled,
            "reason": mode.reason,
            "experimental": True,
            "provider": "R2 BM25 + local BGE Dense + RRF" if mode.enabled else None,
            "data_source": self.runtime_source,
            "graph_expansion_production_candidate_enabled": GRAPH_EXPANSION_PRODUCTION_CANDIDATE_ENABLED,
            "metadata": self.active_provider.metadata if mode.enabled else None,
        }

    def _latency_summary(self) -> dict[str, float | int]:
        with self._lock:
            values = list(self._latencies)
        return {"sample_count": len(values), "p50_ms": round(_percentile(values, 0.5) * 1000, 3), "p95_ms": round(_percentile(values, 0.95) * 1000, 3)}

    @staticmethod
    def _comparison(v1_reference: str | None, v2: dict[str, Any]) -> dict[str, Any]:
        if not v1_reference:
            return {
                "status": "v1_not_invoked",
                "warning": "V1 主链为避免付费模型调用和行为干扰而保持隔离；可由操作员粘贴 V1 参考回答后再保存对比。",
                "v1_text": None,
                "v2_hit_count": len(v2.get("hits", [])),
            }
        return {
            "status": "operator_supplied_v1_reference",
            "v1_text": v1_reference,
            "v2_hit_count": len(v2.get("hits", [])),
            "same_text": v1_reference.strip() == (v2.get("experimental_answer", {}).get("content") or "").strip(),
        }

    @staticmethod
    def _experimental_answer(result: dict[str, Any]) -> dict[str, str]:
        disclaimer = "实验回答，拒答校准尚未完成；内容仅为 R2 命中文本摘录，不是已验证答案。"
        if result.get("status") == "abstain" or not result.get("hits"):
            return {"status": "abstain", "content": "未检索到可展示的证据。" + disclaimer, "disclaimer": disclaimer}
        excerpts = [hit.get("text_snippet", "") for hit in result["hits"][:2] if hit.get("text_snippet")]
        return {"status": "experimental_evidence_extract", "content": "\n\n".join(excerpts), "disclaimer": disclaimer}

    def query(self, *, course_id: str, question: str, v1_reference: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        warnings = [
            "检索仅消费当前课程的 DocumentIR→Evidence sidecar；不读取 qrels、Reviewed Silver 或生产 ORM。",
            "R3 图扩展已从候选检索链路停用。",
        ]
        provider = self.active_provider
        if course_id not in provider.course_ids:
            result = {"status": "abstain", "abstain_reason": "course_not_available", "hits": []}
            warnings.append("course_id 不在冻结演示课程范围内；检索在建索引前已拒绝。")
        else:
            try:
                result = provider.retrieve(course_id=course_id, question=question)
            except Exception as error:  # Provider failures must not touch V1.
                result = {"status": "abstain", "abstain_reason": "demo_provider_unavailable", "hits": []}
                warnings.append(f"本地 R2 Provider 不可用：{type(error).__name__}；V1 未被调用。")
        elapsed = time.perf_counter() - started
        with self._lock:
            self._latencies.append(elapsed)
            self._latencies[:] = self._latencies[-200:]
        answer = self._experimental_answer(result)
        response = {
            "experimental": True,
            "mode": self.mode_state().effective_mode,
            "course_id": course_id,
            "data_source": self.runtime_source,
            "question": question,
            "result": result,
            "experimental_answer": answer,
            "confidence_label": "experimental_uncalibrated" if result.get("status") == "ok" else "abstain",
            "warnings": warnings,
            "v1_v2_comparison": self._comparison(v1_reference, {**result, "experimental_answer": answer}),
            "run_trace": {
                "trace_schema_version": "demo-shadow-retrieval-trace/1.0",
                "stages": [
                    {"name": "course_scope_filter", "detail": "course_id validated before BM25/Dense retrieval"},
                    {"name": "bm25_course_local", "detail": "frozen R0 tokenizer and course-local BM25 over sidecar evidence"},
                    {"name": "dense_local_exact_cosine", "detail": "fixed local BGE revision; no vector service"},
                    {"name": "rrf", "detail": "frozen R2 reciprocal-rank fusion"},
                    {"name": "evidence_citation_closure", "detail": "hits retain Evidence ID, page, block, and citation key"},
                ],
                "elapsed_ms": round(elapsed * 1000, 3),
                "r3_graph_expansion_called": False,
            },
            "runtime": {"request_ms": round(elapsed * 1000, 3), **self._latency_summary(), **provider.metadata},
        }
        response["demo_run_id"] = self.store.save(response)
        return response
