"""
问答服务
负责处理用户与AI的问答交互
"""

from typing import Optional, List
from app.common.llm_client import llm_client, Message


class QAPromptBuilder:
    """问答Prompt构建器"""
    
    @staticmethod
    def build_context_aware_prompt(
        question: str,
        context_content: str = "",
        history_messages: List[dict] = None,
        current_node: dict = None
    ) -> tuple[str, str]:
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
            context_parts.append(f"【课程文档内容】\n{context_content[:3000]}")
        
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
    def build_understanding_analysis_prompt(question: str, answer: str) -> tuple[str, str]:
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
    
    async def ask_question(
        self,
        question: str,
        context_content: str = "",
        history_messages: List[dict] = None,
        current_node: dict = None
    ) -> str:
        """
        回答学生问题
        
        Args:
            question: 学生问题
            context_content: 文档上下文
            history_messages: 历史消息
            current_node: 当前学习节点
            
        Returns:
            str: AI回答
        """
        system_prompt, user_prompt = self.prompt_builder.build_context_aware_prompt(
            question, context_content, history_messages, current_node
        )
        
        messages = [Message(role="system", content=system_prompt)]
        
        if history_messages:
            for msg in history_messages[-10:]:
                messages.append(Message(
                    role=msg.get("role", "user"),
                    content=msg.get("content", "")
                ))
        
        messages.append(Message(role="user", content=user_prompt))
        
        response = await llm_client.chat(messages)
        return response.content
    
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
        import json
        import re
        
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
        except Exception as e:
            print(f"[QAService] 分析失败: {e}")
        
        return {
            "understanding_level": "medium",
            "question_quality": "basic",
            "topic_keywords": [],
            "weak_points": [],
            "suggested_action": "continue",
            "reasoning": "分析失败，使用默认值"
        }


qa_service = QAService()
