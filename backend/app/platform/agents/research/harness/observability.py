"""Process-local metrics and structured node logging for ResearchAgent."""
from __future__ import annotations

import logging
import threading
from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("app.research_agent.harness")


class ResearchHarnessMetrics:
    """Low-cardinality counters suitable for later Prometheus export."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[tuple[str, str]] = Counter()
        self._duration_ms: dict[str, float] = defaultdict(float)

    def observe(self, *, node: str, status: str, duration_ms: float) -> None:
        with self._lock:
            self._counts[(node, status)] += 1
            self._duration_ms[node] += max(0.0, float(duration_ms))

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "node_counts": {
                    f"{node}:{status}": count
                    for (node, status), count in sorted(self._counts.items())
                },
                "node_duration_ms_total": {
                    node: round(value, 3)
                    for node, value in sorted(self._duration_ms.items())
                },
            }


research_harness_metrics = ResearchHarnessMetrics()


def record_node(
    *,
    node: str,
    status: str,
    duration_ms: float,
    trace_id: str,
    run_id: str,
) -> None:
    """Record bounded operational fields; never log prompts or research text."""
    research_harness_metrics.observe(node=node, status=status, duration_ms=duration_ms)
    logger.info(
        "research_harness_node",
        extra={
            "research_node": node,
            "research_status": status,
            "duration_ms": round(duration_ms, 3),
            "trace_id": trace_id,
            "run_id": run_id,
        },
    )


__all__ = ["ResearchHarnessMetrics", "record_node", "research_harness_metrics"]

