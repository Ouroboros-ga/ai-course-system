"""Smoke: default flag leaves V1 retrieval untouched (no regression)."""
from __future__ import annotations
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.qa_service import QAService


def test_default_flag_v1_only_keeps_v1_retrieval():
    svc = QAService.__new__(QAService)
    svc.prompt_builder = MagicMock()
    svc.prompt_builder.build_context_aware_prompt.return_value = ("sys", "user")
    svc.retrieve_rag_context = lambda *a, **k: ("ctx", [{"path": "p", "score": 0.5, "match_type": "tree_keyword", "content_preview": "t"}])
    with patch("app.services.qa_service.LLMAdapter") as LA, patch("app.services.qa_service.Message"):
        LA.return_value.chat = AsyncMock(return_value=MagicMock(success=True, data=MagicMock(content="answer")))
        res = asyncio.run(svc.ask_question_with_rag(question="q", course_id="101"))
    assert res["retrieval_source"] == "v1_treerag"
    assert res["rag_sources"] is not None
