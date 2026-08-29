"""论文前沿趋势分析（ResearchAgent trend_analysis 工具核心，挑战杯 XH-202620）。

对论文**元数据**做确定性聚合（无 LLM、无外部依赖）：
- 热点关键词频次（标题 + 摘要，英文词元，过滤停用词）
- 年份分布（论文数按年统计）
- 关键词趋势方向（以年份中位数为界，比较前后半段出现次数：rising/falling/stable）
- arXiv 主题分类分布

诚实边界：仅基于元数据；样本量小（<4 篇或年份不足 2 个）时明确标记
``trend_reliability: insufficient``，不做武断结论；结果一律携带
``source_policy``（补充参考，不可改掌握度/推荐/图谱）。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

_WORD_RE = re.compile(r"[a-z][a-z0-9-]{2,}")

# 通用英文停用词 + 计算机学科高频无信息量词
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "are", "was", "that", "this", "these", "those",
    "from", "into", "over", "under", "using", "based", "study", "studies", "paper",
    "papers", "method", "methods", "approach", "approaches", "model", "models",
    "system", "systems", "result", "results", "data", "learning", "deep",
    "neural", "network", "networks", "novel", "new", "large", "improve", "improved",
    "show", "shows", "shown", "present", "presented", "propose", "proposed",
    "achieve", "achieves", "performance", "task", "tasks", "problem", "problems",
    "use", "used", "via", "across", "among", "such", "also", "can", "may", "well",
})

MIN_PAPERS_FOR_TREND = 4
MIN_DISTINCT_YEARS = 2


def _keyword_counts(papers: list[Mapping[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for paper in papers:
        text = f"{paper.get('title') or ''} {paper.get('abstract') or ''}".casefold()
        for token in _WORD_RE.findall(text):
            if token not in _STOPWORDS:
                counter[token] += 1
    return counter


def _year_range(papers: list[Mapping[str, Any]]) -> tuple[int, int] | None:
    years = [int(p["year"]) for p in papers if p.get("year")]
    if not years:
        return None
    return min(years), max(years)


def analyze_paper_trends(
    papers: list[Mapping[str, Any]],
    *,
    top_k: int = 12,
) -> dict[str, Any]:
    """生成论文元数据趋势分析报告（纯函数、确定性）。"""
    analyzed = [p for p in papers if p.get("title")]
    years = [int(p["year"]) for p in analyzed if p.get("year")]
    year_range = _year_range(analyzed)
    distinct_years = len(set(years))

    top_keywords: list[dict[str, Any]] = []
    trend_by_keyword: list[dict[str, Any]] = []
    reliability = (
        "sufficient"
        if len(analyzed) >= MIN_PAPERS_FOR_TREND and distinct_years >= MIN_DISTINCT_YEARS
        else "insufficient"
    )

    if analyzed and year_range:
        min_year, max_year = year_range
        median_year = (min_year + max_year) / 2.0
        first_half = [p for p in analyzed if (p.get("year") or 0) <= median_year]
        second_half = [p for p in analyzed if (p.get("year") or 0) > median_year]
        counts = _keyword_counts(analyzed)
        top_keywords = [
            {"term": term, "count": count}
            for term, count in counts.most_common(top_k)
        ]
        first_counts = _keyword_counts(first_half)
        second_counts = _keyword_counts(second_half)
        for item in top_keywords:
            term = item["term"]
            f_count = first_counts.get(term, 0)
            s_count = second_counts.get(term, 0)
            if reliability == "sufficient":
                direction = "rising" if s_count > f_count else ("falling" if f_count > s_count else "stable")
            else:
                direction = "unknown"
            trend_by_keyword.append({
                "term": term,
                "count": item["count"],
                "first_half_count": f_count,
                "second_half_count": s_count,
                "direction": direction,
            })

    year_distribution = {
        str(year): count for year, count in sorted(Counter(years).items())
    }

    categories: Counter = Counter()
    for paper in analyzed:
        category = paper.get("primary_category") or (paper.get("categories") or [None])[0]
        if category:
            categories[category] += 1
    category_distribution = {
        category: count for category, count in categories.most_common(10)
    }

    return {
        "papers_analyzed": len(analyzed),
        "year_range": year_range,
        "year_distribution": year_distribution,
        "top_keywords": top_keywords,
        "trend_by_keyword": trend_by_keyword,
        "category_distribution": category_distribution,
        "trend_reliability": reliability,
        "caveats": [
            "仅基于论文元数据（标题/摘要/年份/分类），非全文分析",
            "样本量不足或年份过少时 trend_reliability=insufficient，不做武断趋势结论",
        ],
        "source_policy": {
            "is_supplementary": True,
            "cannot_modify_mastery": True,
            "cannot_modify_recommendation": True,
            "cannot_modify_graph": True,
        },
    }
