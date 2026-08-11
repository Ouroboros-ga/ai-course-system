"""Teacher-controlled course preparation agent.

The agent has read-only course tools and a proposal-writing planning surface.
Single-node follow-up instructions remain ``PatchProposal`` changes for a
teacher decision; the separate batch endpoint may atomically apply an explicit
teacher-authorized whole-course pass. Locked nodes are excluded before the LLM
sees its editable target set and are checked again before persistence.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import or_
from sqlmodel import Session, select

from app.common.llm_client import Message, llm_client
from app.core.config import settings
from app.models.course_build_model import CourseCorpusSnapshot, CorpusSnapshotStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.document_parse_model import DocumentBlock, EvidenceSpan, EvidenceSpanStatus
from app.platform.agents.prep.actions import (
    PrepAction,
    PrepIntent,
    PrepIntentDecision,
    canonical_prep_action,
    prep_intent_from_decision,
)
from app.platform.agents.contracts.llm import StructuredOutputError
from app.platform.agents.shared.error_messages import safe_prep_error_message


PROMPT_VERSION = "course-prep-agent/2.0"
logger = logging.getLogger(__name__)

# 合法的 style 取值（与 TeachingScriptNode.style 字段对齐）
_VALID_STYLE_VALUES = ("beginner", "academic", "concise")
# 单次 LLM 调用的最大重试次数（首次 + 修复重试）
_LLM_MAX_RETRIES = 1
BatchAction = Literal["organize_structure", "optimize_scripts", "optimize_all_scripts"]
# A batch is one course-level editorial pass.  The response still has a hard
# ceiling so an unexpectedly huge course fails closed instead of truncating.
_BATCH_MAX_TARGETS = 500
_BATCH_MAX_INPUT_CHARS = 120_000
# An outline operation emits a short title plus JSON metadata, while a script
# operation must carry the rewritten sentence(s).  A single 1,200-character
# reserve for both made normal 40–60-node courses fail before the model saw
# their full context.  Keep action-specific reserves so we still fail closed
# for genuinely oversized responses without rejecting ordinary courses.
_BATCH_TITLE_OUTPUT_OVERHEAD = 280
_BATCH_SCRIPT_OUTPUT_OVERHEAD = 680
_TITLE_REQUEST_TERMS = ("标题", "题目", "命名", "名称")
_CONTENT_REQUEST_TERMS = (
    "知识覆盖", "知识点", "讲稿", "内容", "表达", "例子", "通俗", "缩短", "扩展",
)
_TITLE_NOUN_SUFFIXES = (
    "系统", "机构", "装置", "总成", "组件", "发动机", "电机", "机器", "设备", "机", "器",
)
_TITLE_CONTEXT_STOP_WORDS = {
    "作用", "功能", "用途", "保证", "实现", "通常", "主要", "原理", "结构", "形状",
    "检查", "调整", "正时", "点火", "喷油", "做功行程", "转动惯量",
}


class AgentOperation(BaseModel):
    target_kind: str = Field(pattern="^(outline|script)$")
    target_id: str
    # ``replace`` is the legacy/default shape.  Structure organisation may
    # also move, reorder or remove an existing unlocked outline node.
    operation: Literal["replace", "move", "reorder", "remove"] = "replace"
    field: str = Field(default="", pattern="^(|title|content|style|structure)$")
    after: str = Field(default="", max_length=100_000)
    parent_node_id: str | None = Field(default=None, max_length=128)
    order_index: int | None = Field(default=None, ge=0, le=10_000)
    reason: str = Field(min_length=1, max_length=2_000)
    downstream_impact: str = Field(default="", max_length=2_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)


class AgentPlan(BaseModel):
    summary: str = Field(min_length=1, max_length=2_000)
    # A reliable structure pass is allowed to find no safe change.  Callers
    # that promise a selected-node or all-script rewrite enforce their own
    # coverage requirement after target validation.
    operations: list[AgentOperation] = Field(default_factory=list, max_length=_BATCH_MAX_TARGETS)


class StructureTitleOperation(BaseModel):
    """Minimal title edit: the server owns all audit metadata."""

    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)


class StructureMoveOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=128)
    operation: Literal["move"]
    new_parent_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_shape(self) -> "StructureMoveOperation":
        if self.new_parent_id == self.node_id:
            raise ValueError("move cannot target itself")
        return self


class StructureReorderOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=128)
    operation: Literal["reorder"]
    new_order: int | None = Field(default=None, ge=0, le=10_000)

    @model_validator(mode="after")
    def validate_shape(self) -> "StructureReorderOperation":
        if self.new_order is None:
            raise ValueError("reorder requires new_order")
        return self


class StructureRemoveOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=128)
    operation: Literal["remove"]


StructurePlanOperation = Union[
    StructureTitleOperation,
    StructureMoveOperation,
    StructureReorderOperation,
    StructureRemoveOperation,
]


class StructurePlan(BaseModel):
    # This is a dedicated model-facing contract.  Reject root-level prose or
    # legacy AgentPlan fields as well as extra fields in individual operations.
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=2_000)
    operations: list[StructurePlanOperation] = Field(default_factory=list, max_length=_BATCH_MAX_TARGETS)


@dataclass
class CoursePrepAgentResult:
    summary: str
    operations: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    excluded_locked_targets: list[str]
    planner: str


class CoursePrepAgentPlanningError(RuntimeError):
    """The configured LLM failed to return a safe, valid preparation plan."""


class CoursePrepAgentIntentRoutingError(CoursePrepAgentPlanningError):
    """The structured free-text intent router could not produce a decision."""

    error_code = "PREP_AGENT_INTENT_UNAVAILABLE"


class CoursePrepAgentService:
    """Read course facts, plan safe modifications, return proposal-ready data."""

    def __init__(self, *, llm: Any | None = None, course_retrieval: Any | None = None) -> None:
        """Allow injecting an LLM client (constructor接缝 for PrepLLMAdapter).

        When ``llm`` is ``None``, the service uses the module-level
        ``llm_client`` singleton (backward compatible). When an object
        with a ``chat()`` method is injected, ``_plan_with_llm`` calls
        ``self._llm.chat(...)`` instead of ``llm_client.chat(...)``.
        """
        self._llm = llm
        # Optional course-scoped vector retrieval dependency.  The lexical
        # evidence projection remains available as a deterministic fallback
        # when a course has not activated a knowledge bundle yet.
        self._course_retrieval = course_retrieval

    async def classify_intent(
        self,
        session: Session,
        *,
        course_id: int,
        instruction: str,
        outline_node_id: str | None = None,
    ) -> PrepIntent:
        """Classify free text using the configured structured Prep model.

        Only a bounded node summary and the allowed action descriptions are
        exposed to this call.  It cannot retrieve evidence or mutate a draft;
        the returned decision is still gated by ``prep_intent_from_decision``.
        """
        text = (instruction or "").strip()
        if not text:
            return PrepIntent(
                action=None,
                instruction=text,
                needs_clarification=True,
                clarification="请说明希望执行的备课操作和范围。",
            )

        outline, scripts = self._load_latest_draft_targets(
            session,
            course_id=course_id,
        )
        selected = None
        if outline_node_id:
            selected = next(
                (node for node in outline if node.outline_node_id == outline_node_id),
                None,
            )
            if selected is None:
                raise ValueError("选中的课程节点不属于当前最新草稿，请刷新后重试")
        selected_scripts = (
            [node for node in scripts if node.outline_node_id == outline_node_id]
            if selected is not None
            else []
        )
        payload = {
            "instruction": text,
            "selected_node": (
                {
                    "outline_node_id": selected.outline_node_id,
                    "title": selected.title or "",
                    "has_script": bool(selected_scripts),
                }
                if selected is not None
                else None
            ),
            "allowed_actions": [
                {
                    "action": PrepAction.OPTIMIZE_NODE_TITLE.value,
                    "scope": "当前选中课程节点标题",
                },
                {
                    "action": PrepAction.ORGANIZE_STRUCTURE.value,
                    "scope": "全课程未锁定目录/节点结构",
                },
                {
                    "action": PrepAction.OPTIMIZE_NODE_SCRIPT.value,
                    "scope": "当前选中课程节点讲解脚本",
                },
                {
                    "action": PrepAction.OPTIMIZE_ALL_SCRIPTS.value,
                    "scope": "全课程未锁定讲解脚本",
                },
                {
                    "action": PrepAction.MATCH_PPT.value,
                    "scope": "课程节点与 PPT 页面映射",
                },
            ],
        }
        if self._llm is None or not hasattr(self._llm, "classify_intent"):
            raise CoursePrepAgentIntentRoutingError("备课意图模型不可用，未执行任何操作")
        try:
            decision = await self._llm.classify_intent(payload)
            if not isinstance(decision, PrepIntentDecision):
                decision = PrepIntentDecision.model_validate(decision)
        except StructuredOutputError as exc:
            logger.warning(
                "Course prep intent routing failed schema validation: %s: %s",
                type(exc).__name__, str(exc)[:300],
            )
            error = CoursePrepAgentIntentRoutingError(
                "备课意图模型返回无效结果，未执行任何操作"
            )
            error.reason_code = getattr(exc, "reason_code", "")
            error.stage = getattr(exc, "stage", "intent_routing")
            error.attempts = getattr(exc, "attempts", 0)
            raise error from exc
        except Exception as exc:
            logger.warning(
                "Course prep intent routing unavailable: %s: %s",
                type(exc).__name__, str(exc)[:300],
            )
            raise CoursePrepAgentIntentRoutingError(
                "备课意图模型服务不可用，未执行任何操作"
            ) from exc
        return prep_intent_from_decision(
            text,
            selected_outline_node_id=outline_node_id,
            decision=decision,
        )

    async def plan(
        self,
        session: Session,
        *,
        course_id: int,
        instruction: str,
        outline_node_id: str | None = None,
    ) -> CoursePrepAgentResult:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("备课指令不能为空")

        outline_version = session.exec(
            select(CourseOutlineVersion).where(
                CourseOutlineVersion.course_id == course_id,
                CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
            ).order_by(CourseOutlineVersion.version.desc())
        ).first()
        if outline_version is None:
            raise ValueError("课程尚未有初始草稿；请先完成材料解析与首次智能备课")
        outline = list(session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_version_id == outline_version.outline_version_id,
        ).order_by(CourseOutlineNode.order_index)).all())
        script_version = session.exec(
            select(TeachingScriptVersion).where(
                TeachingScriptVersion.course_id == course_id,
                TeachingScriptVersion.outline_version_id == outline_version.outline_version_id,
                TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
            ).order_by(TeachingScriptVersion.version.desc())
        ).first()
        scripts = [] if script_version is None else list(session.exec(
            select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_version_id == script_version.script_version_id,
            ).order_by(TeachingScriptNode.updated_at.desc())
        ).all())
        if not outline:
            raise ValueError("课程尚未有初始草稿；请先完成材料解析与首次智能备课")

        if outline_node_id:
            selected_outline = next(
                (node for node in outline if node.outline_node_id == outline_node_id),
                None,
            )
            if selected_outline is None:
                raise ValueError("选中的课程节点不属于当前最新草稿，请刷新后重试")
            outline = [selected_outline]
            scripts = [
                node for node in scripts
                if node.outline_node_id == outline_node_id
            ]

        locked_targets = {
            *(f"outline:{node.outline_node_id}" for node in outline if node.locked_by is not None),
            *(f"script:{node.script_node_id}" for node in scripts if node.locked_by is not None),
        }
        editable_outline = [node for node in outline if node.locked_by is None]
        editable_scripts = [node for node in scripts if node.locked_by is None]
        if not editable_outline and not editable_scripts:
            raise ValueError("课程的目录与讲稿节点均已锁定，Agent 没有可修改目标")
        evidence = self.retrieve_course_evidence(session, course_id=course_id, instruction=instruction)
        planner = "llm"
        try:
            plan = await self._plan_with_llm(
                instruction=instruction,
                outline=editable_outline,
                scripts=editable_scripts,
                evidence=evidence,
            )
        except (CoursePrepAgentPlanningError, StructuredOutputError) as exc:
            # A single-node incremental proposal has a safe, reviewable local
            # fallback.  Do not turn a transient provider/schema failure into
            # a user-visible 500 when the requested edit can be derived from
            # the draft itself.
            logger.warning(
                "Course prep LLM failed; using deterministic fallback: %s: %s",
                type(exc).__name__, str(exc)[:500],
            )
            plan = None
        if plan is None:
            plan = self._deterministic_fallback(instruction, editable_outline, editable_scripts)
            planner = "deterministic_fallback"
        else:
            plan = self._guard_title_plan(
                plan,
                instruction=instruction,
                outline=editable_outline,
                scripts=editable_scripts,
            )

        allowed_evidence_ids = {item["evidence_id"] for item in evidence if item.get("evidence_id")}
        kept, excluded, discarded_invalid_or_noop = self._filter_operations(
            plan=plan,
            editable_outline=editable_outline,
            editable_scripts=editable_scripts,
            locked_targets=locked_targets,
            allowed_evidence_ids=allowed_evidence_ids,
        )
        if not kept:
            if discarded_invalid_or_noop:
                raise ValueError("模型没有产生可应用的实质性修改，请补充更明确的调整要求后重试")
            raise ValueError("指令没有可修改的未锁定课程节点；锁定内容不会进入 Agent 修改范围")
        return CoursePrepAgentResult(
            summary=plan.summary,
            operations=kept,
            evidence=evidence,
            excluded_locked_targets=excluded,
            planner=planner,
        )

    async def plan_action(
        self,
        session: Session,
        *,
        course_id: int,
        action: PrepAction | str,
        instruction: str = "",
        outline_node_id: str | None = None,
    ) -> CoursePrepAgentResult:
        """Plan exactly one canonical preparation capability.

        This is the only planning entry used by new button and chat flows.
        It deliberately does not fall back to guessed content: an unavailable
        or invalid model result fails closed, leaving the draft unchanged.
        """
        resolved_action = canonical_prep_action(action)
        if resolved_action is None or resolved_action == PrepAction.MATCH_PPT:
            raise ValueError("该动作不属于讲解/课程结构规划链路")
        # Title cleanup has a deterministic, source-backed fallback.  Keep
        # that capability usable when the model is unavailable or returns an
        # unsafe title; the broader structure/script actions remain fail-closed.
        if resolved_action != PrepAction.OPTIMIZE_NODE_TITLE and not self._llm_is_configured():
            raise CoursePrepAgentPlanningError("助教模型未配置，未生成任何修改")

        outline, scripts = self._load_latest_draft_targets(session, course_id=course_id)
        instruction = instruction.strip() or self._default_action_instruction(resolved_action)
        editable_outline = [node for node in outline if node.locked_by is None]
        editable_scripts = [node for node in scripts if node.locked_by is None]
        locked_targets = {
            *(f"outline:{node.outline_node_id}" for node in outline if node.locked_by is not None),
            *(f"script:{node.script_node_id}" for node in scripts if node.locked_by is not None),
        }

        if resolved_action == PrepAction.OPTIMIZE_NODE_TITLE:
            selected = self._selected_outline_node(outline, outline_node_id)
            if selected.locked_by is not None:
                raise ValueError("当前课程节点已被教师锁定，不能由助教优化标题")
            title_scripts = [
                script for script in scripts
                if script.outline_node_id == selected.outline_node_id
            ]
            evidence = await self.retrieve_action_evidence(
                session,
                course_id=course_id,
                instruction=f"{selected.title}\n{instruction}",
                concept_id=selected.knowledge_graph_node_id,
            )
            title_source = "\n".join(
                part for part in (
                    instruction,
                    selected.title or "",
                    *(script.content or "" for script in title_scripts),
                    *(str(item.get("text") or "") for item in evidence),
                ) if part
            )
            fallback_title = self._build_title_suggestion(selected, title_source)

            try:
                plan = await self._required_llm_plan(
                    action=resolved_action,
                    instruction=instruction,
                    outline=[selected],
                    scripts=[],
                    evidence=evidence,
                    course_outline_context=editable_outline,
                    course_script_context=title_scripts,
                )
            except CoursePrepAgentPlanningError as exc:
                logger.warning(
                    "Course prep title plan failed; using source-backed fallback: %s: %s",
                    type(exc).__name__, str(exc)[:300],
                )
                return self._title_fallback_result(
                    selected=selected,
                    title=fallback_title,
                    evidence=evidence,
                    reason="模型标题提案未通过校验，已依据当前节点原文生成安全标题",
                )

            operations, excluded, discarded = self._filter_operations(
                plan=plan,
                editable_outline=[selected],
                editable_scripts=[],
                locked_targets=locked_targets,
                allowed_evidence_ids={item["evidence_id"] for item in evidence if item.get("evidence_id")},
            )
            operations = [item for item in operations if item["target"] == f"outline:{selected.outline_node_id}:title"]
            if discarded or len(operations) != 1 or not self._safe_title(operations[0]["after"], selected, evidence):
                return self._title_fallback_result(
                    selected=selected,
                    title=fallback_title,
                    evidence=evidence,
                    reason="模型标题提案未通过安全校验，已依据当前节点原文生成安全标题",
                )
            return CoursePrepAgentResult(
                summary=plan.summary,
                operations=operations,
                evidence=evidence,
                excluded_locked_targets=excluded,
                planner="llm_node_title",
            )

        if resolved_action == PrepAction.OPTIMIZE_NODE_SCRIPT:
            selected = self._selected_outline_node(outline, outline_node_id)
            target_scripts = [
                script for script in editable_scripts
                if script.outline_node_id == selected.outline_node_id
            ]
            if not target_scripts:
                raise ValueError("当前节点没有可优化的未锁定讲解脚本")
            evidence = await self.retrieve_action_evidence(
                session,
                course_id=course_id,
                instruction=f"{selected.title}\n{instruction}",
                concept_id=selected.knowledge_graph_node_id,
            )
            plan = await self._required_llm_plan(
                action=resolved_action,
                instruction=instruction,
                outline=[],
                scripts=target_scripts,
                evidence=evidence,
                course_outline_context=editable_outline,
                course_script_context=target_scripts,
            )
            operations, excluded, discarded = self._filter_operations(
                plan=plan,
                editable_outline=[],
                editable_scripts=target_scripts,
                locked_targets=locked_targets,
                allowed_evidence_ids={item["evidence_id"] for item in evidence if item.get("evidence_id")},
            )
            expected = {script.script_node_id for script in target_scripts}
            covered = {
                op.target_id for op in plan.operations
                if op.target_kind == "script" and op.field == "content"
                and op.target_id in expected
            }
            if discarded or covered != expected:
                raise CoursePrepAgentPlanningError("模型未完整返回当前节点的讲解脚本优化，草稿未修改")
            return CoursePrepAgentResult(plan.summary, operations, evidence, excluded, "llm_node_script")

        if resolved_action == PrepAction.OPTIMIZE_ALL_SCRIPTS:
            return await self._plan_all_scripts(
                session,
                course_id=course_id,
                instruction=instruction,
                outline=outline,
                editable_scripts=editable_scripts,
                locked_targets=locked_targets,
            )

        if not editable_outline:
            raise ValueError("当前草稿没有可整理的未锁定课程节点")
        evidence = await self.retrieve_action_evidence(session, course_id=course_id, instruction=instruction)
        plan = await self._required_llm_plan(
            action=resolved_action,
            instruction=instruction,
            outline=editable_outline,
            scripts=[],
            evidence=evidence,
            course_outline_context=editable_outline,
            course_script_context=[],
        )
        operations, excluded = self._filter_structure_operations(
            plan=plan,
            outline=outline,
            scripts=scripts,
            allowed_evidence_ids={item["evidence_id"] for item in evidence if item.get("evidence_id")},
        )
        return CoursePrepAgentResult(
            plan.summary,
            operations,
            evidence,
            sorted({
                *excluded,
                *(f"outline:{node.outline_node_id}" for node in outline if node.locked_by is not None),
            }),
            "llm_structure",
        )

    @staticmethod
    def _default_action_instruction(action: PrepAction) -> str:
        return {
            PrepAction.OPTIMIZE_NODE_TITLE: "优化当前课程节点标题，纠正 OCR 片段和不准确用词，使标题准确概括本节点知识。",
            PrepAction.ORGANIZE_STRUCTURE: "整理全部未锁定课程节点：修正标题、删除冗余节点、调整父子关系与先后顺序；不得触碰锁定节点。",
            PrepAction.OPTIMIZE_NODE_SCRIPT: "根据课程原文证据、课程标题和现有讲解脚本，优化当前节点的讲解。",
            PrepAction.OPTIMIZE_ALL_SCRIPTS: "分批优化全部未锁定讲解脚本，使表达连贯、准确且适合教学讲解。",
        }[action]

    @staticmethod
    def _selected_outline_node(
        outline: list[CourseOutlineNode],
        outline_node_id: str | None,
    ) -> CourseOutlineNode:
        if not outline_node_id:
            raise ValueError("请选择要优化的课程节点")
        selected = next((node for node in outline if node.outline_node_id == outline_node_id), None)
        if selected is None:
            raise ValueError("选中的课程节点不属于当前最新草稿，请刷新后重试")
        return selected

    async def _required_llm_plan(
        self,
        *,
        action: PrepAction,
        instruction: str,
        outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode],
        evidence: list[dict[str, Any]],
        course_outline_context: list[CourseOutlineNode],
        course_script_context: list[TeachingScriptNode],
        ) -> AgentPlan:
        try:
            plan = await self._plan_with_llm(
                instruction=instruction,
                outline=outline,
                scripts=scripts,
                evidence=evidence,
                batch_action=action.value,
                course_outline_context=course_outline_context,
                course_script_context=course_script_context,
                structure_mode=action == PrepAction.ORGANIZE_STRUCTURE,
            )
        except StructuredOutputError as exc:
            # Keep the structured provider metadata in the exception chain,
            # while giving legacy/direct callers the same safe Prep message.
            planning_error = CoursePrepAgentPlanningError(
                safe_prep_error_message(exc),
            )
            planning_error.reason_code = getattr(exc, "reason_code", "")
            planning_error.stage = getattr(exc, "stage", "")
            planning_error.validation_errors = getattr(exc, "validation_errors", [])
            planning_error.attempts = getattr(exc, "attempts", 0)
            planning_error.schema_name = getattr(exc, "schema_name", "")
            planning_error.finish_reason = getattr(exc, "finish_reason", "")
            planning_error.truncated = getattr(exc, "truncated", False)
            raise planning_error from exc
        if plan is None:
            raise CoursePrepAgentPlanningError("助教模型不可用，草稿未修改")
        if isinstance(plan, StructurePlan):
            return self._structure_plan_to_agent_plan(plan)
        return plan

    @staticmethod
    def _structure_plan_to_agent_plan(plan: StructurePlan) -> AgentPlan:
        """Fill audit-only PatchProposal fields after compact LLM planning."""
        mapped_operations: list[AgentOperation] = []
        for item in plan.operations:
            if isinstance(item, StructureTitleOperation):
                mapped_operations.append(AgentOperation(
                    target_kind="outline", target_id=item.node_id,
                    operation="replace", field="title", after=item.title,
                    reason="结构整理：标题去除序号、图号或冗余表述",
                    evidence_refs=[],
                ))
            elif isinstance(item, StructureMoveOperation):
                mapped_operations.append(AgentOperation(
                    target_kind="outline", target_id=item.node_id,
                    operation="move", field="structure",
                    after=json.dumps({"parent_node_id": item.new_parent_id}, ensure_ascii=False),
                    parent_node_id=item.new_parent_id,
                    reason="结构整理：调整父子层级",
                    evidence_refs=[],
                ))
            elif isinstance(item, StructureReorderOperation):
                mapped_operations.append(AgentOperation(
                    target_kind="outline", target_id=item.node_id,
                    operation="reorder", field="structure",
                    after=json.dumps({"order_index": item.new_order}, ensure_ascii=False),
                    order_index=item.new_order,
                    reason="结构整理：调整教学顺序",
                    evidence_refs=[],
                ))
            elif isinstance(item, StructureRemoveOperation):
                mapped_operations.append(AgentOperation(
                    target_kind="outline", target_id=item.node_id,
                    operation="remove", field="structure", after="",
                    reason="结构整理：移除冗余节点",
                    evidence_refs=[],
                ))
        return AgentPlan(summary=plan.summary, operations=mapped_operations)

    @staticmethod
    def _agent_plan_to_structure_plan(plan: AgentPlan) -> StructurePlan:
        """Compatibility mapping for injected legacy planner implementations."""
        compact_operations: list[StructurePlanOperation] = []
        for item in plan.operations:
            if item.operation == "replace" and item.field == "title":
                compact_operations.append(StructureTitleOperation(
                    node_id=item.target_id, title=item.after,
                ))
            elif item.operation == "move":
                compact_operations.append(StructureMoveOperation(
                    node_id=item.target_id, operation="move", new_parent_id=item.parent_node_id,
                ))
            elif item.operation == "reorder":
                compact_operations.append(StructureReorderOperation(
                    node_id=item.target_id, operation="reorder", new_order=item.order_index,
                ))
            elif item.operation == "remove":
                compact_operations.append(StructureRemoveOperation(
                    node_id=item.target_id, operation="remove",
                ))
        return StructurePlan(summary=plan.summary, operations=compact_operations)

    async def _plan_all_scripts(
        self,
        session: Session,
        *,
        course_id: int,
        instruction: str,
        outline: list[CourseOutlineNode],
        editable_scripts: list[TeachingScriptNode],
        locked_targets: set[str],
    ) -> CoursePrepAgentResult:
        if not editable_scripts:
            raise ValueError("当前草稿没有可优化的未锁定讲解脚本")
        # Keep each request bounded and let the dedicated script budget cap
        # the rewritten text. The previous path inherited the global 8192
        # budget and allowed hidden reasoning to consume it before JSON was
        # emitted. The default five-node grouping remains compatible with the
        # existing audit path; the provider now disables reasoning and uses a
        # dedicated 4096-token completion budget.
        batch_size = max(1, int(getattr(settings, "PREP_SCRIPT_BATCH_SIZE", 3)))
        groups = [editable_scripts[index:index + batch_size] for index in range(0, len(editable_scripts), batch_size)]
        semaphore = asyncio.Semaphore(3)

        async def plan_group(group: list[TeachingScriptNode]) -> tuple[list[TeachingScriptNode], AgentPlan, list[dict[str, Any]]]:
            query = "\n".join(
                next((node.title for node in outline if node.outline_node_id == script.outline_node_id), "")
                for script in group
            )
            evidence = await self.retrieve_action_evidence(
                session,
                course_id=course_id,
                instruction=f"{instruction}\n{query}",
            )
            async with semaphore:
                compact_outline = self._compact_script_outline_context(outline, group)
                plan = await self._required_llm_plan(
                    action=PrepAction.OPTIMIZE_ALL_SCRIPTS,
                    instruction=instruction,
                    outline=[],
                    scripts=group,
                    evidence=evidence,
                    course_outline_context=compact_outline,
                    course_script_context=group,
                )
            return group, plan, evidence

        planned_groups = await asyncio.gather(*(plan_group(group) for group in groups))
        operations: list[dict[str, Any]] = []
        all_evidence: list[dict[str, Any]] = []
        excluded: list[str] = []
        for group, plan, evidence in planned_groups:
            kept, group_excluded, discarded = self._filter_operations(
                plan=plan,
                editable_outline=[],
                editable_scripts=group,
                locked_targets=locked_targets,
                allowed_evidence_ids={item["evidence_id"] for item in evidence if item.get("evidence_id")},
            )
            expected = {script.script_node_id for script in group}
            # Coverage: every script must have been addressed by the LLM.
            # A no-op (unchanged content) is a valid decision; it is covered
            # when the plan contains a script/content operation for that id
            # even if _filter_operations skipped it as unchanged.
            covered = {
                op.target_id for op in plan.operations
                if op.target_kind == "script" and op.field == "content"
                and op.target_id in expected
            }
            if discarded or covered != expected:
                missing = expected - covered
                extra = covered - expected
                detail = (
                    f"discarded={discarded}, expected={len(expected)}, "
                    f"covered={len(covered)}, kept={len(kept)}"
                )
                if missing:
                    detail += f", missing={sorted(missing)}"
                if extra:
                    detail += f", extra={sorted(extra)}"
                logger.warning(
                    "Script batch validation failed: %s; "
                    "plan_operations=%d group_ids=%s "
                    "kept_targets=%s",
                    detail,
                    len(plan.operations),
                    sorted(expected),
                    [item["target"] for item in kept],
                )
                raise CoursePrepAgentPlanningError(
                    f"至少一组讲解脚本未完整通过校验，未应用任何批量修改（{detail}）"
                )
            operations.extend(kept)
            all_evidence.extend(evidence)
            excluded.extend(group_excluded)
        return CoursePrepAgentResult(
            summary=f"已完成 {len(editable_scripts)} 个未锁定讲解脚本的分组优化计划",
            operations=operations,
            evidence=_dedupe_evidence(all_evidence),
            excluded_locked_targets=sorted(set(excluded)),
            planner=f"llm_script_batches_{batch_size}x3",
        )

    @staticmethod
    def _safe_title(
        title: str,
        node: CourseOutlineNode,
        evidence: list[dict[str, Any]],
    ) -> bool:
        candidate = (title or "").strip()
        if not (2 <= len(candidate) <= 40) or re.search(r"[。！？\n]", candidate):
            return False
        if re.match(r"^(图|表)\s*[0-9A-Za-z._-]+", candidate):
            return False
        source = " ".join([node.title or "", *(str(item.get("text") or "") for item in evidence)])
        sequences = re.findall(r"[\u4e00-\u9fff]{2,}", source)
        terms = {
            sequence[index:index + 2]
            for sequence in sequences
            for index in range(max(0, len(sequence) - 1))
        }
        return not terms or any(term in candidate for term in terms)

    @staticmethod
    def _filter_structure_operations(
        *,
        plan: AgentPlan,
        outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode],
        allowed_evidence_ids: set[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        by_id = {node.outline_node_id: node for node in outline}
        editable_ids = {node.outline_node_id for node in outline if node.locked_by is None}
        locked_ids = {node.outline_node_id for node in outline if node.locked_by is not None}
        parent_by_id = {node.outline_node_id: node.parent_node_id for node in outline}
        removed: set[str] = set()
        normalized: list[dict[str, Any]] = []
        excluded: list[str] = []
        seen_operations: set[tuple[str, str]] = set()

        for item in plan.operations:
            operation_key = (item.operation, item.target_id)
            if operation_key in seen_operations:
                raise CoursePrepAgentPlanningError("结构整理为同一节点重复生成了同类操作")
            seen_operations.add(operation_key)
            if item.target_kind != "outline" or item.target_id not in by_id:
                raise CoursePrepAgentPlanningError("结构整理返回了当前草稿以外的目标，未应用任何修改")
            if item.target_id in locked_ids:
                excluded.append(f"outline:{item.target_id}")
                continue
            if item.operation == "replace":
                if item.field != "title" or not item.after.strip() or not CoursePrepAgentService._safe_title(item.after, by_id[item.target_id], []):
                    raise CoursePrepAgentPlanningError("结构整理返回了不安全的标题修改，未应用任何修改")
                if item.after.strip() == by_id[item.target_id].title:
                    # A sparse-plan no-op is a model contract violation but
                    # not a reason to discard independent safe edits.
                    continue
                normalized.append({
                    "operation": "replace",
                    "target": f"outline:{item.target_id}:title",
                    "after": item.after.strip(),
                    "reason": item.reason,
                    "evidence_refs": [ref for ref in item.evidence_refs if ref in allowed_evidence_ids],
                })
            elif item.operation == "move":
                parent_id = item.parent_node_id
                if parent_id is not None and parent_id not in editable_ids:
                    raise CoursePrepAgentPlanningError("结构整理不能把节点移动到锁定或不存在的父节点下")
                parent_by_id[item.target_id] = parent_id
                normalized.append({
                    "operation": "move",
                    "target": f"outline:{item.target_id}:structure",
                    "after": json.dumps({"parent_node_id": parent_id, "order_index": item.order_index}, ensure_ascii=False),
                    "reason": item.reason,
                    "evidence_refs": [ref for ref in item.evidence_refs if ref in allowed_evidence_ids],
                })
            elif item.operation == "reorder":
                if item.order_index is None:
                    raise CoursePrepAgentPlanningError("结构整理的排序操作缺少目标位置")
                normalized.append({
                    "operation": "reorder",
                    "target": f"outline:{item.target_id}:structure",
                    "after": json.dumps({"order_index": item.order_index}, ensure_ascii=False),
                    "reason": item.reason,
                    "evidence_refs": [ref for ref in item.evidence_refs if ref in allowed_evidence_ids],
                })
            elif item.operation == "remove":
                if item.field not in {"", "structure"}:
                    raise CoursePrepAgentPlanningError("删除课程节点不能附带字段替换")
                removed.add(item.target_id)
                normalized.append({
                    "operation": "remove",
                    "target": f"outline:{item.target_id}:structure",
                    "after": "",
                    "reason": item.reason,
                    "evidence_refs": [ref for ref in item.evidence_refs if ref in allowed_evidence_ids],
                })
            else:
                raise CoursePrepAgentPlanningError("结构整理包含不支持的操作")

        for node_id in parent_by_id:
            seen: set[str] = set()
            cursor: str | None = node_id
            while cursor is not None:
                if cursor in seen:
                    raise CoursePrepAgentPlanningError("结构整理会造成课程节点成环，未应用任何修改")
                seen.add(cursor)
                cursor = parent_by_id.get(cursor)

        # A surviving (non-removed) node must never end up under a parent that
        # is itself being removed. Nodes that are removed together with their
        # parent form a valid branch removal and must be excluded here; the
        # remaining-children check below already guards surviving children.
        if any(
            node_id not in removed and parent_id in removed
            for node_id, parent_id in parent_by_id.items()
            if parent_id is not None
        ):
            raise CoursePrepAgentPlanningError("结构整理把节点移动到了将被删除的父节点下")
        title_targets = {
            item["target"].split(":", 2)[1]
            for item in normalized
            if item["operation"] == "replace"
        }
        if title_targets & removed:
            raise CoursePrepAgentPlanningError("不能同时修改并删除同一课程节点")

        for node_id in removed:
            descendants = _outline_descendants(node_id, parent_by_id)
            if descendants & locked_ids:
                raise CoursePrepAgentPlanningError("不能删除包含锁定节点的课程分支")
            remaining_children = {
                child_id for child_id, parent_id in parent_by_id.items()
                if parent_id == node_id and child_id not in removed
            }
            if remaining_children:
                raise CoursePrepAgentPlanningError("删除父节点前必须先移动其全部子节点")
            if any(script.outline_node_id == node_id and script.locked_by is not None for script in scripts):
                raise CoursePrepAgentPlanningError("不能删除关联了锁定讲解脚本的课程节点")
        return normalized, sorted(set(excluded))

    async def plan_batch(
        self,
        session: Session,
        *,
        course_id: int,
        action: BatchAction,
    ) -> CoursePrepAgentResult:
        """Compatibility entry for older callers of the two batch buttons.

        One-click actions are editorial passes, not a series of unrelated
        per-node rewrites.  The model receives every unlocked draft node and
        script as course context, but may emit operations only for the field
        selected by ``action``.  Complete coverage is verified before the
        endpoint opens its mutation transaction.
        """
        canonical = canonical_prep_action(action)
        if canonical is not None:
            return await self.plan_action(
                session,
                course_id=course_id,
                action=canonical,
            )
        if action not in {"organize_structure", "optimize_scripts"}:
            raise ValueError(f"不支持的批量动作: {action}")
        if not self._llm_is_configured():
            raise CoursePrepAgentPlanningError("助教智能体模型尚未配置，无法执行批量优化")

        outline, scripts = self._load_latest_draft_targets(session, course_id=course_id)
        editable_course_outline = [node for node in outline if node.locked_by is None]
        editable_course_scripts = [node for node in scripts if node.locked_by is None]
        if action == "organize_structure":
            editable_outline = editable_course_outline
            editable_scripts: list[TeachingScriptNode] = []
            locked = [
                f"outline:{node.outline_node_id}"
                for node in outline
                if node.locked_by is not None
            ]
            target_kind = "outline"
            required_field = "title"
            targets: list[Any] = editable_outline
            instruction = (
                "整理本课程全部未锁定的结构节点标题。基于完整的未锁定目录和讲稿上下文，"
                "统一命名粒度、术语与标题风格；保持节点数量、父子关系、顺序和课程事实不变。"
            )
            structure_sparse = getattr(settings, "PREP_SPARSE_STRUCTURE_PLAN", True)
        else:
            editable_outline = []
            editable_scripts = editable_course_scripts
            locked = [
                f"script:{node.script_node_id}"
                for node in scripts
                if node.locked_by is not None
            ]
            target_kind = "script"
            required_field = "content"
            targets = editable_scripts
            instruction = (
                "统一优化本课程全部未锁定讲稿。基于完整的未锁定目录和全部原始讲稿，"
                "统一术语、衔接和教学节奏，保留原事实与证据含义不变；"
                "每个讲稿都必须返回一项 content 修改。"
            )

        if not targets:
            raise ValueError("当前草稿没有可执行该批量动作的未锁定节点")
        if len(targets) > _BATCH_MAX_TARGETS:
            raise CoursePrepAgentPlanningError(
                f"当前草稿有 {len(targets)} 个可编辑目标，超过一次性课程级优化上限 "
                f"{_BATCH_MAX_TARGETS}；为避免部分应用，未执行任何修改"
            )

        self._validate_batch_capacity(
            action=action,
            outline=editable_course_outline,
            scripts=editable_course_scripts,
            target_count=len(targets),
        )

        # Batch actions rely on the draft itself as their editable source of
        # truth.  Single-node chat still does course evidence retrieval and
        # produces a reviewable proposal.
        evidence: list[dict[str, Any]] = []

        plan = await self._plan_with_llm(
            instruction=instruction,
            outline=editable_outline,
            scripts=editable_scripts,
            evidence=evidence,
            batch_action=action,
            course_outline_context=editable_course_outline,
            course_script_context=editable_course_scripts,
            structure_mode=(action == "organize_structure" and structure_sparse),
        )
        if plan is None:
            raise CoursePrepAgentPlanningError("助教智能体模型未返回批量优化结果")
        operations, _, discarded = self._filter_operations(
            plan=plan,
            editable_outline=editable_outline,
            editable_scripts=editable_scripts,
            locked_targets=set(),
            allowed_evidence_ids=set(),
        )
        expected_ids = {
            node.outline_node_id if target_kind == "outline" else node.script_node_id
            for node in targets
        }
        covered_ids = {
            item["target"].split(":", 2)[1]
            for item in operations
            if item["target"].endswith(f":{required_field}")
        }
        missing = sorted(expected_ids - covered_ids)
        if action != "organize_structure" and (missing or len(operations) != len(expected_ids) or discarded):
            logger.warning(
                "Course prep batch action %s returned incomplete or duplicate operations: "
                "missing=%s kept=%d expected=%d discarded=%d",
                action, missing[:10], len(operations), len(expected_ids), discarded,
            )
            raise CoursePrepAgentPlanningError(
                "模型未按每个节点恰好一项修改完整覆盖本课程，未应用任何修改"
            )

        return CoursePrepAgentResult(
            summary=plan.summary,
            operations=operations,
            evidence=evidence,
            excluded_locked_targets=locked,
            planner="llm_course_batch",
        )

    @staticmethod
    def _load_latest_draft_targets(
        session: Session,
        *,
        course_id: int,
    ) -> tuple[list[CourseOutlineNode], list[TeachingScriptNode]]:
        outline_version = session.exec(
            select(CourseOutlineVersion).where(
                CourseOutlineVersion.course_id == course_id,
                CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
            ).order_by(CourseOutlineVersion.version.desc())
        ).first()
        if outline_version is None:
            raise ValueError("课程尚未有初始草稿；请先完成材料解析与首次智能备课")
        outline = list(session.exec(
            select(CourseOutlineNode).where(
                CourseOutlineNode.course_id == course_id,
                CourseOutlineNode.outline_version_id == outline_version.outline_version_id,
            ).order_by(CourseOutlineNode.order_index)
        ).all())
        if not outline:
            raise ValueError("课程尚未有初始草稿；请先完成材料解析与首次智能备课")
        script_version = session.exec(
            select(TeachingScriptVersion).where(
                TeachingScriptVersion.course_id == course_id,
                TeachingScriptVersion.outline_version_id == outline_version.outline_version_id,
                TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
            ).order_by(TeachingScriptVersion.version.desc())
        ).first()
        scripts = [] if script_version is None else list(session.exec(
            select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_version_id == script_version.script_version_id,
            ).order_by(TeachingScriptNode.updated_at.desc())
        ).all())
        return outline, scripts

    @staticmethod
    def _compact_script_outline_context(
        outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode],
    ) -> list[CourseOutlineNode]:
        """Keep only selected script nodes and their editable ancestors."""
        by_id = {node.outline_node_id: node for node in outline}
        needed: set[str] = set()
        for script in scripts:
            cursor: str | None = script.outline_node_id
            while cursor is not None and cursor not in needed:
                node = by_id.get(cursor)
                if node is None or node.locked_by is not None:
                    break
                needed.add(cursor)
                cursor = node.parent_node_id
        return [node for node in outline if node.outline_node_id in needed]

    @staticmethod
    def _filter_operations(
        *,
        plan: AgentPlan,
        editable_outline: list[CourseOutlineNode],
        editable_scripts: list[TeachingScriptNode],
        locked_targets: set[str],
        allowed_evidence_ids: set[str],
    ) -> tuple[list[dict[str, Any]], list[str], int]:
        kept: list[dict[str, Any]] = []
        excluded: list[str] = []
        discarded_invalid_or_noop = 0
        for operation in plan.operations:
            key = f"{operation.target_kind}:{operation.target_id}"
            if key in locked_targets:
                excluded.append(key)
                continue
            target_node = next(
                (node for node in editable_outline if node.outline_node_id == operation.target_id),
                None,
            ) if operation.target_kind == "outline" else next(
                (node for node in editable_scripts if node.script_node_id == operation.target_id),
                None,
            )
            allowed_fields = {"title"} if operation.target_kind == "outline" else {"content", "style"}
            if target_node is None or operation.field not in allowed_fields:
                discarded_invalid_or_noop += 1
                continue
            if str(getattr(target_node, operation.field, "")) == operation.after:
                # A no-op (unchanged content) is a valid model decision that
                # the field is already optimal, not an invalid operation. Skip
                # it without counting toward the discarded tally so batch
                # coverage checks don't fail when some scripts need no change.
                continue
            kept.append({
                "target": f"{operation.target_kind}:{operation.target_id}:{operation.field}",
                "after": operation.after,
                "reason": (
                    f"{operation.reason}。下游影响："
                    f"{operation.downstream_impact or '请检查关联讲稿、练习和映射。'}"
                ),
                "evidence_refs": [
                    item for item in operation.evidence_refs if item in allowed_evidence_ids
                ],
            })
        return kept, excluded, discarded_invalid_or_noop

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
        candidate_stmt = stmt
        if terms:
            candidate_stmt = candidate_stmt.where(or_(*[
                DocumentBlock.text.ilike(f"%{term}%") for term in terms
            ]))
        blocks = list(session.exec(
            candidate_stmt.order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index).limit(64)
        ).all())
        if not blocks and terms:
            blocks = list(session.exec(
                stmt.order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index).limit(64)
            ).all())
        # This is lexical overlap ranking, not BM25, BERT reranking, or vector
        # retrieval. Keep that distinction explicit in code and audit docs.
        ranked = sorted(
            blocks,
            key=lambda block: sum(term in (block.text or "").lower() for term in terms),
            reverse=True,
        )[:8]
        spans = list(session.exec(select(EvidenceSpan).where(
            EvidenceSpan.course_id == course_id,
            EvidenceSpan.block_id.in_([block.block_id for block in ranked]),
            EvidenceSpan.status == EvidenceSpanStatus.CONFIRMED,
        )).all()) if ranked else []
        spans_by_block: dict[str, EvidenceSpan] = {}
        for span in spans:
            spans_by_block.setdefault(span.block_id, span)
        result = []
        for block in ranked:
            span = spans_by_block.get(block.block_id)
            result.append({
                "block_id": block.block_id,
                "evidence_id": span.span_id if span else None,
                "page": block.page_or_slide or block.page_number,
                "text": (block.text or "")[:800],
                "confirmed": span is not None,
            })
        return result

    async def retrieve_action_evidence(
        self,
        session: Session,
        *,
        course_id: int,
        instruction: str,
        concept_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Combine durable local evidence with the active Bundle's RAG hits.

        The vector Port is course-scoped and read-only.  It can be unavailable
        for a newly imported course, in which case the lexical projection is
        still useful source context; no fake evidence ID is invented.
        """
        lexical = self.retrieve_course_evidence(
            session,
            course_id=course_id,
            instruction=instruction,
        )
        if self._course_retrieval is None:
            return lexical
        try:
            vector_hits = await self._course_retrieval.retrieve_course_evidence(
                course_id=str(course_id),
                message=instruction,
                concept_id=concept_id,
                resource_id=None,
            )
        except Exception as error:  # noqa: BLE001 - retrieval is a read-only enhancement
            logger.info(
                "Course Prep vector retrieval unavailable for course=%s: %s",
                course_id,
                type(error).__name__,
            )
            return lexical
        vector = [{
            "block_id": item.get("resource_id") or item.get("evidence_id") or "",
            "evidence_id": item.get("evidence_id"),
            "page": item.get("page_start"),
            "text": str(item.get("text") or "")[:800],
            "confirmed": bool(item.get("evidence_id")),
            "retrieval_sources": list(item.get("retrieval_sources") or []),
            "bundle_id": item.get("bundle_id"),
        } for item in vector_hits]
        return _dedupe_evidence([*vector, *lexical])

    async def _plan_with_llm(
        self, *, instruction: str, outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode], evidence: list[dict[str, Any]],
        batch_action: BatchAction | None = None,
        course_outline_context: list[CourseOutlineNode] | None = None,
        course_script_context: list[TeachingScriptNode] | None = None,
        structure_mode: bool = False,
    ) -> AgentPlan | StructurePlan | None:
        if not self._llm_is_configured():
            return None
        if batch_action == "organize_structure" and not getattr(settings, "PREP_SPARSE_STRUCTURE_PLAN", True):
            structure_mode = False
        if structure_mode:
            # Keep this payload deliberately small.  In particular, outline
            # titles may already contain OCR noise, so duplicating the tree or
            # adding all script bodies dramatically raises input tokens without
            # giving a title/structure planner any additional authority.
            payload: dict[str, Any] = {
                "instruction": instruction,
                "batch_action": batch_action,
                "structure_mode": True,
                "editable_outline": [
                    {
                        "id": item.outline_node_id,
                        "parent_id": item.parent_node_id,
                        "title": item.title,
                        "level": _outline_level(item, outline),
                        "order": item.order_index,
                    }
                    for item in outline
                ],
            }
        else:
            payload = {
                "instruction": instruction,
                "batch_action": batch_action,
                "editable_outline": [
                    {
                        "id": item.outline_node_id,
                        "parent_id": item.parent_node_id,
                        "title": item.title,
                        "level": _outline_level(item, outline),
                        "order": item.order_index,
                    }
                    for item in outline
                ],
                "editable_scripts": [
                    {
                        "id": item.script_node_id,
                        "outline_node_id": item.outline_node_id,
                        "content": item.content,
                        "style": item.style or "",
                        "valid_style_values": list(_VALID_STYLE_VALUES),
                    }
                    for item in scripts
                ],
                "retrieved_course_evidence": evidence,
            }
        if batch_action is not None and not structure_mode:
            context_outline = course_outline_context if course_outline_context is not None else outline
            context_scripts = course_script_context if course_script_context is not None else scripts
            context_outline_ids = {item.outline_node_id for item in context_outline}
            # Full original text lives only in course_context. The editable
            # lists are an allow-list, avoiding a second copy of every script.
            editable_script_ids = {item.script_node_id for item in scripts}
            if editable_script_ids:
                payload["editable_scripts"] = [
                    {
                        "id": item.script_node_id,
                        "outline_node_id": item.outline_node_id,
                        "valid_style_values": list(_VALID_STYLE_VALUES),
                    }
                    for item in scripts
                ]
            if not structure_mode:
                payload["course_context"] = {
                    "hierarchy": [
                        {
                            "id": item.outline_node_id,
                            # Do not expose locked-parent identifiers as context.
                            "parent_id": item.parent_node_id if item.parent_node_id in context_outline_ids else None,
                            "type": item.node_type.value,
                            "order": item.order_index,
                            "title": item.title,
                        }
                        for item in context_outline
                    ],
                    "scripts": [
                        {
                            "id": item.script_node_id,
                            "outline_node_id": item.outline_node_id,
                            "content": item.content,
                            "style": item.style or "",
                        }
                        for item in context_scripts
                    ],
                }
            # In structure mode editable_outline is already the complete,
            # compact tree snapshot.  Do not duplicate it as course_context.
        system = (
            "你是受控备课 Agent。只能对 editable_outline 和 editable_scripts 中的 ID 提出修改；"
            "不得生成、删除或移动节点，不得引用未提供的课程事实，不得修改任何锁定内容。"
            "返回纯 JSON，结构为 {summary, operations[]}；每项包含 target_kind, target_id, field, after, reason, downstream_impact, evidence_refs。"
            "证据只能使用已提供且 confirmed=true 的 evidence_id。"
        )
        system += (
            "target_kind 必须严格使用英文字符串 \"outline\" 或 \"script\"，不能使用同义词、中文或节点类型；"
            "field 必须严格使用英文字符串 \"title\"、\"content\" 或 \"style\"；target_id 必须从输入中原样复制。"
            "editable_scripts.content 是允许改写的课程事实来源；可以在不改变事实含义的前提下重组、简化和改写其表达。"
            "editable_scripts.style 是讲稿的解释风格，合法取值为 beginner/academic/concise；"
            "当 field=\"style\" 时，after 必须是这三个合法值之一，且必须与原 style 不同。"
            "如果没有 confirmed evidence，evidence_refs 使用空数组即可，不得因此保留原文不变。"
            "当教师明确要求改写时，after 必须与原字段有实质差异，不能提交原文不变的空操作。"
            "当教师要求同时修改\"内容和风格\"时，应生成两项操作：一项 field=\"content\"，一项 field=\"style\"，"
            "target_id 均为该讲稿节点 id；不得把两个字段合并到一个操作里。"
            "示例：{\"summary\":\"...\",\"operations\":[{\"target_kind\":\"script\","
            "\"target_id\":\"输入中的 script id\",\"field\":\"content\",\"after\":\"...\","
            "\"reason\":\"...\",\"downstream_impact\":\"...\",\"evidence_refs\":[]}]}。"
            "如果教师要求只生成一项，operations 必须恰好包含一项。"
            "当教师同时要求改进标题表述和知识覆盖时，若目标节点已有讲稿，必须分别生成 outline/title 与 script/content 两项提案；"
            "标题应概括原文的核心对象及被证据支持的作用、结构、原理、用途或检查维度，不能只追加‘优化建议’等空泛后缀；"
            "若原文同时说明对象的功能、结构和一个专门用途，标题应采用‘对象的作用、结构与专门用途’的概念化表达；"
            "script/content 应覆盖标题中承诺的知识维度，不得引入输入证据之外的课程事实。"
            "operations 数组不得为空，至少包含一项；summary 不得为空。"
        )
        if structure_mode:
            system = (
                "Return one JSON object with summary and operations. This is a sparse course-tree edit. "
                "Input editable_outline is the complete editable tree; return only actual safe changes. "
                "For a title edit use {node_id,title}; do not include operation, reason, evidence_refs, or an "
                "unchanged title. For other edits use exactly {node_id,operation:'move',new_parent_id}, "
                "{node_id,operation:'reorder',new_order}, or {node_id,operation:'remove'}. "
                "Never add nodes, create cycles, modify locked nodes, or return markdown."
            )
        elif batch_action == "organize_structure":
            system += (
                "这是一次完整课程结构整理。course_context 给出全部未锁定的原始目录和讲稿，"
                "可据此判断知识点标题是否表达了真正概念、粒度是否合适、与可见父级是否连贯；"
                "但仍不得新增、删除、移动或重设父子关系。遇到图号、表号、页码、OCR 片段或 "
                "a）/b）/c）枚举式图注时，必须改为其实际教学概念的标题。例如 "
                "“图2-28 V 型发动机连杆 a）并列式连杆 b）主副连杆 c）叉形连杆”应整理为 "
                "“V 型发动机连杆的结构形式”。只能返回 outline/title 操作；"
                "reason 与 downstream_impact 各不超过 80 个汉字；"
                "必须为 editable_outline 中每个 ID 恰好返回一项操作，不得遗漏。"
            )
        elif batch_action == "optimize_scripts":
            system += (
                "这是一次完整课程讲稿优化。course_context 给出全部未锁定的原始目录和讲稿，"
                "要把它们作为一段连续课程讲解统一组织。使用适合中文 TTS 的自然短句和清晰停顿，"
                "在段落之间补足必要的承接，先解释术语再给出密集列举，避免朗读图号、页码、"
                "OCR 碎片和生硬的 a）/b）/c）图注；不得改变课程事实。只能返回 script/content 操作；"
                "reason 与 downstream_impact 各不超过 80 个汉字；"
                "必须为 editable_scripts 中每个 ID 恰好返回一项操作，不得遗漏，不得返回 style 或 outline 操作。"
            )
        if batch_action is not None and not structure_mode:
            # The adapter uses the equivalent registered PromptSpec.  Keep a
            # complete direct-client prompt here for local diagnostics and
            # backwards-compatible service injection.
            system = (
                "You are a controlled course-preparation planner. Return JSON only with "
                "summary and operations. The input batch_action is the only allowed capability. "
                "Targets must be copied from editable_outline or editable_scripts; never modify "
                "locked or context-only nodes. Each operation has target_kind, target_id, operation, "
                "field, after, parent_node_id, order_index, reason, downstream_impact, evidence_refs. "
                "For optimize_node_title return exactly one outline replace/title. "
                "For optimize_node_script return only selected script replace/content operations. "
                "For optimize_all_scripts return exactly one script replace/content operation for each editable script. "
                "For organize_structure return only outline operations: replace/title, move with parent_node_id, "
                "reorder with order_index, or remove. Do not add nodes, create cycles, move into locked parents, "
                "or remove a branch containing locked descendants."
            )
        if self._llm is not None and hasattr(self._llm, "plan_incremental"):
            result = await self._llm.plan_incremental(payload)
            if structure_mode and isinstance(result, AgentPlan):
                result = self._agent_plan_to_structure_plan(result)
            return result
        client = self._llm or llm_client
        return await self._call_llm_with_retry(client, system, payload)

    @staticmethod
    def _validate_batch_capacity(
        *,
        action: BatchAction,
        outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode],
        target_count: int,
    ) -> None:
        """Fail closed before a full-course response can be truncated."""
        input_chars = sum(
            len(item.title or "") + len(item.parent_node_id or "") + 64
            for item in outline
        )
        # A sparse structure pass never sends script bodies.  Counting them
        # here made capacity validation disagree with the actual request and
        # could reject an otherwise small directory-only planning call.
        if action != "organize_structure":
            input_chars += sum(
                len(item.content or "") + len(item.style or "") + 64
                for item in scripts
            )
        if action == "organize_structure":
            output_budget = sum(len(item.title or "") for item in outline)
            output_budget += target_count * _BATCH_TITLE_OUTPUT_OVERHEAD
        else:
            output_budget = sum(len(item.content or "") for item in scripts)
            output_budget += target_count * _BATCH_SCRIPT_OUTPUT_OVERHEAD
        output_tokens = (
            int(settings.PREP_STRUCTURE_MAX_TOKENS)
            if action == "organize_structure"
            # Script batches are planned in small groups.  Preserve the legacy
            # course-level preflight ceiling here instead of rejecting a normal
            # course by comparing all groups to one 4096-token call.
            else int(settings.LLM_MAX_TOKENS)
        )
        output_limit = max(1, output_tokens) * 4
        if input_chars > _BATCH_MAX_INPUT_CHARS or output_budget > output_limit:
            raise CoursePrepAgentPlanningError(
                "当前课程的未锁定原文或完整优化结果超过单次模型容量；"
                "为避免截断和部分应用，未执行任何修改"
            )

    async def _call_llm_with_retry(
        self, client: Any, system: str, payload: dict[str, Any],
    ) -> AgentPlan:
        """Call the LLM with one structured-repair retry.

        Mirrors ``ControlledPrepWorkflow._structured_call``'s retry pattern:
        on ``ValidationError`` / ``JSONDecodeError``, send a repair prompt
        containing the validation errors and retry once. Other exceptions
        (network, auth) are not retried.
        """
        user_content = json.dumps(payload, ensure_ascii=False)
        messages = [
            Message(role="system", content=system),
            Message(role="user", content=user_content),
        ]
        last_error: Exception | None = None
        for attempt in range(_LLM_MAX_RETRIES + 1):
            repair_hint = ""
            if last_error is not None:
                error_detail = ""
                if isinstance(last_error, ValidationError):
                    error_detail = json.dumps(
                        last_error.errors(include_input=False), ensure_ascii=False,
                    )[:800]
                else:
                    error_detail = str(last_error)[:800]
                repair_hint = (
                    "\n\n上一次输出未通过严格校验。只返回符合 JSON Schema 的 JSON，"
                    f"不要 Markdown，不要解释。校验错误：{error_detail}"
                )
            try:
                request_kwargs: dict[str, Any] = {
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                }
                if payload.get("structure_mode"):
                    # Keep the legacy direct-client path bounded as well. The
                    # registered Prep adapter uses the same knobs; this is a
                    # rollback-safe fallback for local/demo callers.
                    request_kwargs.update({
                        "max_tokens": int(settings.PREP_STRUCTURE_MAX_TOKENS),
                        "thinking": {"type": "disabled"},
                    })
                elif payload.get("batch_action") in {
                    "optimize_all_scripts",
                    "optimize_node_script",
                }:
                    request_kwargs.update({
                        "max_tokens": 4096,
                        "thinking": {"type": "disabled"},
                    })
                response = await client.chat(
                    messages if repair_hint == "" else [
                        *messages,
                        Message(role="system", content=repair_hint),
                    ],
                    **request_kwargs,
                )
                raw = response.content if hasattr(response, "content") else response
                if not isinstance(raw, str):
                    raise CoursePrepAgentPlanningError(
                        "模型返回的备课提案不是文本，请重试"
                    )
                schema = StructurePlan if payload.get("structure_mode") else AgentPlan
                plan = schema.model_validate_json(raw)
                if not plan.operations and payload.get("batch_action") != PrepAction.ORGANIZE_STRUCTURE.value:
                    raise ValueError("operations must not be empty for this preparation action")
                logger.info(
                    "Course prep LLM succeeded: model=%s latency_ms=%.0f usage=%s "
                    "operations=%d attempt=%d repaired=%s",
                    getattr(response, "model", "unknown"),
                    getattr(response, "latency_ms", 0.0),
                    getattr(response, "usage", {}),
                    len(plan.operations),
                    attempt + 1,
                    last_error is not None,
                )
                return plan
            except ValidationError as exc:
                last_error = exc
                logger.warning(
                    "Course prep LLM returned invalid plan (attempt %d/%d): "
                    "errors=%s raw_response_prefix=%.400s",
                    attempt + 1, _LLM_MAX_RETRIES + 1,
                    exc.errors(include_input=False),
                    raw if isinstance(raw, str) else "",
                )
                if attempt >= _LLM_MAX_RETRIES:
                    raise CoursePrepAgentPlanningError(
                        "模型返回的备课提案格式不符合安全协议，请重试"
                    ) from exc
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Course prep LLM returned invalid JSON (attempt %d/%d): "
                    "%s raw_response_prefix=%.400s",
                    attempt + 1, _LLM_MAX_RETRIES + 1,
                    type(exc).__name__,
                    raw if isinstance(raw, str) else "",
                )
                if attempt >= _LLM_MAX_RETRIES:
                    raise CoursePrepAgentPlanningError(
                        "模型返回的备课提案不是有效 JSON，请重试"
                    ) from exc
            except CoursePrepAgentPlanningError:
                raise
            except Exception as exc:
                logger.warning(
                    "Course prep LLM request failed: %s: %s",
                    type(exc).__name__, str(exc)[:500],
                )
                raise CoursePrepAgentPlanningError(
                    "备课模型服务调用失败，请稍后重试"
                ) from exc
        # Unreachable: loop either returns or raises on the final attempt.
        raise CoursePrepAgentPlanningError("备课模型服务调用失败，请稍后重试")

    def _llm_is_configured(self) -> bool:
        from app.core.config import settings
        return self._llm is not None or bool(
            (settings.LLM_API_KEY or "").strip()
            and (settings.LLM_MODEL_NAME or "").strip()
        )

    @staticmethod
    def _title_requested(instruction: str) -> bool:
        return any(term in instruction for term in _TITLE_REQUEST_TERMS)

    @staticmethod
    def _content_requested(instruction: str) -> bool:
        return any(term in instruction for term in _CONTENT_REQUEST_TERMS)

    @staticmethod
    def _title_subject(node: CourseOutlineNode, source: str) -> str:
        """Infer the stable knowledge object without relying on a topic name."""
        subject = re.sub(r"^(?:图|表)\s*[0-9A-Za-z._-]+\s*", "", (node.title or "").strip())
        # OCR often drops the linking "的" in titles such as
        # "发动机结构基本术语". Keep the object (发动机结构) separate from
        # the teaching facet (基本术语), so the fallback can restore it.
        terminology_match = re.match(r"^(.+?)(?:的)?基本术语$", subject)
        if terminology_match:
            subject = terminology_match.group(1).strip()
        if not subject or subject in {"知识点", "章节", "未命名"}:
            first_sentence = re.split(r"[。！？\n]", source, maxsplit=1)[0]
            match = re.match(r"(.{1,20}?)(?:是|为|包括|指)", first_sentence)
            if match:
                subject = match.group(1).strip(" ：:，,")

        suffixes = "|".join(re.escape(item) for item in _TITLE_NOUN_SUFFIXES)
        context_candidates = Counter(
            re.findall(rf"[\u4e00-\u9fff]{{1,5}}(?:{suffixes})", source)
        )
        for raw_candidate, count in context_candidates.most_common():
            candidate = raw_candidate
            for prefix in sorted(_TITLE_CONTEXT_STOP_WORDS, key=len, reverse=True):
                if candidate.startswith(prefix) and len(candidate) > len(prefix) + 1:
                    candidate = candidate[len(prefix):]
                    break
            if (
                count < 2
                or candidate == subject
                or candidate in subject
                or candidate in _TITLE_CONTEXT_STOP_WORDS
            ):
                continue
            if len(candidate) <= 6:
                return f"{candidate}{subject}"
        return subject or "该知识点"

    @staticmethod
    def _title_facets(source: str) -> list[str]:
        """Extract teachable dimensions in a fixed, human-readable order."""
        facets: list[str] = []
        if re.search(r"基本术语|术语|名词|称谓", source):
            facets.append("基本术语" if re.search(r"基本术语", source) else "术语")
        if re.search(r"作用|功能|用途|负责|保证|实现", source):
            facets.append("作用")
        if re.search(r"结构|组成|形状|部件|外缘|内缘|齿圈|包括", source):
            facets.append("结构")
        if re.search(r"正时(?:记号|标记)|点火(?:正时)?记号|喷油(?:正时)?记号", source):
            facets.append("正时标记")
        elif re.search(r"标记|记号", source):
            facets.append("标记")
        elif re.search(r"维护|安装|拆卸|故障|诊断|排查", source):
            facets.append("维护与检查")
        if re.search(r"原理|工作机制|工作过程", source):
            facets.append("原理")
        return facets

    @classmethod
    def _build_title_suggestion(cls, node: CourseOutlineNode, source: str) -> str:
        subject = cls._title_subject(node, source)
        # Do not append a facet that is already part of the subject. This is
        # common with OCR headings such as "发动机结构基本术语" and prevents
        # awkward results like "发动机结构的基本术语与结构".
        facets = [facet for facet in cls._title_facets(source) if facet not in subject]
        if not facets:
            return f"{subject}的核心概念与教学要点"
        if len(facets) == 1:
            return f"{subject}的{facets[0]}"
        return f"{subject}的{'、'.join(facets[:-1])}与{facets[-1]}"

    @classmethod
    def _title_fallback_result(
        cls,
        *,
        selected: CourseOutlineNode,
        title: str,
        evidence: list[dict[str, Any]],
        reason: str,
    ) -> CoursePrepAgentResult:
        """Return one source-backed title operation and nothing else."""
        candidate = (title or "").strip()
        if not cls._safe_title(candidate, selected, evidence):
            raise CoursePrepAgentPlanningError("当前节点原文不足以生成可安全应用的标题，草稿未修改")
        return CoursePrepAgentResult(
            summary="已依据当前节点标题与课程原文生成可审阅的标题优化建议",
            operations=[{
                "target": f"outline:{selected.outline_node_id}:title",
                "after": candidate,
                "reason": reason,
                "evidence_refs": [
                    item["evidence_id"]
                    for item in evidence
                    if item.get("evidence_id")
                ],
            }],
            evidence=evidence,
            excluded_locked_targets=[],
            planner="deterministic_title_fallback",
        )

    @classmethod
    def _guard_title_plan(
        cls,
        plan: AgentPlan,
        *,
        instruction: str,
        outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode],
    ) -> AgentPlan:
        """Make title edits complete and semantic after the LLM has answered."""
        if not cls._title_requested(instruction) or not outline:
            return plan

        existing_title_ids = {
            operation.target_id
            for operation in plan.operations
            if operation.target_kind == "outline" and operation.field == "title"
        }
        if len(outline) == 1:
            target_nodes = outline
        else:
            target_nodes = [node for node in outline if node.outline_node_id in existing_title_ids]
        if not target_nodes:
            return plan

        operations = list(plan.operations)
        for node in target_nodes:
            script = next((item for item in scripts if item.outline_node_id == node.outline_node_id), None)
            source = "\n".join(
                part for part in (
                    instruction,
                    node.title or "",
                    script.content if script is not None else "",
                ) if part
            )
            suggestion = cls._build_title_suggestion(node, source)
            operation_index = next(
                (
                    index for index, operation in enumerate(operations)
                    if operation.target_kind == "outline"
                    and operation.target_id == node.outline_node_id
                    and operation.field == "title"
                ),
                None,
            )
            if operation_index is None:
                operations.append(AgentOperation(
                    target_kind="outline",
                    target_id=node.outline_node_id,
                    field="title",
                    after=suggestion,
                    reason="按原文识别核心对象及知识维度，生成可审阅的结构化标题",
                    downstream_impact="可能影响关联讲稿、练习建议和 PPT 映射，请在教师确认后复核",
                ))
                continue
            operation = operations[operation_index]
            operations[operation_index] = operation.model_copy(update={"after": suggestion})

        return plan.model_copy(update={"operations": operations})

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
        source = "\n".join(
            part for part in (
                instruction,
                node.title or "",
                script.content if script is not None else "",
            ) if part
        )
        title_requested = CoursePrepAgentService._title_requested(instruction)
        coverage_requested = CoursePrepAgentService._content_requested(instruction)
        operations: list[AgentOperation] = []

        if title_requested:
            title_after = CoursePrepAgentService._build_title_suggestion(node, source)
            operations.append(AgentOperation(
                target_kind="outline", target_id=node.outline_node_id, field="title", after=title_after,
                reason="将节点标题改写为概括核心对象、作用、结构与用途的教学概念",
                downstream_impact="可能影响关联讲稿、练习建议和 PPT 映射，请在接受后复核。",
            ))

        if script is not None and coverage_requested:
            after = script.content + "\n\n【待教师确认的备课建议】请根据本节原文证据补充一个贴近教学对象的说明。"
            operations.append(AgentOperation(
                target_kind="script", target_id=script.script_node_id, field="content", after=after,
                reason="根据教师自然语言指令生成讲稿调整建议", downstream_impact="可能影响本节的音频与数字人媒体，需要在接受后重新生成。",
            ))

        if not operations:
            operations.append(AgentOperation(
                target_kind="outline", target_id=node.outline_node_id, field="title",
                after=f"{node.title}（教学节奏调整建议）",
                reason="根据教师自然语言指令生成目录调整建议", downstream_impact="可能影响关联讲稿、练习建议和 PPT 映射，请在接受后复核。",
            ))
        return AgentPlan(summary="已生成待教师审核的课程标题与知识覆盖调整提案。", operations=operations)

def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a stable, compact evidence list across parallel script groups."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("evidence_id") or ""), str(item.get("block_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _outline_descendants(node_id: str, parent_by_id: dict[str, str | None]) -> set[str]:
    """Return all descendants using the prospective parent relation."""
    descendants: set[str] = set()
    frontier = [node_id]
    while frontier:
        parent = frontier.pop()
        children = [child_id for child_id, parent_id in parent_by_id.items() if parent_id == parent]
        for child_id in children:
            if child_id not in descendants:
                descendants.add(child_id)
                frontier.append(child_id)
    return descendants


def _outline_level(node: CourseOutlineNode, nodes: list[CourseOutlineNode]) -> int:
    by_id = {item.outline_node_id: item.parent_node_id for item in nodes}
    level = 0
    cursor = node.parent_node_id
    seen: set[str] = set()
    while cursor and cursor not in seen:
        seen.add(cursor)
        level += 1
        cursor = by_id.get(cursor)
    return level


course_prep_agent_service = CoursePrepAgentService()
