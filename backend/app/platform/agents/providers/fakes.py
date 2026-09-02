"""Offline fakes used by teaching-workflow tests; no network or database access."""

from __future__ import annotations

from dataclasses import field, dataclass
from typing import Any, Mapping


@dataclass
class FakeScope:
    allowed: bool = True
    async def validate_scope(self, **_: Any) -> Mapping[str, Any]: return {"allowed": self.allowed, "reason": "fake_scope"}


@dataclass
class FakeGraph:
    concepts: list[dict[str, Any]] = field(default_factory=lambda: [{"concept_id": "binary-search", "confidence": 0.9, "name": "二分查找"}])
    async def resolve_concepts(self, **_: Any) -> list[Mapping[str, Any]]: return self.concepts
    async def get_context(self, **_: Any) -> Mapping[str, Any]: return {"graph_version": "fake-graph/1", "prerequisites": [{"concept_id": "ordered-array"}], "successors": []}


@dataclass
class FakeRetrieval:
    evidence: list[dict[str, Any]] = field(default_factory=lambda: [{"evidence_id": "ev-1", "resource_id": "ppt-1", "page_start": 12, "page_end": 13, "text": "有序区间排除 mid 后应更新边界。"}])
    async def retrieve_course_evidence(self, **_: Any) -> list[Mapping[str, Any]]: return self.evidence


@dataclass
class FakeDisciplineKnowledge:
    """R14 fake：学科参考端口。产出与真实 Port 相同的 is_supplementary 契约。"""
    references: list[dict[str, Any]] = field(default_factory=lambda: [{
        "node_id": "ds-007", "name": "二叉树", "course": "数据结构与算法",
        "node_type": "concept", "definition": "二叉树是每个节点至多有两个子树的有序树。",
        "key_points": ["前序/中序/后序/层序遍历"], "example": "",
        "source_title": "数据结构（C语言版）", "source_authors": "严蔚敏、吴伟民",
        "source_chapter": "第 5 章", "retrieval_source": "discipline_kb", "is_supplementary": True,
    }])
    async def search_discipline_knowledge(self, **_: Any) -> list[Mapping[str, Any]]: return self.references


@dataclass
class FakeStudentModeling:
    state: dict[str, Any] = field(default_factory=lambda: {"mastery_score": 0.6, "confidence": 0.8, "repeated_error_risk": 0.1, "hint_dependency": 0.1, "transfer_score": 0.6})
    weak: list[dict[str, Any]] = field(default_factory=list)
    async def get_concept_state(self, **_: Any) -> Mapping[str, Any]: return self.state
    async def get_weak_concepts(self, **_: Any) -> list[Mapping[str, Any]]: return self.weak


@dataclass
class FakeRecommendation:
    async def recommend_next_action(self, **kwargs: Any) -> Mapping[str, Any]: return {"resource_ids": ["resource-1"], "reason": kwargs["action"] + "_fake_reason"}


@dataclass
class FakeSandbox:
    async def get_execution_result(self, **_: Any) -> Mapping[str, Any]: return {"status": "not_run"}


@dataclass
class FakeEvents:
    events: list[dict[str, Any]] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    async def record_learning_event(self, *, event: Mapping[str, Any]) -> None: self.events.append(dict(event))
    async def record_agent_trace(self, *, trace: Mapping[str, Any]) -> None: self.traces.append(dict(trace))


@dataclass
class FakeLLM:
    fail: bool = False
    async def detect_intent(self, **_: Any) -> Mapping[str, Any]:
        if self.fail: raise RuntimeError("fake llm unavailable")
        return {"intent": "concept_question", "confidence": 0.9}
    async def extract_concept_candidates(self, **_: Any) -> list[Mapping[str, Any]]:
        if self.fail: raise RuntimeError("fake llm unavailable")
        return [{"name": "二分查找", "confidence": 0.9}]
    async def generate_teaching_response(self, *, context: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.fail: raise RuntimeError("fake llm unavailable")
        citations = [{"evidence_id": item["evidence_id"], "resource_id": item.get("resource_id"), "page_start": item.get("page_start"), "page_end": item.get("page_end")} for item in context.get("retrieved_evidence", [])]
        return {"answer": "这是基于当前课程证据的教学说明。", "citations": citations}
