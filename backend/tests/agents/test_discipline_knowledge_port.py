"""R14：学科垂类知识库接入 TeachingAgent 的离线契约测试。

覆盖：
- 真实 Provider 检索（is_supplementary 契约、无 evidence_id、空消息短路）；
- 组合根默认注入 + 设置开关关闭时缺省；
- respond 端点把 discipline_references 透出且与 citations 分离。
"""
from __future__ import annotations

import asyncio
import importlib.util
import unittest
from pathlib import Path
from typing import Any

from app.platform.agents.providers.retrieval.discipline_kb import DisciplineKnowledgePortImpl
from app.platform.agents.edu.composition import _discipline_knowledge_port


_ENDPOINT = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "endpoints" / "teaching_agent.py"
_SPEC = importlib.util.spec_from_file_location("teaching_agent_endpoint_discipline_test", _ENDPOINT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class DisciplineKnowledgePortImplTest(unittest.TestCase):
    def setUp(self):
        self.port = DisciplineKnowledgePortImpl()

    def test_search_returns_supplementary_references_without_evidence_id(self):
        refs = asyncio.run(self.port.search_discipline_knowledge(
            course_id="1", message="什么是二叉树", concept_id=None, top_k=2,
        ))
        self.assertGreaterEqual(len(refs), 1)
        first = refs[0]
        self.assertTrue(first["is_supplementary"])
        self.assertEqual(first["retrieval_source"], "discipline_kb")
        self.assertNotIn("evidence_id", first)
        self.assertTrue(first["name"])
        self.assertTrue(first["source_title"])

    def test_search_hits_real_kb_node(self):
        refs = asyncio.run(self.port.search_discipline_knowledge(
            course_id="1", message="哈希冲突怎么处理", concept_id=None, top_k=3,
        ))
        names = {ref["name"] for ref in refs}
        self.assertIn("哈希表", names)

    def test_empty_message_returns_no_references(self):
        refs = asyncio.run(self.port.search_discipline_knowledge(
            course_id="1", message="   ", concept_id=None, top_k=3,
        ))
        self.assertEqual(refs, [])


class CompositionWiringTest(unittest.TestCase):
    def test_composition_root_instantiates_real_discipline_port_by_default(self):
        port = _discipline_knowledge_port()
        self.assertIsInstance(port, DisciplineKnowledgePortImpl)
        # 真实 Provider 一次检索即可命中本地知识库（无外部依赖）。
        refs = asyncio.run(port.search_discipline_knowledge(
            course_id="1", message="什么是哈希表", concept_id=None, top_k=2,
        ))
        self.assertTrue(refs)

    def test_settings_flag_off_disables_port(self):
        from app.core.config import settings
        original = getattr(settings, "TEACHING_AGENT_DISCIPLINE_KB_ENABLED", True)
        settings.TEACHING_AGENT_DISCIPLINE_KB_ENABLED = False
        try:
            self.assertIsNone(_discipline_knowledge_port())
        finally:
            settings.TEACHING_AGENT_DISCIPLINE_KB_ENABLED = original


class RespondEndpointDisciplineProjectionTest(unittest.TestCase):
    def test_response_exposes_discipline_references_separate_from_citations(self):
        import asyncio as _asyncio

        class StubRuntime:
            async def respond(self, **kwargs: Any):
                return {
                    "trace_id": "trace-1", "status": "ok", "intent": "concept_question",
                    "concept_candidates": [], "current_concept_id": None,
                    "teaching_action": "normal_answer", "final_answer": "讲解内容",
                    "citations": [{"evidence_id": "ev-1"}],
                    "discipline_kb_results": [{
                        "node_id": "ds-007", "name": "二叉树", "course": "数据结构与算法",
                        "definition": "…", "key_points": ["…"], "example": "",
                        "source_title": "数据结构（C语言版）", "source_authors": "严蔚敏、吴伟民",
                        "source_chapter": "第 5 章", "retrieval_source": "discipline_kb",
                        "is_supplementary": True,
                    }],
                    "selected_resource_ids": [], "warnings": [], "degraded_services": [],
                    "learning_adjustment": None, "inquiry_depth": None,
                }

        response = _asyncio.run(_MODULE._respond_for_subject(
            subject_user_id=1, course_id=1, session_id="s", message="什么是二叉树",
            resource_id=None, exercise_id=None, code_submission_id=None,
            question_observation=None, persist_learner_turn=False,
            runtime_source=StubRuntime(), session=None,
        ))
        refs = response["discipline_references"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["name"], "二叉树")
        self.assertTrue(refs[0]["is_supplementary"])
        self.assertEqual(refs[0]["source_title"], "数据结构（C语言版）")
        self.assertNotIn("evidence_id", refs[0])
        self.assertEqual(response["citations"], [{"evidence_id": "ev-1"}])
        self.assertEqual(response["status"], "ok")


if __name__ == "__main__":
    unittest.main()
