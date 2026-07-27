"""验收测试：run_id 从 TeachingAgentRequest 端到端流转到 Judge0SandboxPort 与 CodingDiagnosisPort

修复2: 前端提交代码后把 run_id 传给 TeachingAgent
- 后端 TeachingAgentRequest.code_submission_id → runtime.respond → state → load_sandbox_context
- Judge0SandboxPort 按 run_id 从 ExperimentRun 读取真实结果

修复3: 建立受限 CodingDiagnosis 供 EduAgent 只读消费
- CodingEduAgent.diagnose_run 生成诊断
- SessionScopedCodingDiagnosisPort 读取诊断
- load_coding_diagnosis 节点消费诊断

约束来源：
- 用户反馈: "让 Judge0SandboxPort 按 run_id 从本地 ExperimentRun 读取已验证结果"
- 用户反馈: "建立受限 CodingDiagnosis，再供 EduAgent 只读消费"
- Hard Constraints: "Only server-side scoring results or codingagent should write to formal LearningEvidenceRecord"
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from app.platform.agents.contracts import TeachingTools
from app.platform.agents.runtime import TeachingAgentRuntime
from app.platform.agents.tools.integration import Judge0SandboxPort


class TestCodeSubmissionIdEndToEndFlow:
    """测试1: code_submission_id 从 runtime.respond 流转到 sandbox port"""

    def test_code_submission_id_reaches_sandbox_port(self) -> None:
        """runtime.respond(code_submission_id=...) → state → load_sandbox_context → sandbox.get_execution_result"""
        from app.models.experiment_model import ExperimentRun, RunOutcome

        # 构造 mock sandbox port，记录收到的 code_submission_id
        captured = {}

        class CaptureSandboxPort:
            async def get_execution_result(self, *, student_id, course_id, code_submission_id, **_):
                captured["student_id"] = student_id
                captured["course_id"] = course_id
                captured["code_submission_id"] = code_submission_id
                return {
                    "available": True,
                    "status": "accepted",
                    "outcome": "accepted",
                    "diagnosis": {"outcome": "accepted", "compile_ok": True},
                }

        # 构造最小 TeachingTools：sandbox 是被测对象，其他用 None/最小 stub
        from app.platform.agents.contracts import (
            ScopePort, KnowledgeGraphPort, CourseRetrievalPort,
            StudentModelingPort, RecommendationPort, LearningEventPort, TeachingLLMPort,
        )

        class StubScope:
            async def validate_scope(self, *, student_id, course_id, resource_id):
                return {"allowed": True}

        class StubLLM:
            async def detect_intent(self, *, message, course_id):
                return {"intent": "code_debugging"}
            async def extract_concept_candidates(self, *, message, course_id):
                return []
            async def generate_teaching_response(self, *, context):
                return {"answer": "诊断已加载", "teaching_action": "code_debugging"}

        # 使用真实 workflow，但注入 CaptureSandboxPort
        # 其他必需端口用最小 stub（返回空/默认值）
        class StubKnowledgeGraph:
            async def resolve_concepts(self, *, course_id, message, candidates, resource_id):
                return []
            async def get_context(self, *, course_id, concept_id):
                return {"concept_id": concept_id, "prerequisites": [], "successors": []}

        class StubRetrieval:
            async def retrieve_course_evidence(self, *, course_id, message, concept_id, resource_id):
                return []

        class StubStudentModeling:
            async def get_concept_state(self, *, student_id, course_id, concept_id):
                return {"mastery": 0.5}
            async def get_weak_concepts(self, *, student_id, course_id):
                return []

        class StubRecommendation:
            async def recommend_next_action(self, *, student_id, course_id, concept_id, action, graph_context, student_state):
                return {"action": "code_debugging", "confidence": 0.8}

        class StubLearningEvent:
            async def record_learning_event(self, *, event):
                pass
            async def record_agent_trace(self, *, trace):
                pass

        tools = TeachingTools(
            scope=StubScope(),
            knowledge_graph=StubKnowledgeGraph(),
            retrieval=StubRetrieval(),
            student_modeling=StubStudentModeling(),
            recommendation=StubRecommendation(),
            sandbox=CaptureSandboxPort(),
            learning_events=StubLearningEvent(),
            llm=StubLLM(),
        )

        runtime = TeachingAgentRuntime(tools)

        # 调用 respond，传入 code_submission_id
        state = asyncio.run(runtime.respond(
            student_id="10",
            course_id="1",
            session_id="sess-1",
            message="我的代码为什么报错？",
            code_submission_id="run_001",
        ))

        # 验证 code_submission_id 到达 sandbox port
        assert captured.get("code_submission_id") == "run_001"
        assert captured.get("student_id") == "10"
        assert captured.get("course_id") == "1"

        # 验证 sandbox_result 和 code_diagnosis 已写入 state
        assert state.get("sandbox_result") is not None
        assert state["sandbox_result"]["status"] == "accepted"
        assert state.get("code_diagnosis") is not None
        assert state["code_diagnosis"]["outcome"] == "accepted"

    def test_no_code_submission_id_skips_sandbox(self) -> None:
        """未传 code_submission_id 时跳过 load_sandbox_context（不调用 sandbox port）"""
        sandbox_called = {"count": 0}

        class FailingSandboxPort:
            async def get_execution_result(self, **_):
                sandbox_called["count"] += 1
                return {"available": False, "status": "should_not_be_called"}

        class StubScope:
            async def validate_scope(self, *, student_id, course_id, resource_id):
                return {"allowed": True}

        class StubLLM:
            async def detect_intent(self, *, message, course_id):
                return {"intent": "general_qa"}
            async def extract_concept_candidates(self, *, message, course_id):
                return []
            async def generate_teaching_response(self, *, context):
                return {"answer": "已回答", "teaching_action": "general_qa"}

        class StubKnowledgeGraph:
            async def resolve_concepts(self, *, course_id, message, candidates, resource_id):
                return []
            async def get_context(self, *, course_id, concept_id):
                return {"concept_id": concept_id, "prerequisites": [], "successors": []}

        class StubRetrieval:
            async def retrieve_course_evidence(self, *, course_id, message, concept_id, resource_id):
                return []

        class StubStudentModeling:
            async def get_concept_state(self, *, student_id, course_id, concept_id):
                return {"mastery": 0.5}
            async def get_weak_concepts(self, *, student_id, course_id):
                return []

        class StubRecommendation:
            async def recommend_next_action(self, *, student_id, course_id, concept_id, action, graph_context, student_state):
                return {"action": "general_qa", "confidence": 0.8}

        class StubLearningEvent:
            async def record_learning_event(self, *, event):
                pass
            async def record_agent_trace(self, *, trace):
                pass

        tools = TeachingTools(
            scope=StubScope(),
            knowledge_graph=StubKnowledgeGraph(),
            retrieval=StubRetrieval(),
            student_modeling=StubStudentModeling(),
            recommendation=StubRecommendation(),
            sandbox=FailingSandboxPort(),
            learning_events=StubLearningEvent(),
            llm=StubLLM(),
        )

        runtime = TeachingAgentRuntime(tools)
        state = asyncio.run(runtime.respond(
            student_id="10",
            course_id="1",
            session_id="sess-1",
            message="什么是递归？",
            # 不传 code_submission_id
        ))

        # sandbox port 不应被调用
        assert sandbox_called["count"] == 0
        # sandbox_result 不在 state 中（或为 None）
        assert not state.get("sandbox_result")


class TestCodingDiagnosisPortWired:
    """测试2: CodingDiagnosisPort 已在 bootstrap 注入并可被 Agent 消费"""

    def test_bootstrap_injects_coding_diagnosis_port(self, tmp_path) -> None:
        """bootstrap.py 注入 coding_diagnosis port"""
        from app.platform.agents.bootstrap import bootstrap_teaching_agent
        from app.platform.retrieval_demo.service import DemoService
        from app.platform.retrieval_demo.store import DemoRunStore
        from app.platform.agents.tools.coding import SessionScopedCodingDiagnosisPort

        demo_service = DemoService(
            configured_mode="demo_compare",
            environment="test",
            store=DemoRunStore(tmp_path / "runs"),
        )

        with patch("app.platform.agents.bootstrap.settings") as mock_settings:
            mock_settings.TEACHING_AGENT_MODE = "enabled"
            mock_settings.DEMO_RETRIEVAL_MODE = "demo_compare"
            mock_settings.DEMO_RETRIEVAL_ENVIRONMENT = "test"
            mock_settings.LLM_API_BASE = "http://x"
            mock_settings.LLM_API_KEY = "k"
            mock_settings.LLM_MODEL_NAME = "m"
            app = FastAPI()
            injected = bootstrap_teaching_agent(app, demo_service=demo_service)

        assert injected is True
        registry = app.state.teaching_agent_runtime_registry
        # coding_diagnosis port 已注入
        assert registry._coding_diagnosis is not None
        assert isinstance(registry._coding_diagnosis, SessionScopedCodingDiagnosisPort)

    def test_coding_diagnosis_port_reads_diagnosis_by_run_id(self) -> None:
        """SessionScopedCodingDiagnosisPort.get_latest_diagnosis 按 run_id 读取诊断"""
        from app.platform.agents.tools.coding import SessionScopedCodingDiagnosisPort
        from app.models.coding_diagnosis_model import CodingDiagnosisRecord

        mock_record = MagicMock(spec=CodingDiagnosisRecord)
        mock_record.diagnosis_id = "cd_001"
        mock_record.run_id = "run_001"
        mock_record.course_id = 1
        mock_record.student_id = 10
        mock_record.status = "ready"
        mock_record.outcome = "runtime_error"
        mock_record.error_class = "runtime"
        mock_record.line = 5
        mock_record.column = None
        mock_record.summary = "NameError"
        mock_record.debug_steps = ["step1", "step2"]
        mock_record.hints = [{"level": "concept", "text": "hint1"}]
        mock_record.confidence = 0.95
        mock_record.evidence_refs = ["experiment_run:run_001"]
        mock_record.reason_codes = ["RUNTIME_ERROR"]
        mock_record.policy_version = "coding-diagnosis/rule-v1"
        mock_record.generated_by = "coding-rules"
        mock_record.created_at = None

        # coding.py 使用 `with self._session_factory() as session:` 上下文管理器
        mock_session = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.first.return_value = mock_record
        mock_session.exec.return_value = mock_exec_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        port = SessionScopedCodingDiagnosisPort(lambda: mock_session)
        result = asyncio.run(port.get_latest_diagnosis(
            student_id="10", course_id="1", run_id="run_001",
        ))

        assert result is not None
        assert result["diagnosis_id"] == "cd_001"
        assert result["run_id"] == "run_001"
        assert result["outcome"] == "runtime_error"
        assert result["error_class"] == "runtime"
        assert "RUNTIME_ERROR" in result["reason_codes"]

    def test_coding_diagnosis_port_returns_none_when_not_found(self) -> None:
        """诊断不存在时返回 None（不抛异常）"""
        from app.platform.agents.tools.coding import SessionScopedCodingDiagnosisPort

        mock_session = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.first.return_value = None
        mock_session.exec.return_value = mock_exec_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        port = SessionScopedCodingDiagnosisPort(lambda: mock_session)
        result = asyncio.run(port.get_latest_diagnosis(
            student_id="10", course_id="1", run_id="run_missing",
        ))
        assert result is None


class TestCodingDiagnosisServiceDiagnoseRun:
    """测试3: CodingEduAgent.diagnose_run 生成诊断"""

    def test_diagnose_run_creates_record(self) -> None:
        """diagnose_run 从 ExperimentRun 生成 CodingDiagnosisRecord"""
        from app.services.coding_eduagent_service import CodingEduAgent
        from app.models.experiment_model import ExperimentRun, RunOutcome
        from app.models.coding_diagnosis_model import CodingDiagnosisRecord

        mock_run = MagicMock(spec=ExperimentRun)
        mock_run.run_id = "run_001"
        mock_run.course_id = 1
        mock_run.student_id = 10
        mock_run.outcome = RunOutcome.RUNTIME_ERROR
        mock_run.error_code = "RUNTIME_ERROR"
        mock_run.error_message = "NameError: name 'x' is not defined"
        mock_run.compile_message = ""
        mock_run.runtime_message = "NameError"

        mock_session = MagicMock()
        # 第一次 select(ExperimentRun) 返回 run
        # 第二次 select(CodingDiagnosisRecord) 返回 None（不存在）
        # 第三次 select(ExperimentRunArtifact) 返回 []
        mock_run_result = MagicMock()
        mock_run_result.first.return_value = mock_run
        mock_existing_result = MagicMock()
        mock_existing_result.first.return_value = None
        mock_artifacts_result = MagicMock()
        mock_artifacts_result.all.return_value = []
        mock_session.exec.side_effect = [mock_run_result, mock_existing_result, mock_artifacts_result]

        agent = CodingEduAgent()
        record = agent.diagnose_run(
            mock_session, course_id=1, student_id=10, run_id="run_001",
        )

        assert isinstance(record, CodingDiagnosisRecord)
        assert record.run_id == "run_001"
        assert record.outcome == "runtime_error"
        assert record.error_class == "runtime"
        assert "RUNTIME_ERROR" in record.reason_codes
        assert record.confidence == 0.95
        # session.add 被调用
        mock_session.add.assert_called_once()

    def test_diagnose_run_idempotent_returns_existing(self) -> None:
        """已存在诊断时直接返回，不重复创建"""
        from app.services.coding_eduagent_service import CodingEduAgent
        from app.models.experiment_model import ExperimentRun
        from app.models.coding_diagnosis_model import CodingDiagnosisRecord

        mock_run = MagicMock(spec=ExperimentRun)
        mock_run.run_id = "run_001"
        mock_existing_diagnosis = MagicMock(spec=CodingDiagnosisRecord)
        mock_existing_diagnosis.run_id = "run_001"

        mock_session = MagicMock()
        mock_run_result = MagicMock()
        mock_run_result.first.return_value = mock_run
        mock_existing_result = MagicMock()
        mock_existing_result.first.return_value = mock_existing_diagnosis
        mock_session.exec.side_effect = [mock_run_result, mock_existing_result]

        agent = CodingEduAgent()
        record = agent.diagnose_run(
            mock_session, course_id=1, student_id=10, run_id="run_001",
        )

        assert record is mock_existing_diagnosis
        # session.add 不应被调用（幂等）
        mock_session.add.assert_not_called()
