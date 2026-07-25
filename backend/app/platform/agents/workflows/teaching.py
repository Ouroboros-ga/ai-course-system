"""A controlled single-agent teaching graph with explicit deterministic branches."""

from __future__ import annotations

from typing import Any, Mapping

from langgraph.graph import END, START, StateGraph

from ..contracts import TeachingTools
from ..errors import LLMUnavailableError, RequestValidationError, ScopeRejectedError
from ..policies.teaching_action import decide_teaching_action
from ..state import TeachingState


def _trace(state: Mapping[str, Any], node: str, **detail: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **detail}]


def _degrade(state: Mapping[str, Any], service: str, code: str) -> dict[str, Any]:
    return {"warnings": [*state.get("warnings", []), code], "degraded_services": [*state.get("degraded_services", []), service]}


def build_teaching_workflow(tools: TeachingTools):
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
        try:
            matches = await tools.knowledge_graph.resolve_concepts(course_id=state["course_id"], message=state["user_message"], candidates=state.get("concept_candidates", []), resource_id=state.get("current_resource_id"))
            selected = dict(matches[0]) if matches else {}
            return {"concept_candidates": [dict(item) for item in matches], "current_concept_id": selected.get("concept_id"), "concept_grounding_confidence": float(selected.get("confidence", 0.0)), "trace": _trace(state, "resolve_concept", resolved=bool(selected))}
        except Exception as error:
            payload = _degrade(state, "knowledge_graph", "KNOWLEDGE_GRAPH_UNAVAILABLE")
            payload.update({"concept_grounding_confidence": 0.0, "trace": _trace(state, "resolve_concept", error=type(error).__name__)})
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
        try:
            evidence = await tools.retrieval.retrieve_course_evidence(course_id=state["course_id"], message=state["user_message"], concept_id=state.get("current_concept_id"), resource_id=state.get("current_resource_id"))
            return {"retrieved_evidence": [dict(item) for item in evidence], "trace": _trace(state, "retrieve_course_evidence", count=len(evidence))}
        except Exception as error:
            payload = _degrade(state, "retrieval", "COURSE_RETRIEVAL_UNAVAILABLE")
            payload.update({"retrieved_evidence": [], "trace": _trace(state, "retrieve_course_evidence", error=type(error).__name__)})
            return payload

    async def research_web(state: TeachingState) -> dict[str, Any]:
        # 批次4可选节点：未注入 WebResearchPort 时直接跳过。
        # WebResearch 结果始终标记 is_supplementary=true，不修改掌握度/推荐/图谱。
        if tools.web_research is None:
            return {"trace": _trace(state, "research_web", skipped=True)}
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
        try:
            result = dict(await tools.sandbox.get_execution_result(student_id=state["student_id"], course_id=state["course_id"], code_submission_id=submission_id))
            return {"sandbox_result": result, "code_diagnosis": result.get("diagnosis"), "trace": _trace(state, "load_sandbox_context", available=True)}
        except Exception as error:
            payload = _degrade(state, "sandbox", "CODE_SANDBOX_UNAVAILABLE")
            payload.update({"sandbox_result": None, "trace": _trace(state, "load_sandbox_context", error=type(error).__name__)})
            return payload

    async def decide_action(state: TeachingState) -> dict[str, Any]:
        action, reason = decide_teaching_action(state)
        selected: list[str] = []
        try:
            recommendation = await tools.recommendation.recommend_next_action(student_id=state["student_id"], course_id=state["course_id"], concept_id=state.get("current_concept_id"), action=action, graph_context=state.get("graph_context", {}), student_state=state.get("student_concept_state", {}))
            selected = [str(item) for item in recommendation.get("resource_ids", [])]
        except Exception as error:
            degraded = _degrade(state, "recommendation", "RECOMMENDATION_UNAVAILABLE")
            return {**degraded, "teaching_action": action, "teaching_action_reason": reason, "selected_resource_ids": [], "trace": _trace(state, "decide_teaching_action", action=action, recommendation_error=type(error).__name__)}
        return {"teaching_action": action, "teaching_action_reason": reason, "selected_resource_ids": selected, "trace": _trace(state, "decide_teaching_action", action=action)}

    async def generate_response(state: TeachingState) -> dict[str, Any]:
        try:
            generated = await tools.llm.generate_teaching_response(context={key: state.get(key) for key in ("course_id", "user_message", "intent", "current_concept_id", "student_concept_state", "graph_context", "retrieved_evidence", "teaching_action", "teaching_action_reason", "selected_resource_ids", "degraded_services", "cognitive_state", "cognitive_recommendation", "question_bank_items", "web_research_results")})
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
        event = {"event_type": "teaching_agent_response", "trace_id": state["trace_id"], "student_id": state["student_id"], "course_id": state["course_id"], "session_id": state["session_id"], "concept_id": state.get("current_concept_id"), "teaching_action": state.get("teaching_action"), "warnings": state.get("warnings", []), "errors": state.get("errors", []), "final_answer": state.get("final_answer")}
        replay = {
            "trace_id": state["trace_id"], "input": {"student_id": state["student_id"], "course_id": state["course_id"], "session_id": state["session_id"], "message": state["user_message"], "resource_id": state.get("current_resource_id")},
            "intent": state.get("intent"), "concept_id": state.get("current_concept_id"),
            "student_concept_state": state.get("student_concept_state", {}), "graph_context": state.get("graph_context", {}),
            "retrieved_evidence": state.get("retrieved_evidence", []), "teaching_action": state.get("teaching_action"),
            "teaching_action_reason": state.get("teaching_action_reason"), "final_answer": state.get("final_answer"),
            "citations": state.get("citations", []), "warnings": state.get("warnings", []),
            "errors": state.get("errors", []), "degraded_services": state.get("degraded_services", []), "nodes": state.get("trace", []),
            "cognitive_state": state.get("cognitive_state"), "cognitive_recommendation": state.get("cognitive_recommendation"),
            "question_bank_items": state.get("question_bank_items", []), "web_research_results": state.get("web_research_results"),
        }
        try:
            await tools.learning_events.record_learning_event(event=event)
            await tools.learning_events.record_agent_trace(trace=replay)
            return {"trace": _trace(state, "record_learning_event", recorded=True)}
        except Exception as error:
            payload = _degrade(state, "learning_events", "LEARNING_EVENT_RECORDING_UNAVAILABLE")
            payload.update({"trace": _trace(state, "record_learning_event", error=type(error).__name__)})
            return payload

    def after_validation(state: TeachingState) -> str:
        return "record_learning_event" if state.get("status") == "rejected" else "detect_intent"

    def after_intent(state: TeachingState) -> str:
        return "record_learning_event" if state.get("status") == "llm_unavailable" else "resolve_concept"

    def after_resolution(state: TeachingState) -> str:
        return "load_student_state" if state.get("current_concept_id") else "retrieve_evidence"

    def after_generation(state: TeachingState) -> str:
        return "record_learning_event" if state.get("status") == "llm_unavailable" else "validate_response"

    graph = StateGraph(TeachingState)
    graph.add_node("validate_request", validate_request)
    graph.add_node("detect_intent", detect_intent)
    graph.add_node("resolve_concept", resolve_concept)
    graph.add_node("load_student_state", load_student_state)
    graph.add_node("load_cognitive_state", load_cognitive_state)
    graph.add_node("load_graph_context", load_graph_context)
    graph.add_node("load_question_bank", load_question_bank)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("research_web", research_web)
    graph.add_node("load_sandbox_context", load_sandbox_context)
    graph.add_node("decide_teaching_action", decide_action)
    graph.add_node("generate_response", generate_response)
    graph.add_node("validate_response", validate_response)
    graph.add_node("record_learning_event", record_event)
    graph.add_edge(START, "validate_request")
    graph.add_conditional_edges("validate_request", after_validation)
    graph.add_conditional_edges("detect_intent", after_intent)
    graph.add_conditional_edges("resolve_concept", after_resolution)
    # 批次4：在现有链路中插入三个可选节点；端口未注入时为 no-op
    graph.add_edge("load_student_state", "load_cognitive_state")
    graph.add_edge("load_cognitive_state", "load_graph_context")
    graph.add_edge("load_graph_context", "load_question_bank")
    graph.add_edge("load_question_bank", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "research_web")
    graph.add_edge("research_web", "load_sandbox_context")
    graph.add_edge("load_sandbox_context", "decide_teaching_action")
    graph.add_edge("decide_teaching_action", "generate_response")
    graph.add_conditional_edges("generate_response", after_generation)
    graph.add_edge("validate_response", "record_learning_event")
    graph.add_edge("record_learning_event", END)
    return graph.compile()
