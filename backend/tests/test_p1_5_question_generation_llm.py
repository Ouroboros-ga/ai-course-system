"""P1-5 LLM 个性化出题验证测试

验证内容：
1. LLM 不可用时返回明确标记的占位草稿（不伪装成功）
2. LLM 返回合法 JSON 时被正确解析
3. LLM 返回非 JSON 或 generated=false 时回退到占位草稿
4. 节点上下文解析正确处理无活跃快照的情况
5. PracticeRecommendationService 集成 LLM 生成草稿

注：使用 ``asyncio.run`` 而非 ``pytest.mark.asyncio`` 以避免对
``pytest-asyncio`` 插件的硬依赖（与 P1-4 测试保持一致）。
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.services.question_generation_llm import (
    GENERATION_POLICY_VERSION,
    LLM_UNAVAILABLE_CONFIDENCE,
    _build_fallback_payload,
    _parse_llm_response,
    build_generation_prompt,
    generate_question_via_llm,
    generate_question_sync,
    resolve_node_context,
)


class TestFallbackPayload:
    """测试1: LLM 不可用时的占位草稿"""

    def test_fallback_payload_is_clearly_marked(self) -> None:
        payload = _build_fallback_payload(
            purpose="diagnose",
            difficulty="medium",
            node_context=None,
            reason_codes=["insufficient_data"],
            unavailable_reason="未配置 LLM_API_KEY",
        )

        # 占位草稿必须被明确标记，不能伪装成真实 LLM 输出
        assert payload["source"] == "llm_unavailable_stub"
        assert "LLM 不可用" in payload["question_text"]
        assert "占位答案" in payload["answer"]
        assert "LLM 个性化出题不可用" in payload["mapping_reason"]
        assert "未配置 LLM_API_KEY" in payload["mapping_reason"]

        # 置信度必须低于 LOW_CONFIDENCE_THRESHOLD (0.4)
        assert payload["confidence"] == LLM_UNAVAILABLE_CONFIDENCE
        assert payload["confidence"] < 0.4

        # reason_codes 必须包含 llm_unavailable 标记
        assert "llm_unavailable" in payload["reason_codes"]
        assert "insufficient_data" in payload["reason_codes"]

    def test_fallback_payload_includes_node_label_when_available(self) -> None:
        node_context = {
            "id": "n_42",
            "name": "光合作用",
            "description": "植物通过叶绿体合成有机物",
            "aliases": [],
            "prerequisites": [],
        }
        payload = _build_fallback_payload(
            purpose="remediation",
            difficulty="hard",
            node_context=node_context,
            reason_codes=[],
            unavailable_reason="connection timeout",
        )

        assert "光合作用" in payload["question_text"]


class TestParseLLMResponse:
    """测试2: LLM 响应解析"""

    def test_parse_valid_response(self) -> None:
        content = json.dumps({
            "generated": True,
            "question_text": "什么是光合作用？",
            "answer": "植物利用光能将二氧化碳和水转化为有机物的过程。",
            "options": [],
            "difficulty": "easy",
            "category": "biology",
            "confidence": 0.85,
            "reason_codes": ["node_resolved"],
            "mapping_reason": "针对光合作用基础概念诊断",
        })
        parsed = _parse_llm_response(content)

        assert parsed is not None
        assert parsed["question_text"] == "什么是光合作用？"
        assert parsed["confidence"] == 0.85
        assert parsed["source"] == "llm"
        assert parsed["difficulty"] == "easy"

    def test_parse_markdown_code_block(self) -> None:
        content = (
            "```json\n"
            '{"generated": true, "question_text": "Q", "answer": "A"}'
            "\n```"
        )
        parsed = _parse_llm_response(content)

        assert parsed is not None
        assert parsed["question_text"] == "Q"
        assert parsed["answer"] == "A"

    def test_parse_generated_false_returns_none(self) -> None:
        content = json.dumps({"generated": False})
        parsed = _parse_llm_response(content)
        assert parsed is None

    def test_parse_empty_question_returns_none(self) -> None:
        content = json.dumps({
            "generated": True,
            "question_text": "",
            "answer": "A",
        })
        parsed = _parse_llm_response(content)
        assert parsed is None

    def test_parse_invalid_json_returns_none(self) -> None:
        parsed = _parse_llm_response("not json at all")
        assert parsed is None

    def test_parse_empty_content_returns_none(self) -> None:
        parsed = _parse_llm_response("")
        assert parsed is None

    def test_parse_clamps_confidence(self) -> None:
        content = json.dumps({
            "generated": True,
            "question_text": "Q",
            "answer": "A",
            "confidence": 5.0,  # 越界
        })
        parsed = _parse_llm_response(content)
        assert parsed is not None
        assert parsed["confidence"] == 1.0

    def test_parse_normalizes_invalid_difficulty(self) -> None:
        content = json.dumps({
            "generated": True,
            "question_text": "Q",
            "answer": "A",
            "difficulty": "extreme",  # 非法
        })
        parsed = _parse_llm_response(content)
        assert parsed is not None
        assert parsed["difficulty"] == "medium"


class TestBuildPrompt:
    """测试3: 提示词构建"""

    def test_prompt_contains_purpose_intent(self) -> None:
        system, user = build_generation_prompt(
            purpose="diagnose",
            difficulty="medium",
            node_context={"id": "n1", "name": "光合作用", "description": "...",
                          "aliases": [], "prerequisites": []},
            cognitive_snapshot={"mastery_level": "partial"},
            six_dimensions={"observed_performance_score": 0.5},
            reason_codes=["evidence_needed"],
        )

        assert "诊断学生" in system
        assert "光合作用" in user
        assert "medium" in user
        assert "evidence_needed" in user

    def test_prompt_handles_missing_node_context(self) -> None:
        system, user = build_generation_prompt(
            purpose="remediation",
            difficulty="hard",
            node_context=None,
            cognitive_snapshot={},
            six_dimensions={},
            reason_codes=[],
        )

        assert "未提供" in user
        assert "上下文不足" in user


class TestResolveNodeContext:
    """测试4: 节点上下文解析"""

    def test_returns_none_when_node_id_is_none(self) -> None:
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            result = resolve_node_context(session, course_id=1, node_id=None)
            assert result is None

    def test_returns_none_when_no_active_snapshot(self) -> None:
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            result = resolve_node_context(session, course_id=999, node_id=42)
            assert result is None


class TestGenerateViaLLM:
    """测试5: 端到端 LLM 调用与回退"""

    @pytest.fixture
    def session(self):
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            yield s

    def test_no_api_key_returns_fallback(self, session) -> None:
        with patch("app.services.question_generation_llm.settings") as mock_settings:
            mock_settings.LLM_API_KEY = ""
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.QWEN_API_KEY = ""
            mock_settings.DOUBAO_API_KEY = ""

            result = asyncio.run(generate_question_via_llm(
                session,
                course_id=1,
                node_id=None,
                purpose="diagnose",
                difficulty="medium",
                cognitive_snapshot={},
                six_dimensions={},
                reason_codes=[],
            ))

        assert result["source"] == "llm_unavailable_stub"
        assert result["confidence"] == LLM_UNAVAILABLE_CONFIDENCE
        assert "llm_unavailable" in result["reason_codes"]

    def test_llm_call_exception_returns_fallback(self, session) -> None:
        with patch("app.services.question_generation_llm.settings") as mock_settings, \
             patch("app.services.question_generation_llm.llm_client") as mock_client:
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.QWEN_API_KEY = ""
            mock_settings.DOUBAO_API_KEY = ""
            mock_client.chat = AsyncMock(side_effect=RuntimeError("network down"))

            result = asyncio.run(generate_question_via_llm(
                session,
                course_id=1,
                node_id=None,
                purpose="diagnose",
                difficulty="medium",
            ))

        assert result["source"] == "llm_unavailable_stub"
        assert "network down" in result["mapping_reason"]

    def test_llm_returns_valid_question(self, session) -> None:
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "generated": True,
            "question_text": "什么是细胞分裂？",
            "answer": "细胞分裂是一个细胞分裂为两个细胞的过程。",
            "options": [],
            "difficulty": "easy",
            "confidence": 0.8,
            "reason_codes": [],
            "mapping_reason": "针对基础概念",
        })

        with patch("app.services.question_generation_llm.settings") as mock_settings, \
             patch("app.services.question_generation_llm.llm_client") as mock_client:
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.QWEN_API_KEY = ""
            mock_settings.DOUBAO_API_KEY = ""
            mock_client.chat = AsyncMock(return_value=mock_response)

            result = asyncio.run(generate_question_via_llm(
                session,
                course_id=1,
                node_id=None,
                purpose="diagnose",
                difficulty="easy",
            ))

        assert result["source"] == "llm"
        assert result["question_text"] == "什么是细胞分裂？"
        assert result["confidence"] == 0.8
        # node_id=None 应当追加 insufficient_context
        assert "insufficient_context" in result["reason_codes"]

    def test_llm_returns_generated_false_falls_back(self, session) -> None:
        mock_response = MagicMock()
        mock_response.content = json.dumps({"generated": False})

        with patch("app.services.question_generation_llm.settings") as mock_settings, \
             patch("app.services.question_generation_llm.llm_client") as mock_client:
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.QWEN_API_KEY = ""
            mock_settings.DOUBAO_API_KEY = ""
            mock_client.chat = AsyncMock(return_value=mock_response)

            result = asyncio.run(generate_question_via_llm(
                session,
                course_id=1,
                node_id=None,
                purpose="diagnose",
                difficulty="medium",
            ))

        assert result["source"] == "llm_unavailable_stub"
        assert "LLM 返回无可信生成结果" in result["mapping_reason"]


class TestGenerateSync:
    """测试6: 同步包装器"""

    def test_generate_sync_returns_payload(self) -> None:
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            with patch("app.services.question_generation_llm.settings") as mock_settings:
                mock_settings.LLM_API_KEY = ""
                mock_settings.OPENAI_API_KEY = ""
                mock_settings.QWEN_API_KEY = ""
                mock_settings.DOUBAO_API_KEY = ""

                result = generate_question_sync(
                    session,
                    course_id=1,
                    node_id=None,
                    purpose="diagnose",
                    difficulty="medium",
                )

        assert result["source"] == "llm_unavailable_stub"


class TestPolicyVersion:
    """测试7: 策略版本"""

    def test_policy_version_bumped(self) -> None:
        # P1-5 升级版本号以反映 LLM 驱动
        assert GENERATION_POLICY_VERSION == "question-generation/llm-v1"


class TestIntegrationWithRecommendation:
    """测试8: PracticeRecommendationService 集成"""

    def test_recommendation_uses_llm_generator_for_drafts(self) -> None:
        """题库不足时调用 generate_question_sync 生成草稿，而不是占位字符串"""
        from app.services.practice_recommendation_service import (
            PracticeRecommendationService,
        )
        from app.models.practice_recommendation_model import (
            QuestionRecommendationRun,
            QuestionSource,
        )
        from app.models.question_bank_model import QuestionBankItem, QuestionStatus
        from app.models.user_model import User
        from app.models.course_model import Course

        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            teacher = User(username="t1", email="t1@example.com",
                           hashed_password="x", role="TEACHER")
            session.add(teacher)
            student = User(username="s1", email="s1@example.com",
                           hashed_password="x", role="STUDENT")
            session.add(student)
            session.flush()
            course = Course(
                fanya_course_id="fanya_T101",
                fanya_course_name="测试课程",
                title="测试课程",
                teacher_id=teacher.id,
            )
            session.add(course)
            session.flush()

            service = PracticeRecommendationService()

            with patch(
                "app.services.practice_recommendation_service.generate_question_sync"
            ) as mock_gen:
                mock_gen.return_value = {
                    "question_text": "LLM 生成的真实题目",
                    "answer": "LLM 生成的真实答案",
                    "options": [],
                    "difficulty": "medium",
                    "category": "test",
                    "confidence": 0.7,
                    "reason_codes": ["llm_generated"],
                    "mapping_reason": "LLM 个性化生成",
                    "source": "llm",
                }

                run = service.create_recommendation(
                    session,
                    course_id=course.id,
                    student_id=student.id,
                    node_id=None,
                    purpose="diagnose",
                    cognitive_state=None,
                    item_count=2,
                    allow_generation=True,
                )

            assert isinstance(run, QuestionRecommendationRun)
            assert run.item_count == 2

            # 验证 generate_question_sync 被调用（题库为空，必须生成 2 个草稿）
            assert mock_gen.call_count == 2

            # 验证生成的草稿使用 LLM 输出，而不是占位字符串
            from app.models.practice_recommendation_model import (
                QuestionRecommendationItem, QuestionGenerationDraft,
            )
            items = session.exec(
                __import__("sqlmodel").select(QuestionRecommendationItem).where(
                    QuestionRecommendationItem.run_id == run.run_id
                )
            ).all()
            drafts = session.exec(
                __import__("sqlmodel").select(QuestionGenerationDraft).where(
                    QuestionGenerationDraft.course_id == course.id
                )
            ).all()

            assert len(drafts) == 2
            for draft in drafts:
                assert draft.question_text == "LLM 生成的真实题目"
                assert draft.answer == "LLM 生成的真实答案"
                assert "llm_generated" in draft.reason_codes
                assert draft.model_version == GENERATION_POLICY_VERSION
