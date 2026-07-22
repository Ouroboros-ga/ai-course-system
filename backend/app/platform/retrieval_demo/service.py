"""Orchestration for user-visible Shadow-1 runs, without touching V1."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Any

from .mode import DemoModeState, resolve_demo_mode
from .provider import RESEARCH_ROOT, ResearchR2Provider
from .store import DemoRunStore


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    point = (len(ordered) - 1) * percentile
    low, high = math.floor(point), math.ceil(point)
    return ordered[low] + (ordered[high] - ordered[low]) * (point - low)


class DemoService:
    def __init__(self, *, configured_mode: str, environment: str, provider: Any | None = None, store: DemoRunStore | None = None) -> None:
        self.configured_mode = configured_mode
        self.environment = environment
        self.provider = provider or ResearchR2Provider()
        self.store = store or DemoRunStore(RESEARCH_ROOT / "demo_runs")
        self.runtime_override: str | None = None
        self._latencies: list[float] = []
        self._lock = threading.Lock()

    def mode_state(self) -> DemoModeState:
        return resolve_demo_mode(configured_mode=self.configured_mode, environment=self.environment, runtime_override=self.runtime_override)

    def rollback_to_v1_only(self) -> DemoModeState:
        self.runtime_override = "v1_only"
        return self.mode_state()

    def status(self) -> dict[str, Any]:
        mode = self.mode_state()
        return {
            "configured_mode": mode.configured_mode,
            "effective_mode": mode.effective_mode,
            "enabled": mode.enabled,
            "reason": mode.reason,
            "experimental": True,
            "provider": "R2 BM25 + local BGE Dense + RRF" if mode.enabled else None,
            "metadata": self.provider.metadata if mode.enabled else None,
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
        warnings = ["Reviewed Silver 仅用于离线研究演示，不是正式 Human Gold。", "R3 图扩展未被调用，也未声称提升检索指标。"]
        if course_id not in self.provider.course_ids:
            result = {"status": "abstain", "abstain_reason": "course_not_available", "hits": []}
            warnings.append("course_id 不在冻结演示课程范围内；检索在建索引前已拒绝。")
        else:
            try:
                result = self.provider.retrieve(course_id=course_id, question=question)
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
                    {"name": "bm25_course_local", "detail": "frozen R0 tokenizer and course-local BM25"},
                    {"name": "dense_local_exact_cosine", "detail": "fixed local BGE revision; no vector service"},
                    {"name": "rrf", "detail": "frozen R2 reciprocal-rank fusion"},
                    {"name": "evidence_citation_closure", "detail": "hits retain Evidence ID, page, block, and citation key"},
                ],
                "elapsed_ms": round(elapsed * 1000, 3),
                "r3_graph_expansion_called": False,
            },
            "runtime": {"request_ms": round(elapsed * 1000, 3), **self._latency_summary(), **self.provider.metadata},
        }
        response["demo_run_id"] = self.store.save(response)
        return response
