"""ResearchAgent 前沿趋势分析（trend_analysis）契约与 fail-closed 行为。

覆盖：关键词/年份/趋势方向/主题分类聚合、样本不足的诚实降级、
工作流路由（含无现成结果时先检索）、越权拒绝。全部本地 Fake，不调用外部服务。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.platform.agents.research.trends import analyze_paper_trends
from app.platform.agents.research.workflow import ResearchTools, build_research_workflow


def _paper(paper_id: str, title: str, year: int, category: str = "cs.CL", abstract: str = "") -> dict:
    return {
        "provider": "arxiv",
        "paper_id": paper_id,
        "title": title,
        "abstract": abstract,
        "authors": [],
        "published_at": f"{year}-01-01T00:00:00Z",
        "year": year,
        "source_url": f"https://arxiv.org/abs/{paper_id}",
        "categories": [category],
        "primary_category": category,
        "evidence_status": "metadata_only",
        "is_supplementary": True,
        "cannot_modify_mastery": True,
        "cannot_modify_recommendation": True,
        "cannot_modify_graph": True,
    }


# ---------------------------------------------------------------------------
# 纯函数聚合
# ---------------------------------------------------------------------------


def test_keyword_extraction_filters_stopwords():
    papers = [
        _paper("2005.00001", "Retrieval Augmented Generation for Knowledge Intensive Tasks", 2020, abstract="We propose retrieval augmented generation methods."),
        _paper("2005.00002", "Retrieval Augmented Generation in Dialogue Systems", 2021),
    ]
    trend = analyze_paper_trends(papers, top_k=5)

    terms = [item["term"] for item in trend["top_keywords"]]
    assert "retrieval" in terms
    assert "augmented" in terms
    # 停用词不入榜
    assert "the" not in terms
    assert "and" not in terms
    assert "paper" not in terms


def test_year_distribution_sorted():
    papers = [_paper(f"2005.{i:05d}", f"Title {i}", 2020 + i) for i in range(3)]
    trend = analyze_paper_trends(papers)

    years = list(trend["year_distribution"].keys())
    assert years == [str(2020 + i) for i in range(3)]
    assert trend["year_range"] == (2020, 2022)
    assert trend["papers_analyzed"] == 3


def test_trend_direction_rising_and_falling():
    early = [_paper(f"2018.{i:05d}", f"LSTM based Approach {i}", 2018) for i in range(3)]
    late = [_paper(f"2023.{i:05d}", f"Transformer based Approach {i}", 2023) for i in range(3)]
    papers = early + late

    trend = analyze_paper_trends(papers, top_k=10)

    assert trend["trend_reliability"] == "sufficient"
    by_term = {item["term"]: item for item in trend["trend_by_keyword"]}
    assert by_term["transformer"]["direction"] == "rising"
    assert by_term["lstm"]["direction"] == "falling"


def test_insufficient_sample_is_marked_and_unknown():
    papers = [_paper("2024.00001", "Single Paper About Retrieval", 2024)]
    trend = analyze_paper_trends(papers)

    assert trend["papers_analyzed"] == 1
    assert trend["trend_reliability"] == "insufficient"
    assert all(item["direction"] == "unknown" for item in trend["trend_by_keyword"])
    assert any("insufficient" in c for c in trend["caveats"])


def test_empty_input_and_source_policy():
    trend = analyze_paper_trends([])
    assert trend["papers_analyzed"] == 0
    assert trend["trend_reliability"] == "insufficient"
    assert trend["source_policy"]["is_supplementary"] is True
    assert trend["source_policy"]["cannot_modify_graph"] is True


def test_category_distribution():
    papers = [
        _paper("2005.00001", "A", 2020, category="cs.CL"),
        _paper("2005.00002", "B", 2020, category="cs.CL"),
        _paper("2005.00003", "C", 2020, category="cs.LG"),
    ]
    trend = analyze_paper_trends(papers)
    assert trend["category_distribution"]["cs.CL"] == 2
    assert trend["category_distribution"]["cs.LG"] == 1


# ---------------------------------------------------------------------------
# 工作流
# ---------------------------------------------------------------------------


def _base_state(**overrides):
    state = {
        "course_id": "1",
        "actor_user_id": "7",
        "query": "分析检索增强生成领域的前沿趋势",
        "requested_action": "trend_analysis",
        "granted_permissions": ["course.question.ask"],
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }
    state.update(overrides)
    return state


def _fakes(scope_access=None, paper_search=None, workspace=None):
    scope_access = scope_access or AsyncMock()
    scope_access.authorize.return_value = {"allowed": True}
    workspace = workspace or AsyncMock()
    workspace.get_or_create_workspace.return_value = {"workspace_id": "w1"}
    workspace.get_workspace_snapshot.return_value = {}
    paper_search = paper_search or AsyncMock()
    return ResearchTools(
        scope_access=scope_access,
        paper_search=paper_search,
        workspace=workspace,
        structured_llm=None,
    )


def test_trend_workflow_with_preset_papers():
    papers = [
        _paper("2019.00001", "LSTM Model A", 2019),
        _paper("2019.00002", "LSTM Model B", 2019),
        _paper("2024.00001", "Retrieval Augmented Generation A", 2024),
        _paper("2024.00002", "Retrieval Augmented Generation B", 2024),
        _paper("2024.00003", "Retrieval Augmented Generation C", 2024),
    ]
    graph = build_research_workflow(_fakes())

    state = asyncio.run(graph.ainvoke(_base_state(papers=[dict(p) for p in papers])))

    assert state["graph_route"] == "trend"
    assert state["status"] == "success"
    assert state["trend_result"]["papers_analyzed"] == 5
    assert "趋势分析" in state["final_answer"]
    assert state["trend_result"]["source_policy"]["is_supplementary"] is True


def test_trend_workflow_searches_when_no_papers():
    paper_search = AsyncMock()
    paper_search.search.return_value = {
        "status": "success",
        "provider": "arxiv",
        "items": [
            _paper("2022.00001", "Trend Topic Alpha", 2022),
            _paper("2022.00002", "Trend Topic Beta", 2022),
            _paper("2023.00001", "Trend Topic Gamma", 2023),
            _paper("2023.00002", "Trend Topic Delta", 2023),
        ],
        "total": 4,
    }
    graph = build_research_workflow(_fakes(paper_search=paper_search))

    state = asyncio.run(graph.ainvoke(_base_state()))

    paper_search.search.assert_awaited_once()
    assert state["trend_result"]["papers_analyzed"] == 4
    assert state["status"] == "success"


def test_trend_workflow_denied_without_permission():
    scope_access = AsyncMock()
    scope_access.authorize.side_effect = [{"allowed": True}, {"allowed": False}]
    workspace = AsyncMock()
    workspace.get_or_create_workspace.return_value = {"workspace_id": "w1"}
    workspace.get_workspace_snapshot.return_value = {}
    graph = build_research_workflow(_fakes(scope_access=scope_access, workspace=workspace))

    state = asyncio.run(graph.ainvoke(_base_state(papers=[_paper("2020.00001", "X", 2020)])))

    assert state["tool_error_code"] == "RESEARCH_TOOL_PERMISSION_DENIED"
    assert state.get("trend_result") is None


def test_api_action_enum_includes_trend_analysis():
    from app.api.v1.endpoints import research_agent

    assert "trend_analysis" in research_agent.ResearchAction.__args__
