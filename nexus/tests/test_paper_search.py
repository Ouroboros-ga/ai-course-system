import httpx
import respx

from nexus.tools.paper_search import search_arxiv_papers

_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models are based on complex recurrent networks.</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <published>2017-06-12T17:57:34-04:00</published>
    <link rel="alternate" href="http://arxiv.org/abs/1706.03762v7"/>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v7"/>
    <primary_category xmlns="http://arxiv.org/schemas/atom" term="cs.CL"/>
  </entry>
</feed>"""


async def test_arxiv_search_success():
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=_ARXIV_XML)
        )
        result = await search_arxiv_papers.ainvoke({"query": "attention transformer"})
    assert result["status"] == "success"
    assert result["is_supplementary"] is True
    item = result["items"][0]
    assert item["paper_id"] == "1706.03762v7"
    assert item["title"] == "Attention Is All You Need"
    assert item["year"] == 2017
    assert item["primary_category"] == "cs.CL"


async def test_arxiv_upstream_failure_degrades():
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(500, text="boom")
        )
        result = await search_arxiv_papers.ainvoke({"query": "llm survey"})
    assert result["status"] == "upstream_unavailable"
    assert result["error"] == "ARXIV_UNAVAILABLE"
    assert result["items"] == []


async def test_arxiv_short_query_rejected():
    result = await search_arxiv_papers.ainvoke({"query": "a"})
    assert result["status"] == "invalid_query"
