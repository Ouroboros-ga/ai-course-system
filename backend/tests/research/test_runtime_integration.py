from __future__ import annotations

import asyncio

from app.platform.agents.platform import AgentPlatform
from app.platform.agents.runtime.base import AgentRunContext
from app.platform.agents.runtime.dispatcher import BaseAgentRuntime
from app.platform.agents.runtime.events import RunEventType
from app.platform.agents.runtime.profile import AgentProfile, AgentType


def test_generic_platform_enforces_profile_concurrency_with_bounded_runtime():
    class CapturingEvents:
        def __init__(self):
            self.types = []

        async def emit(self, *, run_id, trace_id, event_type, payload):
            self.types.append(event_type)

    events = CapturingEvents()
    platform = AgentPlatform(event_port=events)

    class InspectingGraph:
        async def ainvoke(self, state):
            return {
                **state,
                "active_research_runs": platform.concurrency_limiter.active_count("research"),
            }

    profile = AgentProfile(
        agent_type=AgentType.RESEARCH,
        max_concurrency=1,
        build_initial_state=lambda ctx, trace_id: {
            "trace_id": trace_id,
            "run_id": ctx.run_id,
            "warnings": [],
            "errors": [],
            "degraded_services": [],
            "trace": [],
        },
    )
    platform.register_generic(profile, lambda _scope: InspectingGraph())

    runtime = platform.get_runtime(AgentType.RESEARCH, ("course:1",))
    assert isinstance(runtime, BaseAgentRuntime)

    result = asyncio.run(runtime.respond(AgentRunContext(
        agent_type=AgentType.RESEARCH.value,
        scope=("course:1",),
        course_id="1",
        student_id="7",
    )))

    assert result["active_research_runs"] == 1
    assert result["status"] == "ok"
    assert events.types == [RunEventType.RUN_STARTED, RunEventType.RUN_COMPLETED]
