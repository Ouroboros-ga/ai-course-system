"""ResearchAgent v0 workflow: scope validation → paper search → evidence gate → response.

Only the literature-search slice is active.  Trend analysis, writing and code
reproduction have explicit Port contracts but are not inserted into this graph
until their evidence and sandbox gates are implemented.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from langgraph.graph import END, START, StateGraph

from app.services.web_research_service import sanitize_query

from ..contracts.research import PaperSearchPort, ResearchScopePort
from .state import ResearchState


@dataclass(frozen=True)
class ResearchTools:
    scope_access: ResearchScopePort
    paper_search: PaperSearchPort


def _trace(state: Mapping[str, Any], node: str, **detail: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **detail}]


def build_research_workflow(tools: ResearchTools):
    async def validate_scope(state: ResearchState) -> dict[str, Any]:
        query = sanitize_query(state.get("query", "")).strip()
        meaningful_query = re.sub(r"\[REDACTED\]|[\W_]", "", query, flags=re.IGNORECASE)
        errors = list(state.get("errors", []))
        if not state.get("course_id", "").isdigit():
            errors.append("RESEARCH_INVALID_COURSE_SCOPE")
        if len(meaningful_query) < 2:
            errors.append("RESEARCH_QUERY_TOO_SHORT")
        authorized = False
        if not errors:
            access = await tools.scope_access.authorize(
                course_id=state.get("course_id", ""),
                actor_user_id=state.get("actor_user_id", ""),
                permission="course.question.ask",
            )
            authorized = bool(access.get("allowed"))
            if not authorized:
                errors.append("RESEARCH_SCOPE_DENIED")
        return {
            "query": query[:300],
            "errors": errors,
            "trace": _trace(state, "scope_validator", accepted=not errors, authorized=authorized),
        }

    async def literature_search(state: ResearchState) -> dict[str, Any]:
        if state.get("errors"):
            return {
                "search_result": None,
                "papers": [],
                "trace": _trace(state, "literature_search", skipped=True),
            }
        result = dict(await tools.paper_search.search(
            query=state.get("query", ""),
            limit=state.get("max_results", 8),
            cursor=state.get("cursor"),
        ))
        warnings = [*state.get("warnings", []), *result.get("warnings", [])]
        degraded = list(state.get("degraded_services", []))
        if result.get("status") == "upstream_unavailable":
            degraded.append("arxiv")
        return {
            "search_result": result,
            "papers": [dict(item) for item in result.get("items", []) if isinstance(item, Mapping)],
            "warnings": warnings,
            "degraded_services": degraded,
            "trace": _trace(
                state,
                "literature_search",
                provider=result.get("provider", "unknown"),
                status=result.get("status", "unknown"),
                result_count=len(result.get("items", [])),
            ),
        }

    async def evidence_gate(state: ResearchState) -> dict[str, Any]:
        gated: list[dict[str, Any]] = []
        rejected = 0
        for paper in state.get("papers", []):
            if not paper.get("paper_id") or not paper.get("source_url") or not paper.get("title"):
                rejected += 1
                continue
            gated.append({
                **paper,
                "evidence_status": "metadata_only",
                "is_supplementary": True,
                "cannot_modify_mastery": True,
                "cannot_modify_recommendation": True,
                "cannot_modify_graph": True,
            })
        warnings = list(state.get("warnings", []))
        if rejected:
            warnings.append("RESEARCH_INCOMPLETE_METADATA_REJECTED")
        return {
            "papers": gated,
            "warnings": warnings,
            "trace": _trace(state, "evidence_gate", accepted=len(gated), rejected=rejected),
        }

    async def build_response(state: ResearchState) -> dict[str, Any]:
        result = state.get("search_result") or {}
        if state.get("errors"):
            status = "invalid_request"
            answer = "研究范围或检索词无效，请检查后重试。"
        elif result.get("status") == "upstream_unavailable":
            status = "degraded"
            answer = "arXiv 当前不可用，未生成或伪造任何论文结果。"
        elif not state.get("papers"):
            status = "no_results"
            answer = "没有找到带完整来源元数据的论文，请调整检索词。"
        else:
            status = "success"
            answer = f"找到 {len(state['papers'])} 篇 arXiv 论文元数据；这些结果仍需全文核验。"
        return {
            "status": status,
            "final_answer": answer,
            "trace": _trace(state, "response", status=status),
        }

    graph = StateGraph(ResearchState)
    graph.add_node("scope_validator", validate_scope)
    graph.add_node("literature_search", literature_search)
    graph.add_node("evidence_gate", evidence_gate)
    graph.add_node("response", build_response)
    graph.add_edge(START, "scope_validator")
    graph.add_edge("scope_validator", "literature_search")
    graph.add_edge("literature_search", "evidence_gate")
    graph.add_edge("evidence_gate", "response")
    graph.add_edge("response", END)
    return graph.compile()


__all__ = ["ResearchTools", "build_research_workflow"]
