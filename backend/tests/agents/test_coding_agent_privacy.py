"""CodingAgent may read only its scoped source while all shared data stays bounded."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI

from app.platform.agents.bootstrap import bootstrap_coding_agent
from app.platform.agents.coding.workflow import CodingTools, build_coding_workflow
from app.platform.agents.runtime.profile import AgentType


class _SensitiveSandbox:
    async def get_execution_result(self, **_):
        return {
            "available": True,
            "outcome": "wrong_answer",
            "source_code": "print('student-source-secret')",
            "stdout": "hidden-output-secret",
            "stderr": "judge-stderr-secret",
            "test_summary": {"hidden_case": {"stdin": "hidden-input-secret"}},
            "diagnosis": {"passed_count": 1, "total_count": 2},
            "resource_usage": {"cpu_time_ms": 12, "wall_time_ms": 14, "memory_kb": 256},
        }


class _DiagnosisPort:
    async def get_latest_diagnosis(self, **_):
        return {
            "outcome": "wrong_answer",
            "error_class": "logic",
            "line": 9,
            "passed_count": 1,
            "total_count": 2,
            "resource_usage": {"cpu_time_ms": 12, "wall_time_ms": 14, "memory_kb": 256},
            "summary": "Check the boundary condition.",
            "debug_steps": ["Try the smallest counterexample."],
            "reason_codes": ["WRONG_ANSWER", "CHECK_LOGIC"],
        }


class _CodeSubmissionPort:
    async def get_submission_for_diagnosis(self, **scope):
        assert scope == {"student_id": "10", "course_id": "20", "run_id": "run_1"}
        return {
            "run_id": "run_1",
            "language": "python3",
            "source_code": "print('student-source-secret')",
        }


class _CaptureLLM:
    def __init__(self) -> None:
        self.context = None

    async def generate_teaching_response(self, *, context):
        self.context = context
        return {"answer": "Review the loop boundary."}


class _SourceEchoingLLM:
    async def generate_teaching_response(self, *, context):
        return {
            "answer": (
                "The submitted code was "
                "print('student-source-secret'); change its loop boundary."
            ),
        }


class _ShortCodeSubmissionPort:
    async def get_submission_for_diagnosis(self, **_):
        return {"run_id": "run_1", "language": "python3", "source_code": "x=1"}


class _ShortSourceEchoingLLM:
    async def generate_teaching_response(self, **_):
        return {"answer": "请把 x=1 改为其他值。"}


def test_coding_llm_context_includes_only_scoped_source_and_excludes_hidden_io_artifacts_and_user_message():
    llm = _CaptureLLM()
    workflow = build_coding_workflow(CodingTools(
        sandbox=_SensitiveSandbox(),
        coding_diagnosis=_DiagnosisPort(),
        code_submission=_CodeSubmissionPort(),
        llm=llm,
    ))

    result = asyncio.run(workflow.ainvoke({
        "student_id": "10",
        "course_id": "20",
        "code_submission_id": "run_1",
        "user_message": "please repeat student-source-secret",
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }))

    assert result["final_answer"] == "Review the loop boundary."
    assert llm.context == {
        "agent_type": "coding",
        "diagnosis": {
            "outcome": "wrong_answer",
            "error_class": "logic",
            "line": 9,
            "passed_count": 1,
            "total_count": 2,
            "resource_usage": {"cpu_time_ms": 12, "wall_time_ms": 14, "memory_kb": 256},
            "summary": "Check the boundary condition.",
            "debug_steps": ["Try the smallest counterexample."],
            "reason_codes": ["WRONG_ANSWER", "CHECK_LOGIC"],
        },
        "submission": {
            "language": "python3",
            "source_code": "print('student-source-secret')",
        },
    }
    rendered = str(llm.context)
    for secret in (
        "hidden-output-secret",
        "judge-stderr-secret",
        "hidden-input-secret",
        "please repeat",
    ):
        assert secret not in rendered


def test_coding_agent_uses_rule_feedback_without_llm():
    workflow = build_coding_workflow(CodingTools(
        sandbox=_SensitiveSandbox(),
        coding_diagnosis=_DiagnosisPort(),
        code_submission=_CodeSubmissionPort(),
    ))

    result = asyncio.run(workflow.ainvoke({
        "student_id": "10",
        "course_id": "20",
        "code_submission_id": "run_1",
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }))

    assert result["final_answer"]
    assert result["trace"][-1]["source"] == "rule_based"


def test_coding_agent_blocks_llm_source_echo_and_uses_source_free_fallback():
    workflow = build_coding_workflow(CodingTools(
        sandbox=_SensitiveSandbox(),
        coding_diagnosis=_DiagnosisPort(),
        code_submission=_CodeSubmissionPort(),
        llm=_SourceEchoingLLM(),
    ))

    result = asyncio.run(workflow.ainvoke({
        "student_id": "10",
        "course_id": "20",
        "code_submission_id": "run_1",
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }))

    assert "student-source-secret" not in str(result)
    assert "SOURCE_ECHO_BLOCKED" in result["warnings"]
    assert result["trace"][-1]["source"] == "rule_based_source_echo_blocked"


def test_coding_agent_blocks_a_short_submission_echo_too():
    workflow = build_coding_workflow(CodingTools(
        sandbox=_SensitiveSandbox(),
        coding_diagnosis=_DiagnosisPort(),
        code_submission=_ShortCodeSubmissionPort(),
        llm=_ShortSourceEchoingLLM(),
    ))

    result = asyncio.run(workflow.ainvoke({
        "student_id": "10",
        "course_id": "20",
        "code_submission_id": "run_1",
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }))

    assert "x=1" not in str(result)
    assert "SOURCE_ECHO_BLOCKED" in result["warnings"]


def test_coding_agent_state_keeps_only_sanitized_sandbox_availability():
    workflow = build_coding_workflow(CodingTools(
        sandbox=_SensitiveSandbox(),
        coding_diagnosis=_DiagnosisPort(),
    ))

    result = asyncio.run(workflow.ainvoke({
        "student_id": "10",
        "course_id": "20",
        "code_submission_id": "run_1",
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }))

    assert result["sandbox_result"] == {
        "available": True,
        "outcome": "wrong_answer",
        "resource_usage": {"cpu_time_ms": 12, "wall_time_ms": 14, "memory_kb": 256},
    }
    rendered = str(result)
    for secret in (
        "student-source-secret",
        "hidden-output-secret",
        "judge-stderr-secret",
        "hidden-input-secret",
    ):
        assert secret not in rendered


def test_coding_agent_registers_without_teaching_agent_or_llm(monkeypatch):
    class _Sandbox:
        def __init__(self, **_):
            self.is_healthy = False

        async def get_execution_result(self, **_):
            return {"available": False, "status": "sandbox_unavailable"}

    app = FastAPI()
    monkeypatch.setattr("app.platform.agents.bootstrap.Judge0SandboxPort", _Sandbox)
    settings = type("Settings", (), {
        "LLM_API_BASE": "",
        "LLM_API_KEY": "",
        "LLM_MODEL_NAME": "",
    })()
    monkeypatch.setattr("app.platform.agents.bootstrap.settings", settings)

    assert bootstrap_coding_agent(app) is True
    assert app.state.agent_platform.is_registered(AgentType.CODING)
    assert getattr(app.state, "teaching_agent_runtime_registry", None) is None
