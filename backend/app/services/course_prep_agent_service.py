"""Teacher-controlled course preparation agent.

The agent has read-only course tools and one proposal-writing tool.  It never
updates outline/script rows: every follow-up instruction is persisted as a
``PatchProposal`` for a teacher decision.  Locked nodes are excluded before
the LLM sees its editable target set and are checked again before persistence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from app.common.llm_client import Message, llm_client
from app.models.course_build_model import CourseCorpusSnapshot, CorpusSnapshotStatus
from app.models.course_outline_model import CourseOutlineNode, TeachingScriptNode
from app.models.document_parse_model import DocumentBlock, EvidenceSpan, EvidenceSpanStatus


PROMPT_VERSION = "course-prep-agent/1.0"


class AgentOperation(BaseModel):
    target_kind: str = Field(pattern="^(outline|script)$")
    target_id: str
    field: str = Field(pattern="^(title|content|style)$")
    after: str = Field(min_length=1, max_length=100_000)
    reason: str = Field(min_length=1, max_length=2_000)
    downstream_impact: str = Field(default="", max_length=2_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)


class AgentPlan(BaseModel):
    summary: str = Field(min_length=1, max_length=2_000)
    operations: list[AgentOperation] = Field(min_length=1, max_length=20)


@dataclass
class CoursePrepAgentResult:
    summary: str
    operations: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    excluded_locked_targets: list[str]
    planner: str


class CoursePrepAgentService:
    """Read course facts, plan safe modifications, return proposal-ready data."""

    async def plan(
        self, session: Session, *, course_id: int, instruction: str,
    ) -> CoursePrepAgentResult:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("备课指令不能为空")

        outline = list(session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
        ).order_by(CourseOutlineNode.order_index)).all())
        scripts = list(session.exec(select(TeachingScriptNode).where(
            TeachingScriptNode.course_id == course_id,
        ).order_by(TeachingScriptNode.updated_at.desc())).all())
        if not outline:
            raise ValueError("课程尚未有初始草稿；请先完成材料解析与首次智能备课")

        locked_targets = {
            *(f"outline:{node.outline_node_id}" for node in outline if node.locked_by is not None),
            *(f"script:{node.script_node_id}" for node in scripts if node.locked_by is not None),
        }
        editable_outline = [node for node in outline if node.locked_by is None]
        editable_scripts = [node for node in scripts if node.locked_by is None]
        if not editable_outline and not editable_scripts:
            raise ValueError("课程的目录与讲稿节点均已锁定，Agent 没有可修改目标")
        evidence = self.retrieve_course_evidence(session, course_id=course_id, instruction=instruction)
        plan = await self._plan_with_llm(
            instruction=instruction,
            outline=editable_outline,
            scripts=editable_scripts,
            evidence=evidence,
        )
        planner = "llm"
        if plan is None:
            plan = self._deterministic_fallback(instruction, editable_outline, editable_scripts)
            planner = "deterministic_fallback"

        allowed_evidence_ids = {item["evidence_id"] for item in evidence if item.get("evidence_id")}
        kept: list[dict[str, Any]] = []
        excluded: list[str] = []
        for operation in plan.operations:
            key = f"{operation.target_kind}:{operation.target_id}"
            if key in locked_targets:
                excluded.append(key)
                continue
            exists = any(node.outline_node_id == operation.target_id for node in editable_outline) if operation.target_kind == "outline" else any(
                node.script_node_id == operation.target_id for node in editable_scripts
            )
            if not exists:
                continue
            kept.append({
                "target": f"{operation.target_kind}:{operation.target_id}:{operation.field}",
                "after": operation.after,
                "reason": f"{operation.reason}。下游影响：{operation.downstream_impact or '请在审核后检查关联讲稿、练习和映射。'}",
                "evidence_refs": [item for item in operation.evidence_refs if item in allowed_evidence_ids],
            })
        if not kept:
            raise ValueError("指令没有可修改的未锁定课程节点；锁定内容不会进入 Agent 修改范围")
        return CoursePrepAgentResult(
            summary=plan.summary,
            operations=kept,
            evidence=evidence,
            excluded_locked_targets=excluded,
            planner=planner,
        )

    def retrieve_course_evidence(self, session: Session, *, course_id: int, instruction: str) -> list[dict[str, Any]]:
        """Course-scoped lexical retrieval over the current corpus projection.

        This is deliberately read-only.  Confirmed EvidenceSpan IDs are used
        in proposals; blocks without a confirmed span remain visible as source
        context but cannot masquerade as formal evidence.
        """
        corpus = session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.course_id == course_id,
            CourseCorpusSnapshot.status == CorpusSnapshotStatus.READY,
        ).order_by(CourseCorpusSnapshot.created_at.desc())).first()
        stmt = select(DocumentBlock).where(DocumentBlock.course_id == course_id)
        if corpus is not None:
            stmt = stmt.where(DocumentBlock.run_id.in_(list(corpus.parse_run_ids or [])))
        terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", instruction)][:8]
        blocks = list(session.exec(stmt.order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index)).all())
        ranked = sorted(
            blocks,
            key=lambda block: sum(term in (block.text or "").lower() for term in terms),
            reverse=True,
        )[:8]
        result = []
        for block in ranked:
            span = session.exec(select(EvidenceSpan).where(
                EvidenceSpan.course_id == course_id,
                EvidenceSpan.block_id == block.block_id,
                EvidenceSpan.status == EvidenceSpanStatus.CONFIRMED,
            )).first()
            result.append({
                "block_id": block.block_id,
                "evidence_id": span.span_id if span else None,
                "page": block.page_or_slide or block.page_number,
                "text": (block.text or "")[:800],
                "confirmed": span is not None,
            })
        return result

    async def _plan_with_llm(
        self, *, instruction: str, outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode], evidence: list[dict[str, Any]],
    ) -> AgentPlan | None:
        if not self._llm_is_configured():
            return None
        payload = {
            "instruction": instruction,
            "editable_outline": [
                {"id": item.outline_node_id, "title": item.title, "type": item.node_type.value, "order": item.order_index}
                for item in outline
            ],
            "editable_scripts": [
                {"id": item.script_node_id, "outline_node_id": item.outline_node_id, "content": item.content[:3000]}
                for item in scripts
            ],
            "retrieved_course_evidence": evidence,
        }
        system = (
            "你是受控备课 Agent。只能对 editable_outline 和 editable_scripts 中的 ID 提出修改；"
            "不得生成、删除或移动节点，不得引用未提供的课程事实，不得修改任何锁定内容。"
            "返回纯 JSON，结构为 {summary, operations[]}；每项包含 target_kind, target_id, field, after, reason, downstream_impact, evidence_refs。"
            "证据只能使用已提供且 confirmed=true 的 evidence_id。"
        )
        try:
            response = await llm_client.chat([
                Message(role="system", content=system),
                Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ], temperature=0.2, response_format={"type": "json_object"})
            return AgentPlan.model_validate_json(response.content)
        except (ValidationError, json.JSONDecodeError, ValueError):
            return None
        except Exception:
            return None

    @staticmethod
    def _llm_is_configured() -> bool:
        from app.core.config import settings
        return bool((settings.LLM_API_KEY or "").strip() and (settings.LLM_MODEL_NAME or "").strip())

    @staticmethod
    def _deterministic_fallback(
        instruction: str, outline: list[CourseOutlineNode], scripts: list[TeachingScriptNode],
    ) -> AgentPlan:
        """Offline-safe proposal planner for local demos and test runs."""
        chapter_match = re.search(r"第\s*(\d+)\s*章", instruction)
        candidates = [node for node in outline if node.node_type.value in {"chapter", "section", "knowledge_point"}]
        if not candidates:
            candidates = list(outline)
        index = int(chapter_match.group(1)) - 1 if chapter_match else 0
        node = candidates[min(max(index, 0), len(candidates) - 1)]
        script = next((item for item in scripts if item.outline_node_id == node.outline_node_id), None)
        if script is not None and any(word in instruction for word in ("讲稿", "表达", "例子", "通俗", "缩短", "扩展")):
            after = script.content + "\n\n【待教师确认的备课建议】请根据本节原文证据补充一个贴近教学对象的说明。"
            operation = AgentOperation(
                target_kind="script", target_id=script.script_node_id, field="content", after=after,
                reason="根据教师自然语言指令生成讲稿调整建议", downstream_impact="可能影响本节的音频与数字人媒体，需要在接受后重新生成。",
            )
        else:
            operation = AgentOperation(
                target_kind="outline", target_id=node.outline_node_id, field="title",
                after=f"{node.title}（教学节奏调整建议）",
                reason="根据教师自然语言指令生成目录调整建议", downstream_impact="可能影响关联讲稿、练习建议和 PPT 映射，请在接受后复核。",
            )
        return AgentPlan(summary="已生成一项待教师审核的课程调整提案。", operations=[operation])


course_prep_agent_service = CoursePrepAgentService()
