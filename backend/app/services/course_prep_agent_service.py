"""Teacher-controlled course preparation agent.

The agent has read-only course tools and one proposal-writing tool.  It never
updates outline/script rows: every follow-up instruction is persisted as a
``PatchProposal`` for a teacher decision.  Locked nodes are excluded before
the LLM sees its editable target set and are checked again before persistence.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
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


PROMPT_VERSION = "course-prep-agent/1.2"
logger = logging.getLogger(__name__)

# 合法的 style 取值（与 TeachingScriptNode.style 字段对齐）
_VALID_STYLE_VALUES = ("beginner", "academic", "concise")
# 单次 LLM 调用的最大重试次数（首次 + 修复重试）
_LLM_MAX_RETRIES = 1
BatchAction = Literal["organize_structure", "optimize_scripts"]
# A batch is one course-level editorial pass.  The response still has a hard
# ceiling so an unexpectedly huge course fails closed instead of truncating.
_BATCH_MAX_TARGETS = 500
_BATCH_MAX_INPUT_CHARS = 120_000
_BATCH_OUTPUT_CHARS_PER_TARGET = 1_200


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
    operations: list[AgentOperation] = Field(min_length=1, max_length=_BATCH_MAX_TARGETS)


@dataclass
class CoursePrepAgentResult:
    summary: str
    operations: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    excluded_locked_targets: list[str]
    planner: str


class CoursePrepAgentPlanningError(RuntimeError):
    """The configured LLM failed to return a safe, valid preparation plan."""


class CoursePrepAgentService:
    """Read course facts, plan safe modifications, return proposal-ready data."""

    def __init__(self, *, llm: Any | None = None) -> None:
        """Allow injecting an LLM client (constructor接缝 for PrepLLMAdapter).

        When ``llm`` is ``None``, the service uses the module-level
        ``llm_client`` singleton (backward compatible). When an object
        with a ``chat()`` method is injected, ``_plan_with_llm`` calls
        ``self._llm.chat(...)`` instead of ``llm_client.chat(...)``.
        """
        self._llm = llm

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

    async def plan_batch(
        self,
        session: Session,
        *,
        course_id: int,
        action: BatchAction,
    ) -> CoursePrepAgentResult:
        """Plan one coherent, complete batch action over the current draft.

        One-click actions are editorial passes, not a series of unrelated
        per-node rewrites.  The model receives every unlocked draft node and
        script as course context, but may emit operations only for the field
        selected by ``action``.  Complete coverage is verified before the
        endpoint opens its mutation transaction.
        """
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
        if missing or len(operations) != len(expected_ids) or discarded:
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
                discarded_invalid_or_noop += 1
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

    async def _plan_with_llm(
        self, *, instruction: str, outline: list[CourseOutlineNode],
        scripts: list[TeachingScriptNode], evidence: list[dict[str, Any]],
        batch_action: BatchAction | None = None,
        course_outline_context: list[CourseOutlineNode] | None = None,
        course_script_context: list[TeachingScriptNode] | None = None,
    ) -> AgentPlan | None:
        if not self._llm_is_configured():
            return None
        payload = {
            "instruction": instruction,
            "batch_action": batch_action,
            "editable_outline": [
                {
                    "id": item.outline_node_id,
                    "parent_id": item.parent_node_id,
                    "title": item.title,
                    "type": item.node_type.value,
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
        if batch_action is not None:
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
            "operations 数组不得为空，至少包含一项；summary 不得为空。"
        )
        if batch_action == "organize_structure":
            system += (
                "这是一次完整课程结构整理。course_context 给出全部未锁定的原始目录和讲稿，"
                "可据此判断知识点标题是否表达了真正概念、粒度是否合适、与可见父级是否连贯；"
                "但仍不得新增、删除、移动或重设父子关系。遇到图号、表号、页码、OCR 片段或 "
                "a）/b）/c）枚举式图注时，必须改为其实际教学概念的标题。例如 "
                "“图2-28 V 型发动机连杆 a）并列式连杆 b）主副连杆 c）叉形连杆”应整理为 "
                "“V 型发动机连杆的结构形式”。只能返回 outline/title 操作；"
                "必须为 editable_outline 中每个 ID 恰好返回一项操作，不得遗漏。"
            )
        elif batch_action == "optimize_scripts":
            system += (
                "这是一次完整课程讲稿优化。course_context 给出全部未锁定的原始目录和讲稿，"
                "要把它们作为一段连续课程讲解统一组织。使用适合中文 TTS 的自然短句和清晰停顿，"
                "在段落之间补足必要的承接，先解释术语再给出密集列举，避免朗读图号、页码、"
                "OCR 碎片和生硬的 a）/b）/c）图注；不得改变课程事实。只能返回 script/content 操作；"
                "必须为 editable_scripts 中每个 ID 恰好返回一项操作，不得遗漏，不得返回 style 或 outline 操作。"
            )
        if self._llm is not None and hasattr(self._llm, "plan_incremental"):
            return await self._llm.plan_incremental(payload)
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
        ) + sum(
            len(item.content or "") + len(item.style or "") + 64
            for item in scripts
        )
        output_budget = (
            sum(len(item.title or "") for item in outline)
            if action == "organize_structure"
            else sum(len(item.content or "") for item in scripts)
        ) + target_count * _BATCH_OUTPUT_CHARS_PER_TARGET
        output_limit = max(1, int(settings.LLM_MAX_TOKENS)) * 4
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
                response = await client.chat(
                    messages if repair_hint == "" else [
                        *messages,
                        Message(role="system", content=repair_hint),
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                raw = response.content if hasattr(response, "content") else response
                if not isinstance(raw, str):
                    raise CoursePrepAgentPlanningError(
                        "模型返回的备课提案不是文本，请重试"
                    )
                plan = AgentPlan.model_validate_json(raw)
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
