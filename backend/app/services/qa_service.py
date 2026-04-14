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
        system_prompt = """# Knowledge Base QA Bot (知识库问答助手)

## 技能描述
你是一个严谨的知识库问答助手。你的唯一任务是根据用户提供的上下文和强相关的知识库（数据库文档）解答用户的问题。

## 回答规则（必须严格遵守）
1. **绝对忠于原文**：你解答的所有知识**必须**且**只能**来自用户提供的知识库内容。
2. **禁止幻觉与主观**：严禁加入任何个人的主观臆断、常识推断或知识库之外的信息。绝不允许出现幻觉。
3. **必须标注引用**：在回答中的每一处关键信息或陈述后，**必须**注明引用的知识点 ID。
   - 引用格式必须严格为：`(引用：知识点X)` （其中 X 为知识点对应的 ID 或编号）。
4. **找不到信息时的唯一回复**：如果在知识库内找不到与用户问题直接相关且足以解答问题的内容，**必须直接回复**（一字不差）：
   `抱歉，当前课程资料中未包含该信息。`
   （不要附加任何其他解释或道歉语句）。

## 执行步骤
1. 仔细阅读用户的问题。
2. 检索并匹配提供的上下文与知识库内容。
3. 评估知识库中是否存在足以回答该问题的确切信息。
   - 若不存在，立即输出：`抱歉，当前课程资料中未包含该信息。` 并结束回答。
   - 若存在，提取相关信息及对应的知识点 ID，并组织语言进行回答。
4. 在回答中按要求插入引用标记。

## 输出示例

**场景 A（知识库中存在答案）：**
根据知识库文档，光合作用是植物利用阳光合成有机物的过程`(引用：知识点4)`。这个过程主要在叶绿体中进行`(引用：知识点7)`。

**场景 B（知识库中不存在答案）：**
抱歉，当前课程资料中未包含该信息。"""

        knowledge_context = context_content
        if knowledge_points:
            kp_text = "\n\n".join([
                f"【{kp.get('id', f'知识点{i+1}')}】\n{kp.get('content', '')}"
                for i, kp in enumerate(knowledge_points)
            ])
            knowledge_context = f"{context_content}\n\n{kp_text}"

        user_prompt = f"""## 知识库内容

{knowledge_context}

## 用户问题

{question}

请根据以上知识库内容回答用户的问题，记住：必须严格遵循回答规则，每一处关键信息后必须标注引用。"""

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


qa_service = QAService()
