from __future__ import annotations

import asyncio

from app.platform.agents.gateway import AgentGateway
from app.platform.agents.prep.common.dependencies import CommonPrepDependencies
from app.platform.agents.prep.initial.composition import build_initial_graph_factory
from app.platform.agents.prep.initial.dependencies import (
    InitialPrepDependencies,
    InitialPrepResult,
)
from app.platform.agents.prep.initial.profile import build_initial_profile
from app.platform.agents.prep.incremental.composition import (
    build_incremental_graph_factory,
)
from app.platform.agents.prep.incremental.dependencies import (
    IncrementalPrepDependencies,
    IncrementalPrepResult,
)
from app.platform.agents.prep.incremental.profile import build_incremental_profile
from app.platform.agents.runtime.base import AgentRunContext
from app.platform.agents.runtime.dispatcher import BaseAgentRuntime
from app.platform.agents.runtime.events import (
    NullAgentRunStorePort,
    RunEventType,
)
from app.platform.agents.runtime.profile import AgentProfile, AgentType
from app.platform.agents.runtime.registry import AgentDefinitionKey, AgentRuntimeRegistry
from app.platform.agents.shared.state import empty_meta
from app.platform.agents.contracts.llm import StructuredOutputError
from app.platform.agents.prep.incremental.workflow import build_incremental_workflow


class _FailingGraph:
    async def ainvoke(self, state):
        return {
            **state,
            "meta": {
                **state["meta"],
                "errors": ["INCREMENTAL_PLAN_INVALID_REQUEST"],
                "status": "planning_error",
            },
        }


class _CapturingEvents:
    def __init__(self):
        self.types = []

    async def emit(self, *, run_id, trace_id, event_type, payload):
        self.types.append(event_type)


class _BatchPort:
    def __init__(self):
        self.calls = []

    async def plan(self, **kwargs):
        raise AssertionError("batch action must not use the single-command port")

    async def plan_action(self, *, course_id, action, instruction, outline_node_id):
        self.calls.append((course_id, action, instruction, outline_node_id))
        return IncrementalPrepResult(
            summary="批量完成",
            operations=[{
                "target": "outline:on_1:title",
                "after": "新标题",
                "reason": "统一标题",
                "evidence_refs": [],
            }],
            planner="llm_batched",
        )


class _UnusedStructuredLLM:
    async def complete(self, **kwargs):
        raise AssertionError("workflow should call the incremental port")


class _StructuredFailurePort:
    async def plan(self, **_kwargs):
        raise StructuredOutputError(
            "LLM response did not match schema after one repair retry: ValidationError",
            reason_code="structured_output_invalid",
            stage="plan_incremental",
            attempts=2,
            schema_name="AgentPlan",
            validation_errors=[{"loc": ["operations"], "type": "missing", "msg": "Field required"}],
        )

    async def plan_action(self, **_kwargs):
        return await self.plan(**_kwargs)


def _profile():
    def build_initial_state(ctx, *, trace_id):
        return {
            "meta": empty_meta(
                run_id=ctx.run_id,
                trace_id=trace_id,
                agent_type=AgentType.PREP.value,
            ),
        }

    return AgentProfile(
        agent_type=AgentType.PREP,
        build_initial_state=build_initial_state,
    )


def test_gateway_fails_when_workflow_reports_errors_in_meta():
    key = AgentDefinitionKey(
        agent_type=AgentType.PREP.value,
        agent_version="incremental",
    )
    events = _CapturingEvents()
    registry = AgentRuntimeRegistry()
    registry.register_factory(
        key,
        lambda: BaseAgentRuntime(
            profile=_profile(),
            graph=_FailingGraph(),
            event_port=events,
        ),
    )
    gateway = AgentGateway(registry=registry, event_port=events)

    result = asyncio.run(gateway.start(
        agent_type=AgentType.PREP,
        definition_key=key,
        context=AgentRunContext(
            agent_type=AgentType.PREP.value,
            course_id="42",
            teacher_id="7",
            scope=("42",),
        ),
    ))

    assert result.status == "failed"
    assert result.error_code == "INCREMENTAL_PLAN_INVALID_REQUEST"
    assert result.result["errors"] == ["INCREMENTAL_PLAN_INVALID_REQUEST"]
    assert result.result["status"] == "planning_error"
    assert RunEventType.RUN_FAILED in events.types
    assert RunEventType.RUN_COMPLETED not in events.types


def test_gateway_preserves_structured_workflow_error_message():
    key = AgentDefinitionKey(
        agent_type=AgentType.PREP.value,
        agent_version="incremental",
    )
    registry = AgentRuntimeRegistry()
    registry.register_factory(
        key,
        lambda: BaseAgentRuntime(
            profile=_profile(),
            graph=type("StructuredFailureGraph", (), {
                "ainvoke": lambda _, state: _structured_failure(state),
            })(),
        ),
    )
    gateway = AgentGateway(registry=registry)

    result = asyncio.run(gateway.start(
        agent_type=AgentType.PREP,
        definition_key=key,
        context=AgentRunContext(agent_type=AgentType.PREP.value, scope=("42",)),
    ))

    assert result.status == "failed"
    assert result.error_code == "INCREMENTAL_PLAN_FAILED"
    assert result.error_message == "模型未完整覆盖全部节点"


async def _structured_failure(state):
    return {
        **state,
        "meta": {
            **state["meta"],
            "errors": [{
                "code": "INCREMENTAL_PLAN_FAILED",
                "message": "模型未完整覆盖全部节点",
                "node": "execute_incremental_plan",
            }],
            "status": "planning_error",
        },
    }


def test_registered_incremental_runtime_dispatches_batch_action_to_port():
    key = AgentDefinitionKey(
        agent_type=AgentType.PREP.value,
        agent_version="incremental",
    )
    events = _CapturingEvents()
    port = _BatchPort()
    dependencies = IncrementalPrepDependencies(
        common=CommonPrepDependencies(
            structured_llm=_UnusedStructuredLLM(),
            run_store=NullAgentRunStorePort(),
            event_port=events,
        ),
        incremental_prep=port,
    )
    builder = build_incremental_graph_factory(dependencies)
    profile = build_incremental_profile()
    registry = AgentRuntimeRegistry()
    registry.register_factory(
        key,
        lambda: BaseAgentRuntime(
            profile=profile,
            graph=builder(()),
            event_port=events,
        ),
    )
    gateway = AgentGateway(registry=registry, event_port=events)

    result = asyncio.run(gateway.start(
        agent_type=AgentType.PREP,
        definition_key=key,
        context=AgentRunContext(
            agent_type=AgentType.PREP.value,
            course_id="42",
            teacher_id="7",
            scope=("42",),
            extras={"action": "organize_structure"},
        ),
    ))

    assert result.status == "completed"
    assert port.calls == [("42", "organize_structure", "", None)]
    assert result.result["result"]["planner"] == "llm_batched"


def test_incremental_workflow_hides_raw_structured_output_error():
    dependencies = IncrementalPrepDependencies(
        common=CommonPrepDependencies(
            structured_llm=_UnusedStructuredLLM(),
            run_store=NullAgentRunStorePort(),
            event_port=_CapturingEvents(),
        ),
        incremental_prep=_StructuredFailurePort(),
    )
    graph = build_incremental_workflow(dependencies)
    result = asyncio.run(graph.ainvoke({
        "request": {
            "course_id": "42",
            "instruction": "优化标题",
            "outline_node_id": "node-1",
            "action": "optimize_node_title",
        },
        "meta": {"errors": [], "degraded_services": []},
    }))

    error = result["meta"]["errors"][-1]
    assert error["reason_code"] == "structured_output_invalid"
    assert "LLM response did not match schema" not in error["message"]
    assert "ValidationError" not in error["message"]
    assert "课程节点优化" in error["message"]


def test_incremental_profile_limits_shared_llm_runs_to_three():
    assert build_incremental_profile().max_concurrency == 3
    assert build_incremental_profile().default_timeout_seconds == 240.0


def test_registered_initial_runtime_executes_initial_prep_port():
    class _InitialPort:
        def __init__(self):
            self.calls = []

        async def build(self, **kwargs):
            self.calls.append(kwargs)
            return InitialPrepResult(
                outline_version_id="ov_1",
                script_version_id="sv_1",
                graph_candidate_batch_id="gb_1",
                warnings=["需要教师复核"],
            )

    port = _InitialPort()
    events = _CapturingEvents()
    dependencies = InitialPrepDependencies(
        common=CommonPrepDependencies(
            structured_llm=_UnusedStructuredLLM(),
            run_store=NullAgentRunStorePort(),
            event_port=events,
        ),
        initial_prep=port,
    )
    key = AgentDefinitionKey(
        agent_type=AgentType.PREP.value,
        agent_version="initial",
    )
    registry = AgentRuntimeRegistry()
    builder = build_initial_graph_factory(dependencies)
    profile = build_initial_profile()
    registry.register_factory(
        key,
        lambda: BaseAgentRuntime(
            profile=profile,
            graph=builder(()),
            event_port=events,
        ),
    )
    runtime = asyncio.run(registry.get_or_create(key))

    result = asyncio.run(runtime.run(
        context=AgentRunContext(
            agent_type=AgentType.PREP.value,
            course_id="42",
            teacher_id="7",
            scope=("42",),
            extras={
                "corpus_snapshot_id": "cs_1",
                "build_task_id": "bt_1",
                "replace_unreviewed_initial": True,
            },
        ),
    ))

    assert result["status"] == "ok"
    assert result["result"]["outline_version_id"] == "ov_1"
    assert port.calls[0]["teacher_id"] == "7"
    assert port.calls[0]["replace_unreviewed_initial"] is True
