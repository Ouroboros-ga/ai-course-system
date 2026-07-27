"""A controlled single-agent teaching graph with explicit deterministic branches.

阶段9 改造：在每个可选工具节点前插入 ToolGovernance 检查；高风险动作通过
TeacherSafetyValve 生成提案，等待教师决策。被禁用的工具跳过执行并记录到
governance_skipped_tools；沙箱不可用时 CodingAction 标记不可用而非虚构执行。
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from langgraph.graph import END, START, StateGraph

from ..contracts import TeachingTools
from ..errors import LLMUnavailableError, RequestValidationError, ScopeRejectedError
from ..policies.teaching_action import decide_teaching_action
from ..state import TeachingState


def _trace(state: Mapping[str, Any], node: str, **detail: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **detail}]


def _degrade(state: Mapping[str, Any], service: str, code: str) -> dict[str, Any]:
    return {
        "warnings": [*state.get("warnings", []), code],
        "degraded_services": [*state.get("degraded_services", []), service],
    }


async def _governance_check(tools: TeachingTools, state: TeachingState, tool_name: str) -> tuple[bool, dict[str, Any]]:
    """检查工具是否被教师策略启用；未注入治理端口时默认允许。

    返回 (允许执行, 治理元数据)；被禁用时记录到 governance_skipped_tools。
    """
    if tools.tool_governance is None:
        return True, {}
    try:
        allowed = await tools.tool_governance.is_tool_enabled(
            course_id=state["course_id"], tool_name=tool_name,
        )
        meta: dict[str, Any] = {"allowed": allowed}
        if not allowed:
            skipped = [*state.get("governance_skipped_tools", []), tool_name]
            meta["skipped"] = skipped
        return allowed, meta
    except Exception:  # noqa: BLE001 -- 治理失败不阻断主流程
        return True, {}


async def _record_invocation(
    tools: TeachingTools, state: TeachingState, tool_name: str,
    input_summary: dict[str, Any], output_summary: dict[str, Any],
    duration_ms: int | None = None, degraded: bool = False, degraded_reason: str = "",
    allowed_by_policy: bool = True,
) -> None:
    """记录工具调用审计；失败不阻断主流程。"""
    if tools.tool_governance is None:
        return
    try:
        await tools.tool_governance.record_invocation(
            course_id=state["course_id"], student_id=state["student_id"],
            trace_id=state["trace_id"], tool_name=tool_name,
            input_summary=input_summary, output_summary=output_summary,
            duration_ms=duration_ms, degraded=degraded,
            degraded_reason=degraded_reason, allowed_by_policy=allowed_by_policy,
        )
    except Exception:  # noqa: BLE001
        pass


def build_teaching_workflow(tools: TeachingTools):
    async def load_session_context(state: TeachingState) -> dict[str, Any]:
        if tools.conversation_context is None:
            return {"trace": _trace(state, "load_session_context", skipped=True)}
        try:
            context = await tools.conversation_context.load_context(
                student_id=state["student_id"], course_id=state["course_id"], session_id=state["session_id"],
            )
            return {"session_context": dict(context) if context else None, "trace": _trace(state, "load_session_context", available=context is not None)}
        except Exception as error:
            payload = _degrade(state, "conversation_context", "SESSION_CONTEXT_UNAVAILABLE")
            payload.update({"trace": _trace(state, "load_session_context", error=type(error).__name__)})
            return payload

    async def validate_request(state: TeachingState) -> dict[str, Any]:
        try:
            if not all(str(state.get(field, "")).strip() for field in ("student_id", "course_id", "session_id", "user_message")):
                raise RequestValidationError("student_id, course_id, session_id and user_message are required")
            if len(str(state["user_message"])) > 4000:
                raise RequestValidationError("user_message exceeds 4000 characters")
            decision = await tools.scope.validate_scope(student_id=state["student_id"], course_id=state["course_id"], resource_id=state.get("current_resource_id"))
            if not decision.get("allowed", False):
                raise ScopeRejectedError(str(decision.get("reason", "scope_not_allowed")))
            return {"trace": _trace(state, "validate_request", scope="accepted")}
        except (RequestValidationError, ScopeRejectedError) as error:
            return {"errors": [*state.get("errors", []), error.code], "status": "rejected", "trace": _trace(state, "validate_request", error=error.code)}

    async def detect_intent(state: TeachingState) -> dict[str, Any]:
        try:
            result = await tools.llm.detect_intent(message=state["user_message"], course_id=state["course_id"])
            intent = str(result.get("intent", "course_question"))
            confidence = float(result.get("confidence", 0.0))
            candidates = await tools.llm.extract_concept_candidates(message=state["user_message"], course_id=state["course_id"])
            return {"intent": intent, "intent_confidence": confidence, "concept_candidates": [dict(item) for item in candidates], "trace": _trace(state, "detect_intent", intent=intent)}
        except Exception as error:
            return {"errors": [*state.get("errors", []), LLMUnavailableError.code], "status": "llm_unavailable", "trace": _trace(state, "detect_intent", error=type(error).__name__)}

    async def resolve_concept(state: TeachingState) -> dict[str, Any]:
        # 阶段9：ToolGovernance 检查
        allowed, gov_meta = await _governance_check(tools, state, "graph")
        if not allowed:
            return {
                "concept_grounding_confidence": 0.0,
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "resolve_concept", governance="disabled"),
            }
        start = time.monotonic()
        try:
            matches = await tools.knowledge_graph.resolve_concepts(course_id=state["course_id"], message=state["user_message"], candidates=state.get("concept_candidates", []), resource_id=state.get("current_resource_id"))
            selected = dict(matches[0]) if matches else {}
            await _record_invocation(tools, state, "graph",
                input_summary={"message_length": len(str(state.get("user_message", "")))},
                output_summary={"concept_id": selected.get("concept_id"), "candidate_count": len(matches)},
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return {"concept_candidates": [dict(item) for item in matches], "current_concept_id": selected.get("concept_id"), "concept_grounding_confidence": float(selected.get("confidence", 0.0)), "trace": _trace(state, "resolve_concept", resolved=bool(selected))}
        except Exception as error:
            payload = _degrade(state, "knowledge_graph", "KNOWLEDGE_GRAPH_UNAVAILABLE")
            payload.update({"concept_grounding_confidence": 0.0, "trace": _trace(state, "resolve_concept", error=type(error).__name__)})
            await _record_invocation(tools, state, "graph",
                input_summary={"message_length": len(str(state.get("user_message", "")))},
                output_summary={}, degraded=True, degraded_reason="KNOWLEDGE_GRAPH_UNAVAILABLE",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return payload

    async def load_student_state(state: TeachingState) -> dict[str, Any]:
        try:
            concept_id = str(state["current_concept_id"])
            learner, weak = await tools.student_modeling.get_concept_state(student_id=state["student_id"], course_id=state["course_id"], concept_id=concept_id), await tools.student_modeling.get_weak_concepts(student_id=state["student_id"], course_id=state["course_id"])
            return {"student_concept_state": dict(learner), "weak_concepts": [dict(item) for item in weak], "trace": _trace(state, "load_student_state", available=True)}
        except Exception as error:
            payload = _degrade(state, "student_modeling", "STUDENT_MODELING_UNAVAILABLE")
            payload.update({"student_concept_state": {}, "weak_concepts": [], "trace": _trace(state, "load_student_state", error=type(error).__name__)})
            return payload

    async def load_cognitive_state(state: TeachingState) -> dict[str, Any]:
        # 批次4可选节点：未注入 CognitionPort 时直接跳过，不影响现有流程
        if tools.cognition is None:
            return {"trace": _trace(state, "load_cognitive_state", skipped=True)}
        # 阶段9：ToolGovernance 检查
        allowed, gov_meta = await _governance_check(tools, state, "cognition")
        if not allowed:
            return {
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "load_cognitive_state", governance="disabled"),
            }
        try:
            node_id = state.get("current_concept_id")
            cognitive_state = await tools.cognition.get_state(
                student_id=state["student_id"], course_id=state["course_id"], node_id=node_id,
            )
            cognitive_rec = await tools.cognition.get_recommendation(
                student_id=state["student_id"], course_id=state["course_id"], node_id=node_id,
            )
            return {
                "cognitive_state": dict(cognitive_state) if cognitive_state else None,
                "cognitive_recommendation": dict(cognitive_rec) if cognitive_rec else None,
                "trace": _trace(state, "load_cognitive_state", available=cognitive_state is not None),
            }
        except Exception as error:
            payload = _degrade(state, "cognition", "COGNITION_PORT_UNAVAILABLE")
            payload.update({"trace": _trace(state, "load_cognitive_state", error=type(error).__name__)})
            return payload

    async def load_graph_context(state: TeachingState) -> dict[str, Any]:
        # 阶段9：ToolGovernance 检查（graph 工具复用）
        allowed, gov_meta = await _governance_check(tools, state, "graph")
        if not allowed:
            return {
                "graph_context": {}, "prerequisites": [], "successors": [],
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "load_graph_context", governance="disabled"),
            }
        try:
            graph = dict(await tools.knowledge_graph.get_context(course_id=state["course_id"], concept_id=str(state["current_concept_id"])))
            return {"graph_context": graph, "prerequisites": list(graph.get("prerequisites", [])), "successors": list(graph.get("successors", [])), "trace": _trace(state, "load_graph_context", graph_version=graph.get("graph_version"))}
        except Exception as error:
            payload = _degrade(state, "knowledge_graph", "GRAPH_CONTEXT_UNAVAILABLE")
            payload.update({"graph_context": {}, "prerequisites": [], "successors": [], "trace": _trace(state, "load_graph_context", error=type(error).__name__)})
            return payload

    async def load_question_bank(state: TeachingState) -> dict[str, Any]:
        # 批次4可选节点：未注入 QuestionBankPort 时直接跳过
        if tools.question_bank is None:
            return {"trace": _trace(state, "load_question_bank", skipped=True)}
        # 阶段9：ToolGovernance 检查
        allowed, gov_meta = await _governance_check(tools, state, "question_bank")
        if not allowed:
            return {
                "question_bank_items": [],
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "load_question_bank", governance="disabled"),
            }
        try:
            node_id = state.get("current_concept_id")
            items = await tools.question_bank.list_questions(
                course_id=state["course_id"], node_id=node_id, limit=10,
            )
            return {
                "question_bank_items": [dict(item) for item in items],
                "trace": _trace(state, "load_question_bank", count=len(items)),
            }
        except Exception as error:
            payload = _degrade(state, "question_bank", "QUESTION_BANK_PORT_UNAVAILABLE")
            payload.update({"question_bank_items": [], "trace": _trace(state, "load_question_bank", error=type(error).__name__)})
            return payload

    async def retrieve_evidence(state: TeachingState) -> dict[str, Any]:
        # 阶段9：ToolGovernance 检查
        allowed, gov_meta = await _governance_check(tools, state, "retrieval")
        if not allowed:
            return {
                "retrieved_evidence": [],
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "retrieve_course_evidence", governance="disabled"),
            }
        start = time.monotonic()
        try:
            evidence = await tools.retrieval.retrieve_course_evidence(course_id=state["course_id"], message=state["user_message"], concept_id=state.get("current_concept_id"), resource_id=state.get("current_resource_id"))
            await _record_invocation(tools, state, "retrieval",
                input_summary={"message_length": len(str(state.get("user_message", "")))},
                output_summary={"evidence_count": len(evidence), "evidence_ids": [str(e.get("evidence_id")) for e in evidence if e.get("evidence_id")][:20]},
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return {"retrieved_evidence": [dict(item) for item in evidence], "trace": _trace(state, "retrieve_course_evidence", count=len(evidence))}
        except Exception as error:
            payload = _degrade(state, "retrieval", "COURSE_RETRIEVAL_UNAVAILABLE")
            payload.update({"retrieved_evidence": [], "trace": _trace(state, "retrieve_course_evidence", error=type(error).__name__)})
            await _record_invocation(tools, state, "retrieval",
                input_summary={}, output_summary={}, degraded=True,
                degraded_reason="COURSE_RETRIEVAL_UNAVAILABLE",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return payload

    async def research_web(state: TeachingState) -> dict[str, Any]:
        # 批次4可选节点：未注入 WebResearchPort 时直接跳过。
        # WebResearch 结果始终标记 is_supplementary=true，不修改掌握度/推荐/图谱。
        if tools.web_research is None:
            return {"trace": _trace(state, "research_web", skipped=True)}
        # 阶段9：ToolGovernance 检查
        allowed, gov_meta = await _governance_check(tools, state, "web_research")
        if not allowed:
            return {
                "web_research_results": None,
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "research_web", governance="disabled"),
            }
        # 阶段9：高风险动作通过教师安全阀生成提案
        if tools.teacher_safety_valve is not None:
            try:
                proposal = await tools.teacher_safety_valve.create_proposal(
                    course_id=state["course_id"], student_id=state["student_id"],
                    trace_id=state["trace_id"], session_id=state["session_id"],
                    proposal_type="web_research", tool_name="web_research",
                    proposed_action={"query_length": len(str(state.get("user_message", "")))},
                )
                pending = [*state.get("pending_proposals", []), dict(proposal)]
                state_updates: dict[str, Any] = {
                    "pending_proposals": pending,
                    "trace": _trace(state, "research_web", proposal_id=proposal.get("proposal_id")),
                }
                # 高风险动作 fail-closed：提案需要确认且未批准时，跳过实际 web research 执行
                if proposal.get("requires_confirmation") and proposal.get("status") == "pending":
                    state_updates["web_research_results"] = None
                    state_updates["warnings"] = [*state.get("warnings", []), "WEB_RESEARCH_PENDING_TEACHER_CONFIRMATION"]
                    return state_updates
            except Exception:  # noqa: BLE001 -- 安全阀自身失败时 fail-closed
                # 安全阀不可用时不得继续执行高风险 web research；
                # 主流程继续（Q&A 不受影响），但该高风险工具被降级跳过。
                payload = _degrade(state, "web_research", "SAFETY_VALVE_UNAVAILABLE")
                payload.update({
                    "web_research_results": None,
                    "trace": _trace(state, "research_web", safety_valve="failed"),
                })
                return payload
        try:
            result = await tools.web_research.research(
                course_id=state["course_id"],
                query=state["user_message"],
                student_id=state["student_id"],
            )
            return {
                "web_research_results": dict(result) if result else None,
                "trace": _trace(state, "research_web", available=bool(result)),
            }
        except Exception as error:
            payload = _degrade(state, "web_research", "WEB_RESEARCH_PORT_UNAVAILABLE")
            payload.update({"web_research_results": None, "trace": _trace(state, "research_web", error=type(error).__name__)})
            return payload

    async def load_sandbox_context(state: TeachingState) -> dict[str, Any]:
        submission_id = state.get("current_code_submission_id")
        if not submission_id:
            return {"trace": _trace(state, "load_sandbox_context", skipped=True)}
        # 阶段9：ToolGovernance 检查
        allowed, gov_meta = await _governance_check(tools, state, "sandbox")
        if not allowed:
            return {
                "sandbox_result": None,
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "load_sandbox_context", governance="disabled"),
            }
        try:
            result = dict(await tools.sandbox.get_execution_result(student_id=state["student_id"], course_id=state["course_id"], code_submission_id=submission_id))
            return {"sandbox_result": result, "code_diagnosis": result.get("diagnosis"), "trace": _trace(state, "load_sandbox_context", available=True)}
        except Exception as error:
            # 阶段9：沙箱不可用时 CodingAction 显示不可用而非虚构执行
            payload = _degrade(state, "sandbox", "CODE_SANDBOX_UNAVAILABLE")
            payload.update({
                "sandbox_result": None,
                "code_diagnosis": {"status": "unavailable", "reason": "CODE_SANDBOX_UNAVAILABLE"},
                "trace": _trace(state, "load_sandbox_context", error=type(error).__name__),
            })
            return payload

    async def load_coding_diagnosis(state: TeachingState) -> dict[str, Any]:
        """Load a server-owned, read-only CodingEduAgent diagnosis.

        This is teaching context only. It must never be converted into a
        LearningEvidence record or modify the six-dimensional cognition state.
        """
        if tools.coding_diagnosis is None or not state.get("current_code_submission_id"):
            return {"trace": _trace(state, "load_coding_diagnosis", skipped=True)}
        allowed, gov_meta = await _governance_check(tools, state, "coding_diagnosis")
        if not allowed:
            return {
                "coding_diagnosis": None,
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "load_coding_diagnosis", governance="disabled"),
            }
        try:
            diagnosis = await tools.coding_diagnosis.get_latest_diagnosis(
                student_id=state["student_id"], course_id=state["course_id"],
                run_id=state.get("current_code_submission_id"),
            )
            return {
                "coding_diagnosis": dict(diagnosis) if diagnosis else None,
                "trace": _trace(state, "load_coding_diagnosis", available=diagnosis is not None),
            }
        except Exception as error:  # noqa: BLE001 -- diagnosis is optional context
            payload = _degrade(state, "coding_diagnosis", "CODING_DIAGNOSIS_UNAVAILABLE")
            payload.update({
                "coding_diagnosis": None,
                "trace": _trace(state, "load_coding_diagnosis", error=type(error).__name__),
            })
            return payload

    async def load_learning_history(state: TeachingState) -> dict[str, Any]:
        """Provide bounded assessment/cognition history without chat or source code."""
        if tools.student_history is None:
            return {"trace": _trace(state, "load_learning_history", skipped=True)}
        try:
            history = await tools.student_history.get_history(
                student_id=state["student_id"], course_id=state["course_id"],
                concept_id=state.get("current_concept_id"),
            )
            return {
                "learning_history": dict(history),
                "trace": _trace(state, "load_learning_history", status=history.get("status", "unknown")),
            }
        except Exception as error:  # noqa: BLE001 -- history must not block Q&A
            payload = _degrade(state, "student_history", "STUDENT_HISTORY_UNAVAILABLE")
            payload.update({
                "learning_history": {"status": "unknown", "reason": "history_unavailable"},
                "trace": _trace(state, "load_learning_history", error=type(error).__name__),
            })
            return payload

    async def load_experiment_context(state: TeachingState) -> dict[str, Any]:
        """阶段9新增：加载课程实验上下文（按 course_id 隔离，仅 published）。"""
        if tools.experiment is None:
            return {"trace": _trace(state, "load_experiment_context", skipped=True)}
        allowed, gov_meta = await _governance_check(tools, state, "experiment")
        if not allowed:
            return {
                "experiment_items": [],
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "load_experiment_context", governance="disabled"),
            }
        try:
            items = await tools.experiment.list_experiments(
                course_id=state["course_id"], node_id=state.get("current_concept_id"), limit=10,
            )
            return {
                "experiment_items": [dict(item) for item in items],
                "trace": _trace(state, "load_experiment_context", count=len(items)),
            }
        except Exception as error:
            payload = _degrade(state, "experiment", "EXPERIMENT_PORT_UNAVAILABLE")
            payload.update({"experiment_items": [], "trace": _trace(state, "load_experiment_context", error=type(error).__name__)})
            return payload

    async def load_visualization_context(state: TeachingState) -> dict[str, Any]:
        """阶段9新增：加载算法可视化上下文（按 course_id 隔离，仅 published）。"""
        if tools.visualization is None:
            return {"trace": _trace(state, "load_visualization_context", skipped=True)}
        allowed, gov_meta = await _governance_check(tools, state, "visualization")
        if not allowed:
            return {
                "visualization_plans": [],
                "governance_skipped_tools": gov_meta.get("skipped", []),
                "trace": _trace(state, "load_visualization_context", governance="disabled"),
            }
        try:
            plans = await tools.visualization.list_published_plans(
                course_id=state["course_id"], node_id=state.get("current_concept_id"), limit=10,
            )
            return {
                "visualization_plans": [dict(item) for item in plans],
                "trace": _trace(state, "load_visualization_context", count=len(plans)),
            }
        except Exception as error:
            payload = _degrade(state, "visualization", "VISUALIZATION_PORT_UNAVAILABLE")
            payload.update({"visualization_plans": [], "trace": _trace(state, "load_visualization_context", error=type(error).__name__)})
            return payload

    async def decide_action(state: TeachingState) -> dict[str, Any]:
        action, reason = decide_teaching_action(state)
        selected: list[str] = []
        # 阶段9：沙箱不可用时 code_debugging 标记为不可用，不虚构执行
        if action == "code_debugging" and state.get("sandbox_result") is None:
            return {
                "teaching_action": "code_debugging_unavailable",
                "teaching_action_reason": "sandbox_unavailable",
                "selected_resource_ids": [],
                "warnings": [*state.get("warnings", []), "CODE_DEBUGGING_UNAVAILABLE"],
                "trace": _trace(state, "decide_teaching_action", action="code_debugging_unavailable"),
            }
        try:
            recommendation = await tools.recommendation.recommend_next_action(student_id=state["student_id"], course_id=state["course_id"], concept_id=state.get("current_concept_id"), action=action, graph_context=state.get("graph_context", {}), student_state=state.get("student_concept_state", {}))
            selected = [str(item) for item in recommendation.get("resource_ids", [])]
        except Exception as error:
            degraded = _degrade(state, "recommendation", "RECOMMENDATION_UNAVAILABLE")
            return {**degraded, "teaching_action": action, "teaching_action_reason": reason, "selected_resource_ids": [], "trace": _trace(state, "decide_teaching_action", action=action, recommendation_error=type(error).__name__)}
        return {"teaching_action": action, "teaching_action_reason": reason, "selected_resource_ids": selected, "trace": _trace(state, "decide_teaching_action", action=action)}

    async def generate_response(state: TeachingState) -> dict[str, Any]:
        try:
            generated = await tools.llm.generate_teaching_response(context={key: state.get(key) for key in ("course_id", "user_message", "intent", "current_concept_id", "student_concept_state", "graph_context", "retrieved_evidence", "teaching_action", "teaching_action_reason", "selected_resource_ids", "degraded_services", "cognitive_state", "cognitive_recommendation", "question_bank_items", "web_research_results", "session_context", "learning_history", "coding_diagnosis", "experiment_items", "visualization_plans")})
            return {"final_answer": str(generated.get("answer", "")), "citations": [dict(item) for item in generated.get("citations", [])], "trace": _trace(state, "generate_response", answer_present=bool(generated.get("answer")))}
        except Exception as error:
            return {"errors": [*state.get("errors", []), LLMUnavailableError.code], "status": "llm_unavailable", "trace": _trace(state, "generate_response", error=type(error).__name__)}

    async def validate_response(state: TeachingState) -> dict[str, Any]:
        allowed = {str(item.get("evidence_id")) for item in state.get("retrieved_evidence", []) if item.get("evidence_id")}
        citations = [item for item in state.get("citations", []) if not item.get("evidence_id") or str(item["evidence_id"]) in allowed]
        warnings = list(state.get("warnings", []))
        if len(citations) != len(state.get("citations", [])):
            warnings.append("UNSUPPORTED_CITATION_REMOVED")
        if state.get("retrieved_evidence") == []:
            citations = []
            warnings.append("NO_COURSE_EVIDENCE_AVAILABLE")
        return {"citations": citations, "warnings": warnings, "trace": _trace(state, "validate_response", citation_count=len(citations))}

    async def record_event(state: TeachingState) -> dict[str, Any]:
        # Audit/context records never carry raw question text, answer text, prompt or full trace.
        event = {"event_type": "teaching_agent_response", "trace_id": state["trace_id"], "student_id": state["student_id"], "course_id": state["course_id"], "session_id": state["session_id"], "concept_id": state.get("current_concept_id"), "teaching_action": state.get("teaching_action"), "warnings": state.get("warnings", []), "errors": state.get("errors", [])}
        replay = {
            "trace_id": state["trace_id"], "student_id": state["student_id"], "course_id": state["course_id"], "session_id": state["session_id"],
            "intent": state.get("intent"), "concept_id": state.get("current_concept_id"),
            "retrieved_evidence": state.get("retrieved_evidence", []), "warnings": state.get("warnings", []),
            "errors": state.get("errors", []), "degraded_services": state.get("degraded_services", []), "nodes": state.get("trace", []),
        }
        try:
            await tools.learning_events.record_learning_event(event=event)
            await tools.learning_events.record_agent_trace(trace=replay)
            if tools.conversation_context is not None:
                await tools.conversation_context.save_context(
                    student_id=state["student_id"], course_id=state["course_id"], session_id=state["session_id"],
                    context={"current_concept_id": state.get("current_concept_id"), "last_intent": state.get("intent"), "last_teaching_action": state.get("teaching_action"), "warnings": state.get("warnings", []), "reason_codes": state.get("errors", [])},
                )
            return {"trace": _trace(state, "record_learning_event", recorded=True)}
        except Exception as error:
            payload = _degrade(state, "learning_events", "LEARNING_EVENT_RECORDING_UNAVAILABLE")
            payload.update({"trace": _trace(state, "record_learning_event", error=type(error).__name__)})
            return payload

    def after_validation(state: TeachingState) -> str:
        return "record_learning_event" if state.get("status") == "rejected" else "load_session_context"

    def after_intent(state: TeachingState) -> str:
        return "record_learning_event" if state.get("status") == "llm_unavailable" else "resolve_concept"

    def after_resolution(state: TeachingState) -> str:
        return "load_student_state" if state.get("current_concept_id") else "retrieve_evidence"

    def after_generation(state: TeachingState) -> str:
        return "record_learning_event" if state.get("status") == "llm_unavailable" else "validate_response"

    graph = StateGraph(TeachingState)
    graph.add_node("validate_request", validate_request)
    graph.add_node("load_session_context", load_session_context)
    graph.add_node("detect_intent", detect_intent)
    graph.add_node("resolve_concept", resolve_concept)
    graph.add_node("load_student_state", load_student_state)
    graph.add_node("load_cognitive_state", load_cognitive_state)
    graph.add_node("load_graph_context", load_graph_context)
    graph.add_node("load_question_bank", load_question_bank)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("research_web", research_web)
    graph.add_node("load_sandbox_context", load_sandbox_context)
    graph.add_node("load_coding_diagnosis", load_coding_diagnosis)
    graph.add_node("load_learning_history", load_learning_history)
    # 阶段9新增：实验与可视化节点
    graph.add_node("load_experiment_context", load_experiment_context)
    graph.add_node("load_visualization_context", load_visualization_context)
    graph.add_node("decide_teaching_action", decide_action)
    graph.add_node("generate_response", generate_response)
    graph.add_node("validate_response", validate_response)
    graph.add_node("record_learning_event", record_event)
    graph.add_edge(START, "validate_request")
    graph.add_conditional_edges("validate_request", after_validation)
    graph.add_edge("load_session_context", "detect_intent")
    graph.add_conditional_edges("detect_intent", after_intent)
    graph.add_conditional_edges("resolve_concept", after_resolution)
    # 批次4：在现有链路中插入三个可选节点；端口未注入时为 no-op
    graph.add_edge("load_student_state", "load_cognitive_state")
    graph.add_edge("load_cognitive_state", "load_graph_context")
    graph.add_edge("load_graph_context", "load_question_bank")
    graph.add_edge("load_question_bank", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "research_web")
    graph.add_edge("research_web", "load_sandbox_context")
    # 阶段9：在 sandbox 之后插入 experiment/visualization 节点
    graph.add_edge("load_sandbox_context", "load_coding_diagnosis")
    graph.add_edge("load_coding_diagnosis", "load_learning_history")
    graph.add_edge("load_learning_history", "load_experiment_context")
    graph.add_edge("load_experiment_context", "load_visualization_context")
    graph.add_edge("load_visualization_context", "decide_teaching_action")
    graph.add_edge("decide_teaching_action", "generate_response")
    graph.add_conditional_edges("generate_response", after_generation)
    graph.add_edge("validate_response", "record_learning_event")
    graph.add_edge("record_learning_event", END)
    return graph.compile()
