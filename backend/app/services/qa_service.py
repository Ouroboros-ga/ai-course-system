"""
问答服务
负责处理用户与AI的问答交互
集成RAG检索增强生成
"""

import json
import re
from typing import Optional, List, Tuple, Dict, Any

from app.common.llm_client import llm_client, Message
from app.common.RAG import rag_pipeline
from app.common.prompts.qa import QA_SYSTEM_PROMPT, build_qa_prompt


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
        system_prompt = """你是一位专业的AI助教，帮助学生理解课程内容。

## 回答要求

1. **准确性**：基于提供的文档内容回答，不要编造信息
2. **清晰性**：用简洁易懂的语言解释概念
3. **引导性**：适当提出追问，引导学生深入思考
4. **引用标注**：如果引用文档内容，标注来源

## 回答格式

如果问题与文档相关：
- 先给出直接答案
- 再提供详细解释
- 最后提出引导性问题

如果问题与文档无关：
- 礼貌说明问题超出范围
- 建议与课程相关的问题

## 特殊情况

- 如果学生明显困惑，提供更基础的解释
- 如果学生理解良好，可以深入扩展
- 如果问题模糊，先澄清问题再回答"""

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

【学生问题】
{question}

请根据以上内容回答学生的问题。如果问题与文档内容相关，请结合文档内容给出详细解答。"""

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
        strategy: str = "hybrid"
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        使用RAG检索获取与问题相关的上下文
        
        Args:
            question: 用户问题
            top_k: 返回的相关文档数量
            strategy: 检索策略 (keyword/path/hybrid)
            
        Returns:
            tuple: (上下文文本, 来源列表)
        """
        try:
            retrieval_results = rag_pipeline.retrieve(
                question, strategy=strategy, top_k=top_k
            )
            
            if not retrieval_results:
                return "", []
            
            context_parts = []
            sources = []
            
            for i, result in enumerate(retrieval_results):
                context = rag_pipeline._retriever.get_context_for_result(result)
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
        strict_mode: bool = False
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
                question, top_k=rag_top_k
            )
        
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
            response = await llm_client.chat(messages, temperature=0.7)
        
        return {
            "answer": response.content,
            "rag_sources": rag_sources if rag_sources else None,
            "rag_context": rag_context if rag_context else None,
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


qa_service = QAService()
