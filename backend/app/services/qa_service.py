"""
问答服务
负责处理用户与AI的问答交互
集成RAG检索增强生成
"""

import json
import re
from typing import Optional, List, Tuple, Dict, Any

from app.common.llm_client import llm_client, Message
from app.platform.adapters.llm import LLMAdapter
from app.common.RAG import rag_pipeline
from app.platform.retrieval import RetrievalScope, retrieval_gateway
from app.common.prompts.qa import QA_SYSTEM_PROMPT, build_qa_prompt, QUIZ_SYSTEM_PROMPT, build_quiz_prompt


class QAPromptBuilder:
    """问答Prompt构建器"""
    
    @staticmethod
    def build_knowledge_base_qa_prompt(
        question: str,
        context_content: str,
        knowledge_points: List[dict] = None
    ) -> Tuple[str, str]:
        """
        构建严格的知识库问答Prompt
        
        Args:
            question: 用户问题
            context_content: 知识库上下文内容
            knowledge_points: 知识点列表，格式: [{"id": "知识点1", "content": "..."}]
            
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        system_prompt = QA_SYSTEM_PROMPT

        # 构建知识库内容
        knowledge_context = context_content
        if knowledge_points:
            kp_text = "\n\n".join([
                f"【{kp.get('id', f'知识点{i+1}')}】\n{kp.get('content', '')}"
                for i, kp in enumerate(knowledge_points)
            ])
            knowledge_context = f"{context_content}\n\n{kp_text}"

        # 使用 build_qa_prompt 构建用户提示词
        user_prompt = build_qa_prompt(question, [
            {"id": f"知识点{i+1}", "content": content}
            for i, content in enumerate(knowledge_context.split("\n\n"))
            if content.strip()
        ])

        return system_prompt, user_prompt
    
    @staticmethod
    def build_context_aware_prompt(
        question: str,
        context_content: str = "",
        history_messages: List[dict] = None,
        current_node: dict = None
    ) -> Tuple[str, str]:
        """
        构建基于上下文的问答Prompt
        
        Args:
            question: 用户问题
            context_content: 文档上下文内容
            history_messages: 历史消息列表
            current_node: 当前学习的节点信息
            
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        system_prompt = """你是一位经验丰富的大学讲师，正在为学生进行一对一辅导。你的回答风格应该像真正的老师在课堂上讲解一样自然流畅。

## 核心原则

1. **准确专业**：基于提供的课程资料回答，确保知识点的准确性。如果资料中没有相关信息，诚实告知学生。
2. **通俗易懂**：避免堆砌术语，用生动的例子和类比帮助学生理解抽象概念。
3. **循序渐进**：先给出核心结论，再展开细节说明，最后可以延伸到实际应用。
4. **互动启发**：在解释完知识点后，自然地引导学生思考更深层次的问题或相关应用场景。

## 回答风格要求

✅ **推荐做法**：
- 用连贯的段落直接回答，不要使用"首先/其次/最后"等机械结构
- 适当使用例子、类比、生活化场景来解释概念
- 在解释完核心内容后，自然地过渡到延伸思考："你觉得...""有没有想过..."
- 语气亲切但不失专业性，像导师和朋友之间的对话

❌ **禁止做法**：
- 绝对不要出现"直接答案"、"详细解释"、"引导性提问"这类标签或标题
- 不要使用编号列表（1. 2. 3.）来组织主要内容
- 不要在开头说"根据你的问题..."或"关于这个问题..."这类套话
- 避免过于学术化的长篇大论，保持简洁有力

## 示例对比

❌ 错误示例（不要这样回答）：
```
直接答案：电气工程是研究电能的学科。
详细解释：它包括电力系统、电力电子等领域。
引导性问题：你想了解哪个方向？
```

✅ 正确示例（应该这样回答）：
```
电气工程是一门非常实用的学科，简单来说就是研究"电"从产生到应用的整个过程。

想象一下，当你按下开关灯亮了，或者给手机插上充电器开始充电，背后都是电气工程的原理在工作。它主要涵盖几个方向：电力系统负责把电从发电厂送到千家万户，电力电子则专注于如何高效地转换和控制电能——比如电动汽车的电机控制、太阳能板的能量转换等等。

说到这里，不知道你是否对新能源领域感兴趣？现在风电、光伏这些清洁能源技术发展特别快，里面有很多电气工程的应用值得深入了解。
```

## 特殊情况处理

- 如果学生的问题比较基础，可以从最简单的概念讲起，逐步深入
- 如果学生已经理解得不错，可以适当拓展到前沿应用或行业动态
- 如果问题不够清晰，可以先确认学生的具体疑惑点再作答"""

        context_parts = []
        
        if context_content:
            context_parts.append(f"【课程文档内容】\n{context_content[:5000]}")
        
        if current_node:
            context_parts.append(
                f"【当前学习进度】\n"
                f"正在学习: {current_node.get('title', '未知')}\n"
                f"节点类型: {current_node.get('type', 'lecture')}"
            )
        
        context_str = "\n\n".join(context_parts) if context_parts else "（无文档上下文）"
        
        user_prompt = f"""{context_str}

【学生提问】
{question}

请以老师的身份，用自然流畅的语言回答这个问题的同时引导学生思考。记住：直接开始回答，不要加任何前缀或标题。"""

        return system_prompt, user_prompt
    
    @staticmethod
    def build_understanding_analysis_prompt(question: str, answer: str) -> Tuple[str, str]:
        """
        构建理解程度分析的Prompt
        
        Args:
            question: 学生问题
            answer: AI回答
            
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        system_prompt = """你是一位教学评估专家，分析学生对知识的理解程度。

请分析学生的提问，判断其理解水平，并以JSON格式返回：

{
    "understanding_level": "high/medium/low",
    "question_quality": "good/basic/confused/repeat",
    "topic_keywords": ["关键词1", "关键词2"],
    "weak_points": ["薄弱点1"],
    "suggested_action": "continue/review/practice",
    "reasoning": "判断理由"
}

字段说明：
- understanding_level: 理解程度
  - high: 问题深入，理解良好
  - medium: 问题基础，基本理解
  - low: 问题模糊或重复，需要帮助

- question_quality: 问题质量
  - good: 有深度的好问题
  - basic: 基础问题
  - confused: 表达混乱
  - repeat: 重复提问

- suggested_action: 建议操作
  - continue: 继续学习新内容
  - review: 复习当前内容
  - practice: 需要更多练习"""

        user_prompt = f"""学生问题: {question}

AI回答: {answer}

请分析学生的理解程度。"""

        return system_prompt, user_prompt


class QAService:
    """问答服务"""
    
    def __init__(self):
        self.prompt_builder = QAPromptBuilder()
    
    def retrieve_rag_context(
        self,
        question: str,
        top_k: int = 3,
        strategy: str = "hybrid",
        course_id: Optional[Any] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        使用RAG检索获取与问题相关的上下文

        Args:
            question: 用户问题
            top_k: 返回的相关文档数量
            strategy: 检索策略 (keyword/path/hybrid)
            course_id: 课程ID。传入时经统一 RetrievalGateway 按课程作用域检索，
                避免跨课程上下文污染；不传时走遗留全局树路径（已弃用，
                生产主链始终传入 course_id）。

        Returns:
            tuple: (上下文文本, 来源列表)
        """
        try:
            if course_id is not None:
                # 生产路径：显式课程作用域 -> 统一 Gateway -> Tree Provider
                chunks = retrieval_gateway.retrieve(
                    question,
                    scope=RetrievalScope.course(course_id),
                    top_k=top_k,
                )
                if not chunks:
                    return "", []
                context_parts: List[str] = []
                sources: List[Dict[str, Any]] = []
                for i, chunk in enumerate(chunks):
                    context_path = "/".join(chunk.path)
                    context_parts.append(
                        f"【来源{i+1}: {context_path}】\n{chunk.content}"
                    )
                    sources.append({
                        "path": context_path,
                        "score": chunk.retrieval_score,
                        "match_type": chunk.match_type,
                        "content_preview": chunk.metadata.get(
                            "matched_content_preview", ""
                        ),
                    })
                return "\n\n---\n\n".join(context_parts), sources

            # 遗留无作用域路径（已弃用，生产主链不触发）：委托 rag_pipeline 全局树
            retrieval_results = rag_pipeline.retrieve(
                question, strategy=strategy, top_k=top_k
            )
            if not retrieval_results:
                return "", []
            context_parts = []
            sources = []
            for i, result in enumerate(retrieval_results):
                context = rag_pipeline.get_context_for_result(result)
                context_parts.append(f"【来源{i+1}: {result.context_path}】\n{context}")
                sources.append({
                    "path": result.context_path,
                    "score": result.score,
                    "match_type": result.match_type,
                    "content_preview": result.matched_content[:200] if result.matched_content else "",
                })
            return "\n\n---\n\n".join(context_parts), sources
        except Exception as e:
            print(f"[QAService] RAG检索失败: {str(e)}")
            return "", []
    
    async def ask_question_with_rag(
        self,
        question: str,
        course_context: str = "",
        history_messages: List[dict] = None,
        current_node: dict = None,
        use_rag: bool = True,
        rag_top_k: int = 3,
        strict_mode: bool = False,
        course_id: Optional[Any] = None,
        student_id: Optional[Any] = None,
        allow_r2_student_answer: bool = False,
    ) -> Dict[str, Any]:
        """
        基于RAG检索增强的问答

        Args:
            question: 用户问题
            course_context: 课程文档上下文
            history_messages: 历史消息
            current_node: 当前学习节点
            use_rag: 是否使用RAG检索
            rag_top_k: RAG检索返回数量
            strict_mode: 是否使用严格知识库模式（带引用标注）
            course_id: 课程ID，用于RAG按课程隔离检索，避免跨课程污染

        Returns:
            dict: {
                "answer": "回答内容",
                "rag_sources": [...],
                "rag_context": "RAG检索上下文"
            }
        """
        rag_context = ""
        rag_sources = []

        if use_rag:
            rag_context, rag_sources = self.retrieve_rag_context(
                question, top_k=rag_top_k, course_id=course_id
            )

        # ---- P1-09 R2 sidecar retrieval shadow (mainline wiring) ----
        # Triggered after the course-scoped V1 retrieval attempt and before
        # the single LLM call. R2 may supply evidence when V1 has no result.
        # When DOCUMENT_KG_RUNTIME_MODE is effectively v2_shadow AND the
        # course has an Evidence sidecar AND R2 returns citation-closed
        # hits, R2 retrieval REPLACES rag_context/rag_sources that feed the
        # single (still-V1) LLM call. No second LLM call. When the flag is
        # off, the course has no sidecar, R2 abstains, or any runtime error
        # occurs, triggered=False and V1 retrieval is left untouched
        # (business fail-closed). Default flag v1_only = no-op = pure V1.
        retrieval_source = "none"
        retrieval_metadata = {
            "policy_version": "r2-retrieval-v1.0",
            "evidence_ids": [],
            "fallback_reason": None,
            "hit_count": 0,
        }
        if use_rag:
            if rag_sources:
                retrieval_source = "v1_treerag"
            else:
                retrieval_metadata["fallback_reason"] = "v1_no_results"
            if not allow_r2_student_answer:
                retrieval_metadata["fallback_reason"] = "student_answer_gate_disabled"
            else:
                try:
                    from app.platform.shadow.r2_retrieval_shadow import (
                        trigger_r2_retrieval_shadow,
                    )
                    r2 = trigger_r2_retrieval_shadow(
                        question=question,
                        course_id=course_id,
                        v1_context=rag_context,
                        v1_sources=rag_sources,
                    )
                    if r2.triggered:
                        rag_context, rag_sources = r2.rag_context, r2.rag_sources
                        retrieval_source = "v2_r2_sidecar"
                        retrieval_metadata["hit_count"] = r2.hit_count
                        retrieval_metadata["evidence_ids"] = sorted({
                            evidence_id
                            for source in (r2.rag_sources or [])
                            for evidence_id in source.get("evidence_refs", [])
                        })
                    else:
                        retrieval_metadata["fallback_reason"] = r2.fallback_reason
                except Exception as r2_err:  # noqa: BLE001
                    print(
                        "[R2 retrieval] suppressed (V1 unaffected): "
                        f"{type(r2_err).__name__}"
                    )
                    retrieval_metadata["fallback_reason"] = (
                        f"r2_exception:{type(r2_err).__name__}"
                    )

        # ---- P1-09 G3C: V2 evidence/retrieval/citation shadow ----
        # Triggered AFTER V1 retrieval succeeds, BEFORE the V1 LLM call.
        # HARD CONSTRAINT (ADR-0006 §G3C): shadow does NOT call the
        # generation model (no second LLM call, no second answer). It only
        # runs V2 retrieval + evidence binding + Citation validation, writing
        # a V1-ragSources-vs-V2-candidates trace. Shadow results are NOT
        # returned to the user. trigger_evidence_shadow catches ALL errors
        # (business fail-closed) so V1 is never affected; outer try/except
        # is a second safety net. Default flag v1_only = no-op.
        if use_rag and rag_sources:
            try:
                from app.platform.shadow.evidence_shadow import trigger_evidence_shadow
                trigger_evidence_shadow(
                    question=question,
                    course_id=course_id,
                    v1_sources=rag_sources,
                )
            except Exception as evidence_shadow_err:  # noqa: BLE001
                print(f"[G3C evidence shadow] suppressed (V1 unaffected): {evidence_shadow_err}")

        # ---- P1-09 G3D2: V2 memory-candidate shadow (NOT injected into QA) ----
        # HARD CONSTRAINT (ADR-0006 §G3D2): candidate memory is NOT injected
        # into the formal QA prompt. The V1 answer is unchanged. This only
        # records "what memory context WOULD be provided". Default flag
        # disabled = no-op. Business fail-closed; V1 never affected.
        try:
            from app.platform.shadow.memory_candidate_shadow import trigger_memory_candidate_shadow
            trigger_memory_candidate_shadow(
                question=question,
                student_id=student_id,
                course_id=course_id,
                v1_context={"rag_sources": rag_sources} if use_rag else {},
            )
        except Exception as memory_shadow_err:  # noqa: BLE001
            print(f"[G3D2 memory shadow] suppressed (V1 unaffected): {memory_shadow_err}")

        # ---- P1-09 G3D3: V2 safety dry-run (does NOT block V1) ----
        # Records would_allow / would_refuse; V1 is never blocked.
        # Default flag disabled = no-op. Business fail-closed.
        try:
            from app.platform.shadow.safety_dryrun_shadow import trigger_safety_dryrun
            trigger_safety_dryrun(
                question=question,
                course_id=course_id,
            )
        except Exception as safety_shadow_err:  # noqa: BLE001
            print(f"[G3D3 safety dry-run] suppressed (V1 unaffected): {safety_shadow_err}")

        full_context = course_context
        if rag_context:
            full_context = f"{course_context}\n\n【RAG检索相关内容】\n{rag_context}"
        
        if strict_mode and full_context:
            system_prompt, user_prompt = self.prompt_builder.build_knowledge_base_qa_prompt(
                question, full_context
            )
            messages = [Message(role="system", content=system_prompt)]
            
            if history_messages:
                for msg in history_messages[-5:]:
                    messages.append(Message(
                        role=msg.get("role", "user"),
                        content=msg.get("content", "")
                    ))
            
            messages.append(Message(role="user", content=user_prompt))
            response = await llm_client.chat(messages, temperature=0.1)
        else:
            system_prompt, user_prompt = self.prompt_builder.build_context_aware_prompt(
                question, full_context, history_messages, current_node
            )
            messages = [Message(role="system", content=system_prompt)]
            
            if history_messages:
                for msg in history_messages[-10:]:
                    messages.append(Message(
                        role=msg.get("role", "user"),
                        content=msg.get("content", "")
                    ))
            
            messages.append(Message(role="user", content=user_prompt))
            llm_result = await LLMAdapter(llm_client).chat(messages, temperature=0.7)
            if not llm_result.success:
                raise RuntimeError(llm_result.error_message or "LLM chat failed")
            response = llm_result.data
        
        return {
            "answer": response.content,
            "rag_sources": rag_sources if rag_sources else None,
            "rag_context": rag_context if rag_context else None,
            "retrieval_source": retrieval_source,
            "retrieval_metadata": retrieval_metadata,
        }
    
    async def ask_question_with_knowledge_base(
        self,
        question: str,
        context_content: str,
        knowledge_points: List[dict] = None,
        history_messages: List[dict] = None
    ) -> str:
        """
        基于知识库的严格问答
        
        Args:
            question: 用户问题
            context_content: 知识库上下文
            knowledge_points: 知识点列表
            history_messages: 历史消息
            
        Returns:
            str: AI回答（带引用标注）
        """
        system_prompt, user_prompt = self.prompt_builder.build_knowledge_base_qa_prompt(
            question, context_content, knowledge_points
        )
        
        messages = [Message(role="system", content=system_prompt)]
        
        if history_messages:
            for msg in history_messages[-5:]:
                messages.append(Message(
                    role=msg.get("role", "user"),
                    content=msg.get("content", "")
                ))
        
        messages.append(Message(role="user", content=user_prompt))
        
        response = await llm_client.chat(messages, temperature=0.1)
        return response.content
    
    async def ask_question(
        self,
        question: str,
        context_content: str = "",
        history_messages: List[dict] = None,
        current_node: dict = None
    ) -> str:
        """
        回答学生问题（简化版，仅返回回答文本）
        
        Args:
            question: 学生问题
            context_content: 文档上下文
            history_messages: 历史消息
            current_node: 当前学习节点
            
        Returns:
            str: AI回答
        """
        result = await self.ask_question_with_rag(
            question=question,
            course_context=context_content,
            history_messages=history_messages,
            current_node=current_node,
            use_rag=False
        )
        return result["answer"]
    
    async def analyze_understanding(
        self,
        question: str,
        answer: str
    ) -> dict:
        """
        分析学生理解程度
        
        Args:
            question: 学生问题
            answer: AI回答
            
        Returns:
            dict: 分析结果
        """
        system_prompt, user_prompt = self.prompt_builder.build_understanding_analysis_prompt(
            question, answer
        )
        
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt)
        ]
        
        try:
            response = await llm_client.chat(messages)
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        
        return {
            "understanding_level": "medium",
            "question_quality": "basic",
            "topic_keywords": [],
            "weak_points": [],
            "suggested_action": "continue",
            "reasoning": "分析失败，使用默认值"
        }
    
    async def ask_question_with_multi_kb(
        self,
        question: str,
        kb_ids: List[int] = None,
        subject: str = None,
        history_messages: List[dict] = None,
        top_k: int = 5,
        strict_mode: bool = True
    ) -> Dict[str, Any]:
        """
        基于多学科知识库的问答
        
        Args:
            question: 用户问题
            kb_ids: 知识库ID列表
            subject: 学科过滤 (math/physics/chemistry/...)
            history_messages: 历史消息
            top_k: 返回知识点数量
            strict_mode: 是否使用严格知识库模式
            
        Returns:
            dict: {
                "answer": "回答内容",
                "knowledge_points": [...],
                "kb_context": "知识库上下文"
            }
        """
        from sqlmodel import Session
        from app.models.database import get_session
        from app.models.knowledge_model import SubjectType
        from app.services.knowledge_service import KnowledgeSearchService
        
        session = next(get_session())
        
        try:
            subject_enum = None
            if subject:
                try:
                    subject_enum = SubjectType(subject)
                except ValueError:
                    pass
            
            kb_context, knowledge_points = KnowledgeSearchService.get_context_for_question(
                session=session,
                question=question,
                kb_ids=kb_ids,
                subject=subject_enum,
                top_k=top_k,
            )
            
            if not kb_context:
                return {
                    "answer": "抱歉，当前知识库中未找到相关信息。",
                    "knowledge_points": [],
                    "kb_context": None,
                }
            
            if strict_mode:
                answer = await self.ask_question_with_knowledge_base(
                    question=question,
                    context_content=kb_context,
                    knowledge_points=knowledge_points,
                    history_messages=history_messages,
                )
            else:
                result = await self.ask_question_with_rag(
                    question=question,
                    course_context=kb_context,
                    history_messages=history_messages,
                    use_rag=False,
                    strict_mode=False,
                )
                answer = result["answer"]
            
            return {
                "answer": answer,
                "knowledge_points": knowledge_points,
                "kb_context": kb_context,
            }
            
        except Exception as e:
            print(f"[QAService] 多学科知识库问答失败: {str(e)}")
            return {
                "answer": f"知识库检索失败: {str(e)}",
                "knowledge_points": [],
                "kb_context": None,
            }
        finally:
            session.close()
    
    def retrieve_from_multi_kb(
        self,
        question: str,
        kb_ids: List[int] = None,
        subject: str = None,
        top_k: int = 5,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        从多学科知识库检索上下文
        
        Args:
            question: 用户问题
            kb_ids: 知识库ID列表
            subject: 学科过滤
            top_k: 返回知识点数量
            
        Returns:
            tuple: (上下文文本, 知识点列表)
        """
        from sqlmodel import Session
        from app.models.database import get_session
        from app.models.knowledge_model import SubjectType
        from app.services.knowledge_service import KnowledgeSearchService
        
        session = next(get_session())
        
        try:
            subject_enum = None
            if subject:
                try:
                    subject_enum = SubjectType(subject)
                except ValueError:
                    pass
            
            kb_context, knowledge_points = KnowledgeSearchService.get_context_for_question(
                session=session,
                question=question,
                kb_ids=kb_ids,
                subject=subject_enum,
                top_k=top_k,
            )
            
            return kb_context, knowledge_points
            
        except Exception as e:
            print(f"[QAService] 多学科知识库检索失败: {str(e)}")
            return "", []
        finally:
            session.close()

    async def generate_quiz(
        self,
        node_content: str,
        node_title: str = "",
        course_context: str = "",
    ) -> Dict[str, Any]:
        """
        根据课程节点内容生成选择题

        Args:
            node_content: 节点讲解内容
            node_title: 节点标题
            course_context: 课程文档上下文（可选，用于增强出题质量）

        Returns:
            dict: {
                "quiz": {
                    "question": "...",
                    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
                    "correct_answer": "A",
                    "explanation": "..."
                }
            }
        """
        full_content = node_content
        if course_context:
            full_content = f"{course_context[:3000]}\n\n{node_content}"

        user_prompt = build_quiz_prompt(full_content, node_title)

        messages = [
            Message(role="system", content=QUIZ_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]

        try:
            response = await llm_client.chat(messages, temperature=0.7, max_tokens=1000)
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                quiz_data = json.loads(json_match.group())
                required_keys = {"question", "options", "correct_answer", "explanation"}
                if required_keys.issubset(quiz_data.keys()):
                    if isinstance(quiz_data["options"], dict) and len(quiz_data["options"]) >= 2:
                        valid_answers = {"A", "B", "C", "D"}
                        if quiz_data["correct_answer"] in valid_answers:
                            return {"quiz": quiz_data}

            print(f"[QAService] 选择题JSON解析失败或格式不合法: {response.content[:200]}")
            return {"quiz": None, "error": "生成格式异常"}
        except json.JSONDecodeError as e:
            print(f"[QAService] 选择题JSON解析错误: {str(e)}")
            return {"quiz": None, "error": "JSON解析失败"}
        except Exception as e:
            print(f"[QAService] 选择题生成失败: {str(e)}")
            return {"quiz": None, "error": str(e)}


qa_service = QAService()
