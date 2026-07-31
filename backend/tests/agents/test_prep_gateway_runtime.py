from __future__ import annotations

import asyncio

from app.platform.agents.gateway import AgentGateway
from app.platform.agents.prep.common.dependencies import CommonPrepDependencies
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

    async def plan_batch(self, *, course_id, action):
        self.calls.append((course_id, action))
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
    assert port.calls == [("42", "organize_structure")]
    assert result.result["result"]["planner"] == "llm_batched"


def test_incremental_profile_limits_shared_llm_runs_to_three():
    assert build_incremental_profile().max_concurrency == 3
    assert build_incremental_profile().default_timeout_seconds == 240.0
