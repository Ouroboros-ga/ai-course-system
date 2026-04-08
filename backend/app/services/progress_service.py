"""
学习进度服务
负责分析学习进度、理解程度、自适应调节
"""

from typing import Optional, List
from app.common.llm_client import llm_client, Message


class ProgressPromptBuilder:
    """进度分析Prompt构建器"""
    
    @staticmethod
    def build_node_location_prompt(question: str, nodes: List[dict]) -> tuple[str, str]:
        """
        构建节点定位Prompt
        
        Args:
            question: 学生问题
            nodes: 所有节点列表
            
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        system_prompt = """你是一位教学导航专家，根据学生的问题定位到对应的知识点节点。

请分析学生问题，找到最相关的节点，以JSON格式返回：

{
    "matched_node_id": "节点ID",
    "confidence": 0.85,
    "reasoning": "匹配理由",
    "related_nodes": ["其他相关节点ID"]
}

匹配规则：
1. 优先匹配问题中明确提到的知识点
2. 其次匹配问题内容与节点标题的相似度
3. 考虑知识点的先后顺序关系"""

        nodes_str = "\n".join([
            f"- [{n.get('id', n.get('chapter_id'))}] {n.get('title', '')} ({n.get('type', 'lecture')})"
            for n in nodes
        ])
        
        user_prompt = f"""学生问题: {question}

可用节点列表:
{nodes_str}

请找到最匹配的节点。"""

        return system_prompt, user_prompt
    
    @staticmethod
    def build_adaptive_adjustment_prompt(
        understanding_history: List[dict],
        current_node: dict
    ) -> tuple[str, str]:
        """
        构建自适应调节Prompt
        
        Args:
            understanding_history: 理解程度历史
            current_node: 当前节点
            
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        system_prompt = """你是一位自适应学习专家，根据学生的理解情况调整学习策略。

请分析学生的理解历史，给出调节建议，以JSON格式返回：

{
    "action": "continue/slow_down/review/skip",
    "reason": "调节原因",
    "suggested_duration_adjustment": 0,
    "additional_content_needed": false,
    "review_nodes": ["需要复习的节点ID"],
    "next_node_suggestion": "建议的下一个节点ID"
}

调节策略：
- continue: 理解良好，继续正常学习
- slow_down: 理解有困难，放慢节奏
- review: 需要复习前置知识
- skip: 已完全掌握，可以跳过"""

        history_str = "\n".join([
            f"- {h.get('timestamp')}: {h.get('level')} - {h.get('question', '')[:30]}"
            for h in understanding_history[-10:]
        ])
        
        user_prompt = f"""当前学习节点: {current_node.get('title', '未知')}

理解历史:
{history_str}

请给出自适应调节建议。"""

        return system_prompt, user_prompt


class ProgressService:
    """学习进度服务"""
    
    def __init__(self):
        self.prompt_builder = ProgressPromptBuilder()
    
    async def locate_node_by_question(
        self,
        question: str,
        nodes: List[dict]
    ) -> dict:
        """
        根据问题定位节点
        
        Args:
            question: 学生问题
            nodes: 节点列表
            
        Returns:
            dict: 定位结果
        """
        import json
        import re
        
        system_prompt, user_prompt = self.prompt_builder.build_node_location_prompt(
            question, nodes
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
            print(f"[ProgressService] 节点定位失败: {e}")
        
        return {
            "matched_node_id": nodes[0].get('id', nodes[0].get('chapter_id')) if nodes else None,
            "confidence": 0.5,
            "reasoning": "定位失败，使用默认节点",
            "related_nodes": []
        }
    
    async def get_adaptive_adjustment(
        self,
        understanding_history: List[dict],
        current_node: dict
    ) -> dict:
        """
        获取自适应调节建议
        
        Args:
            understanding_history: 理解历史
            current_node: 当前节点
            
        Returns:
            dict: 调节建议
        """
        import json
        import re
        
        system_prompt, user_prompt = self.prompt_builder.build_adaptive_adjustment_prompt(
            understanding_history, current_node
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
            print(f"[ProgressService] 自适应调节分析失败: {e}")
        
        return {
            "action": "continue",
            "reason": "分析失败，继续正常学习",
            "suggested_duration_adjustment": 0,
            "additional_content_needed": False,
            "review_nodes": [],
            "next_node_suggestion": None
        }


progress_service = ProgressService()
