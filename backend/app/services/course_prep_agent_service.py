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
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from app.common.llm_client import Message, llm_client
from app.models.course_build_model import CourseCorpusSnapshot, CorpusSnapshotStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.document_parse_model import DocumentBlock, EvidenceSpan, EvidenceSpanStatus


PROMPT_VERSION = "course-prep-agent/1.1"
logger = logging.getLogger(__name__)

# 合法的 style 取值（与 TeachingScriptNode.style 字段对齐）
_VALID_STYLE_VALUES = ("beginner", "academic", "concise")
# 单次 LLM 调用的最大重试次数（首次 + 修复重试）
_LLM_MAX_RETRIES = 1


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
                "reason": f"{operation.reason}。下游影响：{operation.downstream_impact or '请在审核后检查关联讲稿、练习和映射。'}",
                "evidence_refs": [item for item in operation.evidence_refs if item in allowed_evidence_ids],
            })
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
                {
                    "id": item.script_node_id,
                    "outline_node_id": item.outline_node_id,
                    "content": item.content[:3000],
                    "style": item.style or "",
                    "valid_style_values": list(_VALID_STYLE_VALUES),
                }
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
        client = self._llm or llm_client
        return await self._call_llm_with_retry(client, system, payload)

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
