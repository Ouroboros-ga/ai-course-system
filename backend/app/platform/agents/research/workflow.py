"""Conditional LangGraph workflow for the ResearchAgent HarnessEngineer."""
from __future__ import annotations

import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.services.web_research_service import sanitize_query

from ..contracts.llm import LLMOptions, LLMTraceContext, StructuredLLMPort
from ..contracts.research import PaperSearchPort, ResearchScopePort
from ..contracts.research_workspace import ResearchWorkspacePort
from .harness.context import ContextItem, ResearchContextManager
from .harness.observability import record_node
from .harness.prompting import PromptTemplateError, ResearchPromptAssembler
from .harness.reliability import ReliableToolExecutor
from .harness.tooling import DynamicResearchToolSelector, ResearchToolRegistry
from .state import ResearchState

_ACTIONS = Literal[
    "auto",
    "literature_search",
    "todo_create",
    "todo_update",
    "todo_list",
    "notepad_write",
    "notepad_read",
    "memory_store",
    "memory_search",
    "scope_create",
    "scope_switch",
    "scope_interrupt",
    "scope_resume",
    "scope_complete",
]


class HarnessIntentPlan(BaseModel):
    """Bounded model proposal; policy intersection happens after validation."""

    action: _ACTIONS = "auto"
    tool_hints: list[str] = Field(default_factory=list, max_length=3)
    reason_code: str = Field(default="MODEL_PLAN", max_length=64)


@dataclass(frozen=True)
class ResearchTools:
    scope_access: ResearchScopePort
    paper_search: PaperSearchPort
    workspace: ResearchWorkspacePort
    structured_llm: StructuredLLMPort | None = None
    prompt_assembler: ResearchPromptAssembler = field(default_factory=ResearchPromptAssembler.default)
    context_manager: ResearchContextManager = field(default_factory=ResearchContextManager)
    tool_registry: ResearchToolRegistry = field(default_factory=ResearchToolRegistry.default)


def _node_update(
    state: Mapping[str, Any],
    node: str,
    started: float,
    *,
    status: str = "ok",
    **updates: Any,
) -> dict[str, Any]:
    duration_ms = (time.monotonic() - started) * 1000
    detail = dict(updates.pop("trace_detail", {}))
    if node == "response":
        updates["status"] = status
    trace = [
        *state.get("trace", []),
        {"node": node, "status": status, "duration_ms": round(duration_ms, 3), **detail},
    ]
    record_node(
        node=node,
        status=status,
        duration_ms=duration_ms,
        trace_id=str(state.get("trace_id", "")),
        run_id=str(state.get("run_id", "")),
    )
    return {**updates, "trace": trace}


def build_research_workflow(tools: ResearchTools):
    selector = DynamicResearchToolSelector(tools.tool_registry)
    executor = ReliableToolExecutor(registry=tools.tool_registry)

    async def validate_scope(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        query = sanitize_query(state.get("query", "")).strip()
        meaningful_query = re.sub(r"\[REDACTED\]|[\W_]", "", query, flags=re.IGNORECASE)
        errors = list(state.get("errors", []))
        if not state.get("course_id", "").isdigit():
            errors.append("RESEARCH_INVALID_COURSE_SCOPE")
        if len(meaningful_query) < 2:
            errors.append("RESEARCH_QUERY_TOO_SHORT")
        authorized = False
        if not errors:
            access = await tools.scope_access.authorize(
                course_id=state.get("course_id", ""),
                actor_user_id=state.get("actor_user_id", ""),
                permission="course.question.ask",
            )
            authorized = bool(access.get("allowed"))
            if not authorized:
                errors.append("RESEARCH_SCOPE_DENIED")
        return _node_update(
            state,
            "scope_validator",
            started,
            status="ok" if not errors else "denied",
            query=query[:300],
            errors=errors,
            granted_permissions=["course.question.ask"] if authorized else [],
            trace_detail={"accepted": not errors, "authorized": authorized},
        )

    def route_after_scope(state: ResearchState) -> str:
        return "response" if state.get("errors") else "workspace_hydrate"

    async def hydrate_workspace(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        try:
            workspace_id = str(state.get("workspace_id") or "")
            if not workspace_id:
                workspace = await tools.workspace.get_or_create_workspace(
                    course_id=int(state["course_id"]),
                    actor_user_id=state["actor_user_id"],
                    title="科研工作台",
                )
                workspace_id = str(workspace["workspace_id"])
            snapshot = await tools.workspace.get_workspace_snapshot(
                workspace_id=workspace_id,
                course_id=int(state["course_id"]),
                actor_user_id=state["actor_user_id"],
            )
            return _node_update(
                state,
                "workspace_hydrate",
                started,
                workspace_id=workspace_id,
                active_scope_id=snapshot.get("active_scope_id"),
                workspace_snapshot=dict(snapshot),
                context_budget_tokens=min(
                    64_000,
                    max(32, int(state.get("context_budget_tokens") or snapshot.get("context_budget_tokens") or 4_000)),
                ),
                trace_detail={"workspace_status": snapshot.get("status", "unknown")},
            )
        except Exception as error:  # noqa: BLE001 - graph must fail closed
            return _node_update(
                state,
                "workspace_hydrate",
                started,
                status="failed",
                errors=[*state.get("errors", []), _safe_error_code(error, "RESEARCH_WORKSPACE_UNAVAILABLE")],
            )

    async def assess_context(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        snapshot = state.get("workspace_snapshot") or {}
        active_scope_id = snapshot.get("active_scope_id")
        context_warnings = list(state.get("warnings", []))
        context_degraded = list(state.get("degraded_services", []))
        memory_error_type = ""
        items: list[dict[str, Any]] = []
        sequence = 0
        for todo in snapshot.get("todos", []):
            if todo.get("scope_id") not in {None, active_scope_id}:
                continue
            sequence += 1
            items.append({
                "item_id": todo.get("todo_id", f"todo-{sequence}"),
                "kind": "todo",
                "content": f"[{todo.get('status')}] {todo.get('title')} {todo.get('description', '')}".strip(),
                "sequence": sequence,
                "importance": 0.6 + 0.1 * int(todo.get("priority", 1)),
            })
        for note in snapshot.get("notes", []):
            if note.get("scope_id") not in {None, active_scope_id}:
                continue
            sequence += 1
            items.append({
                "item_id": note.get("note_id", f"note-{sequence}"),
                "kind": "notepad",
                "content": f"{note.get('title', '')}\n{note.get('content', '')}".strip(),
                "sequence": sequence,
                "importance": 0.8,
            })
        for scope in snapshot.get("scopes", []):
            if scope.get("scope_id") != active_scope_id:
                continue
            sequence += 1
            items.append({
                "item_id": scope.get("scope_id", f"scope-{sequence}"),
                "kind": "scope",
                "content": f"{scope.get('objective', '')}\n{scope.get('context_summary', '')}".strip(),
                "sequence": sequence,
                "importance": 1.0,
            })
        if snapshot.get("short_term_summary"):
            sequence += 1
            items.append({
                "item_id": "workspace-short-term",
                "kind": "short_term_memory",
                "content": snapshot["short_term_summary"],
                "sequence": sequence,
                "importance": 0.9,
            })
        if snapshot.get("memories"):
            try:
                memory_result = await tools.workspace.search_memory(
                    workspace_id=state["workspace_id"],
                    course_id=int(state["course_id"]),
                    actor_user_id=state["actor_user_id"],
                    query=state.get("query", ""),
                    limit=6,
                )
                for memory in memory_result.get("items", []):
                    if memory.get("scope_id") not in {None, active_scope_id}:
                        continue
                    sequence += 1
                    items.append({
                        "item_id": memory.get("memory_id", f"memory-{sequence}"),
                        "kind": "long_term_memory",
                        "content": memory.get("content", ""),
                        "sequence": sequence,
                        "importance": memory.get("importance", 0.5),
                    })
            except Exception as error:  # noqa: BLE001 - remaining context is still usable
                memory_error_type = type(error).__name__
                context_warnings.append("RESEARCH_CONTEXT_MEMORY_DEGRADED")
                context_degraded.append("research_context_memory")
        raw_tokens = sum(max(1, math.ceil(len(item["content"]) / 3)) for item in items if item["content"])
        return _node_update(
            state,
            "context_assess",
            started,
            context_items=items,
            raw_context_tokens=raw_tokens,
            warnings=context_warnings,
            degraded_services=context_degraded,
            trace_detail={
                "item_count": len(items),
                "raw_tokens": raw_tokens,
                "budget_tokens": state.get("context_budget_tokens", 4_000),
                "memory_error_type": memory_error_type,
            },
        )

    def route_context(state: ResearchState) -> str:
        return (
            "context_compress"
            if int(state.get("raw_context_tokens", 0)) > int(state.get("context_budget_tokens", 4_000))
            else "context_select"
        )

    async def prepare_context(state: ResearchState, *, node: str) -> dict[str, Any]:
        started = time.monotonic()
        base = tools.context_manager
        manager = ResearchContextManager(
            max_tokens=max(32, int(state.get("context_budget_tokens", base.max_tokens))),
            chunk_chars=base.chunk_chars,
            chunk_overlap=base.chunk_overlap,
            preserve_recent=base.preserve_recent,
            summarizer=base.summarizer,
        )
        prepared = await manager.prepare(
            query=state.get("query", ""),
            items=[ContextItem(**item) for item in state.get("context_items", []) if item.get("content")],
        )
        return _node_update(
            state,
            node,
            started,
            context_text=prepared.text or "无已保存上下文。",
            context_meta={
                "selected_item_ids": list(prepared.selected_item_ids),
                "dropped_item_ids": list(prepared.dropped_item_ids),
                "estimated_tokens": prepared.estimated_tokens,
                "budget_tokens": prepared.budget_tokens,
                "compressed": prepared.compressed,
                "compression_method": prepared.compression_method,
            },
            trace_detail={
                "compressed": prepared.compressed,
                "estimated_tokens": prepared.estimated_tokens,
            },
        )

    async def context_select(state: ResearchState) -> dict[str, Any]:
        return await prepare_context(state, node="context_select")

    async def context_compress(state: ResearchState) -> dict[str, Any]:
        return await prepare_context(state, node="context_compress")

    async def assemble_prompt(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        action = state.get("requested_action", "auto")
        task = _prompt_task(action)
        scope_title = _active_scope_title(state.get("workspace_snapshot") or {})
        allowed = set(state.get("allowed_tool_names") or [spec.name for spec in tools.tool_registry.list()])
        manifest = "\n".join(
            f"- {spec.name}: {spec.description}"
            for spec in tools.tool_registry.list()
            if spec.name in allowed
        ) or "无"
        try:
            bundle = tools.prompt_assembler.assemble(
                role="evidence_researcher",
                task=task,
                variables={
                    "scope_title": scope_title,
                    "research_question": state.get("query", ""),
                    "context": state.get("context_text", "无已保存上下文。"),
                    "tool_manifest": manifest,
                },
            )
        except PromptTemplateError as error:
            return _node_update(
                state,
                "prompt_assemble",
                started,
                status="failed",
                errors=[*state.get("errors", []), _safe_error_code(error, "RESEARCH_PROMPT_INVALID")],
            )
        return _node_update(
            state,
            "prompt_assemble",
            started,
            prompt_version=bundle.version,
            prompt_hash=bundle.prompt_hash,
            prompt_role=bundle.role,
            prompt_task=bundle.task,
            trace_detail={"prompt_version": bundle.version},
        )

    async def plan_intent(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        requested = state.get("requested_action", "auto") or "auto"
        if requested != "auto" or tools.structured_llm is None:
            return _node_update(
                state,
                "intent_planner",
                started,
                status="skipped",
                planner_action=requested,
                planner_tool_hints=[],
                trace_detail={"reason": "explicit_action" if requested != "auto" else "llm_unavailable"},
            )
        # Re-render inside the model node so the full prompt remains ephemeral
        # and never becomes a checkpoint/audit state field.
        allowed = set(state.get("allowed_tool_names") or [spec.name for spec in tools.tool_registry.list()])
        manifest = "\n".join(
            f"- {spec.name}: {spec.description}"
            for spec in tools.tool_registry.list()
            if spec.name in allowed
        ) or "无"
        bundle = tools.prompt_assembler.assemble(
            role=state.get("prompt_role", "evidence_researcher"),
            task=state.get("prompt_task", "research_request"),
            variables={
                "scope_title": _active_scope_title(state.get("workspace_snapshot") or {}),
                "research_question": state.get("query", ""),
                "context": state.get("context_text", "无已保存上下文。"),
                "tool_manifest": manifest,
            },
        )
        try:
            response = await tools.structured_llm.complete(
                messages=[{"role": "system", "content": bundle.prompt}],
                output_schema=HarnessIntentPlan,
                options=LLMOptions(
                    temperature=0.0,
                    max_tokens=240,
                    timeout_seconds=8.0,
                    response_format={"type": "json_object"},
                    prompt_version=bundle.version,
                ),
                trace_context=LLMTraceContext(
                    run_id=state.get("run_id", ""),
                    trace_id=state.get("trace_id", ""),
                    course_id=state.get("course_id", ""),
                    agent_type="research",
                    node="intent_planner",
                    purpose="route_research_harness_task",
                ),
            )
            plan = response.parsed
            if not isinstance(plan, HarnessIntentPlan):
                raise TypeError("structured plan missing")
            hints = [name for name in plan.tool_hints if tools.tool_registry.get(name) is not None]
            return _node_update(
                state,
                "intent_planner",
                started,
                planner_action=plan.action,
                planner_tool_hints=hints,
                trace_detail={"reason_code": plan.reason_code, "tool_hint_count": len(hints)},
            )
        except Exception as error:  # noqa: BLE001 - deterministic selector is the declared fallback
            return _node_update(
                state,
                "intent_planner",
                started,
                status="degraded",
                planner_action="auto",
                planner_tool_hints=[],
                warnings=[*state.get("warnings", []), "RESEARCH_INTENT_PLANNER_DEGRADED"],
                degraded_services=[*state.get("degraded_services", []), "research_intent_planner"],
                trace_detail={"error_type": type(error).__name__},
            )

    async def select_tools(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        allowed = set(state.get("allowed_tool_names") or [spec.name for spec in tools.tool_registry.list()])
        if state.get("planner_tool_hints"):
            allowed &= set(state["planner_tool_hints"])
        selection = selector.select(
            message=state.get("query", ""),
            requested_action=state.get("planner_action") or state.get("requested_action", "auto"),
            context_kinds={item.get("kind", "") for item in state.get("context_items", [])},
            allowed_tool_names=allowed,
            granted_permissions=set(state.get("granted_permissions", [])),
        )
        return _node_update(
            state,
            "tool_selector",
            started,
            selected_tools=list(selection.selected_tool_names),
            denied_tools=list(selection.denied_tool_names),
            tool_scores=dict(selection.scores),
            tool_selection_reason=selection.reason_code,
            planner_action=selection.primary_intent,
            trace_detail={
                "selected_count": len(selection.selected_tool_names),
                "denied_count": len(selection.denied_tool_names),
                "reason_code": selection.reason_code,
            },
        )

    async def route_tools(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        action = state.get("planner_action") or state.get("requested_action", "auto")
        if state.get("errors"):
            route = "invalid"
        elif not state.get("selected_tools"):
            route = "clarify"
        elif action == "literature_search":
            route = "literature"
        elif action.startswith("todo_"):
            route = "todo"
        elif action.startswith("notepad_"):
            route = "notepad"
        elif action.startswith("memory_"):
            route = "memory"
        elif action.startswith("scope_"):
            route = "scope"
        else:
            route = "clarify"
        return _node_update(
            state,
            "route_tools",
            started,
            graph_route=route,
            trace_detail={"route": route},
        )

    def tool_route(state: ResearchState) -> str:
        return state.get("graph_route", "clarify")

    async def reauthorize_tool(state: ResearchState) -> bool:
        access = await tools.scope_access.authorize(
            course_id=state.get("course_id", ""),
            actor_user_id=state.get("actor_user_id", ""),
            permission="course.question.ask",
        )
        return bool(access.get("allowed"))

    async def literature_search(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        if not await reauthorize_tool(state):
            return _tool_denied(state, "literature_search", started)
        execution = await executor.execute(
            "paper_search",
            lambda: tools.paper_search.search(
                query=state.get("query", ""),
                limit=state.get("max_results", 8),
                cursor=state.get("cursor"),
            ),
        )
        if execution.status != "success":
            return _node_update(
                state,
                "literature_search",
                started,
                status=execution.status,
                search_result={"status": "upstream_unavailable", "items": [], "provider": "arxiv"},
                papers=[],
                tool_error_code=execution.error_code,
                warnings=[*state.get("warnings", []), execution.error_code],
                degraded_services=[*state.get("degraded_services", []), "arxiv"],
                trace_detail={"attempts": execution.attempts},
            )
        result = dict(execution.value or {})
        warnings = [*state.get("warnings", []), *result.get("warnings", [])]
        degraded = list(state.get("degraded_services", []))
        if result.get("status") == "upstream_unavailable":
            degraded.append("arxiv")
        return _node_update(
            state,
            "literature_search",
            started,
            search_result=result,
            papers=[dict(item) for item in result.get("items", []) if isinstance(item, Mapping)],
            warnings=warnings,
            degraded_services=degraded,
            tool_result={"provider": result.get("provider", "arxiv"), "total": len(result.get("items", []))},
            trace_detail={
                "provider": result.get("provider", "unknown"),
                "provider_status": result.get("status", "unknown"),
                "result_count": len(result.get("items", [])),
                "attempts": execution.attempts,
            },
        )

    async def evidence_gate(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        gated: list[dict[str, Any]] = []
        rejected = 0
        for paper in state.get("papers", []):
            if not paper.get("paper_id") or not paper.get("source_url") or not paper.get("title"):
                rejected += 1
                continue
            gated.append({
                **paper,
                "evidence_status": "metadata_only",
                "is_supplementary": True,
                "cannot_modify_mastery": True,
                "cannot_modify_recommendation": True,
                "cannot_modify_graph": True,
            })
        warnings = list(state.get("warnings", []))
        if rejected:
            warnings.append("RESEARCH_INCOMPLETE_METADATA_REJECTED")
        return _node_update(
            state,
            "evidence_gate",
            started,
            papers=gated,
            warnings=warnings,
            trace_detail={"accepted": len(gated), "rejected": rejected},
        )

    async def todo_action(state: ResearchState) -> dict[str, Any]:
        return await _workspace_tool_action(state, "todo_action", "todo_manager", _run_todo)

    async def _run_todo(state: ResearchState):
        payload = dict(state.get("action_payload") or {})
        common = _workspace_args(state)
        action = state.get("planner_action", "todo_create")
        if action == "todo_create":
            return await tools.workspace.create_todo(
                **common,
                scope_id=payload.get("scope_id") or state.get("active_scope_id"),
                title=payload.get("title") or state.get("query", ""),
                description=payload.get("description", ""),
                priority=payload.get("priority", 1),
            )
        if action == "todo_update":
            return await tools.workspace.update_todo(
                **common,
                todo_id=payload.get("todo_id", ""),
                status=payload.get("status"),
                title=payload.get("title"),
                description=payload.get("description"),
                priority=payload.get("priority"),
                position=payload.get("position"),
                expected_version=payload.get("expected_version"),
            )
        return list((state.get("workspace_snapshot") or {}).get("todos", []))

    async def notepad_action(state: ResearchState) -> dict[str, Any]:
        return await _workspace_tool_action(state, "notepad_action", "notepad", _run_notepad)

    async def _run_notepad(state: ResearchState):
        payload = dict(state.get("action_payload") or {})
        if state.get("planner_action") == "notepad_read":
            return list((state.get("workspace_snapshot") or {}).get("notes", []))
        return await tools.workspace.save_note(
            **_workspace_args(state),
            scope_id=payload.get("scope_id") or state.get("active_scope_id"),
            note_id=payload.get("note_id"),
            title=payload.get("title") or "研究笔记",
            content=payload.get("content") or state.get("query", ""),
            tags=payload.get("tags") or [],
            expected_version=payload.get("expected_version"),
        )

    async def memory_action(state: ResearchState) -> dict[str, Any]:
        return await _workspace_tool_action(state, "memory_action", "memory", _run_memory)

    async def _run_memory(state: ResearchState):
        payload = dict(state.get("action_payload") or {})
        if state.get("planner_action") == "memory_store":
            return await tools.workspace.store_memory(
                **_workspace_args(state),
                scope_id=payload.get("scope_id") or state.get("active_scope_id"),
                tier=payload.get("tier", "long_term"),
                content=payload.get("content") or state.get("query", ""),
                importance=payload.get("importance", 0.5),
            )
        return await tools.workspace.search_memory(
            **_workspace_args(state),
            query=payload.get("query") or state.get("query", ""),
            limit=payload.get("limit", 8),
        )

    async def scope_action(state: ResearchState) -> dict[str, Any]:
        return await _workspace_tool_action(state, "scope_action", "scope_manager", _run_scope)

    async def _run_scope(state: ResearchState):
        payload = dict(state.get("action_payload") or {})
        action = state.get("planner_action", "scope_create")
        if action == "scope_create":
            return await tools.workspace.create_scope(
                **_workspace_args(state),
                parent_scope_id=payload.get("parent_scope_id") or state.get("active_scope_id"),
                title=payload.get("title") or state.get("query", ""),
                objective=payload.get("objective", ""),
                activate=bool(payload.get("activate", True)),
            )
        transition = action.removeprefix("scope_")
        return await tools.workspace.transition_scope(
            **_workspace_args(state),
            scope_id=payload.get("scope_id") or state.get("active_scope_id") or "",
            action=transition,
            context_summary=payload.get("context_summary"),
        )

    async def _workspace_tool_action(state, node, tool_name, operation):
        started = time.monotonic()
        if not await reauthorize_tool(state):
            return _tool_denied(state, node, started)
        execution = await executor.execute(tool_name, lambda: operation(state))
        if execution.status != "success":
            return _node_update(
                state,
                node,
                started,
                status=execution.status,
                tool_result=None,
                tool_error_code=execution.error_code,
                warnings=[*state.get("warnings", []), execution.error_code],
                trace_detail={"attempts": execution.attempts, "error_type": execution.error_type},
            )
        return _node_update(
            state,
            node,
            started,
            tool_result=execution.value,
            trace_detail={"attempts": execution.attempts},
        )

    async def refresh_workspace(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        try:
            snapshot = await tools.workspace.get_workspace_snapshot(**_workspace_args(state))
            return _node_update(
                state,
                "workspace_refresh",
                started,
                workspace_snapshot=dict(snapshot),
                active_scope_id=snapshot.get("active_scope_id"),
            )
        except Exception as error:  # noqa: BLE001 - completed tool result remains available
            return _node_update(
                state,
                "workspace_refresh",
                started,
                status="degraded",
                warnings=[*state.get("warnings", []), "RESEARCH_WORKSPACE_REFRESH_FAILED"],
                degraded_services=[*state.get("degraded_services", []), "research_workspace_refresh"],
                trace_detail={"error_type": type(error).__name__},
            )

    async def build_response(state: ResearchState) -> dict[str, Any]:
        started = time.monotonic()
        result = state.get("search_result") or {}
        route = state.get("graph_route", "invalid")
        if state.get("errors"):
            status = "invalid_request"
            answer = "研究范围、工作区或请求内容无效，请检查后重试。"
        elif state.get("tool_error_code"):
            status = "degraded" if route == "literature" else "failed"
            answer = "研究工具未完成执行；系统已保留现有工作区状态。"
        elif route == "clarify":
            status = "clarification_required"
            answer = "尚未识别出可安全执行的研究任务，请明确要检索、记待办、写笔记、查记忆或切换子任务。"
        elif route == "literature" and result.get("status") == "upstream_unavailable":
            status = "degraded"
            answer = "arXiv 当前不可用，未生成或伪造任何论文结果。"
        elif route == "literature" and not state.get("papers"):
            status = "no_results"
            answer = "没有找到带完整来源元数据的论文，请调整检索词。"
        elif route == "literature":
            status = "success"
            answer = f"找到 {len(state['papers'])} 篇 arXiv 论文元数据；这些结果仍需全文核验。"
        else:
            status = "success"
            answer = "科研工作区已更新。"
        return _node_update(
            state,
            "response",
            started,
            status=status,
            final_answer=answer,
            trace_detail={"response_status": status},
        )

    graph = StateGraph(ResearchState)
    graph.add_node("scope_validator", validate_scope)
    graph.add_node("workspace_hydrate", hydrate_workspace)
    graph.add_node("context_assess", assess_context)
    graph.add_node("context_select", context_select)
    graph.add_node("context_compress", context_compress)
    graph.add_node("prompt_assemble", assemble_prompt)
    graph.add_node("intent_planner", plan_intent)
    graph.add_node("tool_selector", select_tools)
    graph.add_node("route_tools", route_tools)
    graph.add_node("literature_search", literature_search)
    graph.add_node("evidence_gate", evidence_gate)
    graph.add_node("todo_action", todo_action)
    graph.add_node("notepad_action", notepad_action)
    graph.add_node("memory_action", memory_action)
    graph.add_node("scope_action", scope_action)
    graph.add_node("workspace_refresh", refresh_workspace)
    graph.add_node("response", build_response)

    graph.add_edge(START, "scope_validator")
    graph.add_conditional_edges(
        "scope_validator",
        route_after_scope,
        {"workspace_hydrate": "workspace_hydrate", "response": "response"},
    )
    graph.add_edge("workspace_hydrate", "context_assess")
    graph.add_conditional_edges(
        "context_assess",
        route_context,
        {"context_select": "context_select", "context_compress": "context_compress"},
    )
    graph.add_edge("context_select", "prompt_assemble")
    graph.add_edge("context_compress", "prompt_assemble")
    graph.add_edge("prompt_assemble", "intent_planner")
    graph.add_edge("intent_planner", "tool_selector")
    graph.add_edge("tool_selector", "route_tools")
    graph.add_conditional_edges(
        "route_tools",
        tool_route,
        {
            "literature": "literature_search",
            "todo": "todo_action",
            "notepad": "notepad_action",
            "memory": "memory_action",
            "scope": "scope_action",
            "clarify": "response",
            "invalid": "response",
        },
    )
    graph.add_edge("literature_search", "evidence_gate")
    graph.add_edge("evidence_gate", "workspace_refresh")
    graph.add_edge("todo_action", "workspace_refresh")
    graph.add_edge("notepad_action", "workspace_refresh")
    graph.add_edge("memory_action", "workspace_refresh")
    graph.add_edge("scope_action", "workspace_refresh")
    graph.add_edge("workspace_refresh", "response")
    graph.add_edge("response", END)
    return graph.compile()


def _workspace_args(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "workspace_id": state.get("workspace_id", ""),
        "course_id": int(state.get("course_id", 0)),
        "actor_user_id": state.get("actor_user_id", ""),
    }


def _tool_denied(state: Mapping[str, Any], node: str, started: float) -> dict[str, Any]:
    return _node_update(
        state,
        node,
        started,
        status="denied",
        tool_error_code="RESEARCH_TOOL_PERMISSION_DENIED",
        warnings=[*state.get("warnings", []), "RESEARCH_TOOL_PERMISSION_DENIED"],
    )


def _prompt_task(action: str) -> str:
    if action.startswith("todo_"):
        return "todo_management"
    if action.startswith("notepad_"):
        return "notepad"
    if action.startswith("memory_"):
        return "memory"
    if action.startswith("scope_"):
        return "scope_management"
    if action == "literature_search":
        return "literature_search"
    return "research_request"


def _active_scope_title(snapshot: Mapping[str, Any]) -> str:
    active = snapshot.get("active_scope_id")
    for scope in snapshot.get("scopes", []):
        if scope.get("scope_id") == active:
            return str(scope.get("title") or "主研究作用域")
    return "主研究作用域"


def _safe_error_code(error: BaseException, fallback: str) -> str:
    value = str(error).strip()
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", value) else fallback


__all__ = ["HarnessIntentPlan", "ResearchTools", "build_research_workflow"]
