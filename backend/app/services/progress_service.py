"""
进度续接与理解度分析服务
实现自然语言分析学生提问，判断理解程度，定位学习节点，调节讲授节奏
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from sqlmodel import Session, select

from app.common.llm_client import llm_client, Message
from app.models.progress_model import (
    LearningProgress,
    NodeProgress,
    UnderstandingAnalysis,
    UnderstandingLevel,
    LearningStatus,
)
from app.models.course_model import Course, CourseScript, ScriptNode
from app.models.user_model import ChatMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UnderstandingAnalyzer:
    """
    理解度分析器
    使用大模型API分析学生提问内容，判断理解程度
    """

    async def analyze_question(
        self,
        question: str,
        node_content: str,
        node_title: str,
        conversation_history: List[ChatMessage] = None,
    ) -> Dict:
        """
        分析学生提问，判断理解程度

        Args:
            question: 学生提问内容
            node_content: 当前节点的讲解内容
            node_title: 当前节点标题
            conversation_history: 历史对话记录

        Returns:
            {
                "understanding_level": "low/medium/high/excellent",
                "understanding_score": 0.0-1.0,
                "keywords_mastered": ["关键词1", "关键词2"],
                "keywords_weak": ["薄弱点1", "薄弱点2"],
                "analysis_reason": "分析原因",
                "suggestions": "学习建议",
                "need_review": True/False,
                "related_node_ids": [1, 2, 3]
            }
        """
        system_prompt = """你是一位经验丰富的教学分析专家。请分析学生的提问内容，判断其对当前知识点的理解程度。

## 分析维度

1. **理解程度等级**：
   - excellent (0.85-1.0): 完全理解，能提出深入问题或应用知识
   - high (0.7-0.84): 基本理解，问题集中在细节或拓展
   - medium (0.5-0.69): 部分理解，存在概念混淆或应用困难
   - low (0.0-0.49): 理解困难，问题基础或偏离核心概念

2. **关键词掌握情况**：
   - 已掌握的关键词：学生在提问中正确使用的专业术语
   - 薄弱关键词：学生理解有误或未提及的核心概念

3. **问题类型识别**：
   - 概念澄清类：对基本概念不理解
   - 应用困难类：理解概念但不会应用
   - 拓展深入类：想了解更多细节或关联知识
   - 纠错类：发现或质疑内容错误

## 输出格式

请严格按照以下JSON格式返回，不要添加任何其他内容：

```json
{
    "understanding_level": "low/medium/high/excellent",
    "understanding_score": 0.75,
    "keywords_mastered": ["关键词1", "关键词2"],
    "keywords_weak": ["薄弱点1"],
    "analysis_reason": "学生提问显示其对核心概念有基本理解，但在应用层面存在困惑...",
    "suggestions": "建议通过实例演示加深理解，重点关注...",
    "need_review": false,
    "confidence_score": 0.85
}
```"""

        user_prompt = f"""请分析以下学生的提问：

## 当前学习内容
**节点标题**: {node_title}
**讲解内容**: 
{node_content[:1000]}

## 学生提问
{question}

## 历史对话（最近3轮）
{self._format_history(conversation_history[-6:] if conversation_history else [])}

请判断学生的理解程度，并给出学习建议。"""

        try:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]

            response = await llm_client.chat(messages, temperature=0.3, max_tokens=1000)

            result = self._parse_analysis_result(response.content)

            logger.info(f"[理解度分析] 等级: {result['understanding_level']}, 分数: {result['understanding_score']}")

            return result

        except Exception as e:
            logger.error(f"[理解度分析失败] {str(e)}")
            return self._get_default_analysis()

    def _format_history(self, messages: List[ChatMessage]) -> str:
        """格式化历史对话"""
        if not messages:
            return "无历史对话"

        formatted = []
        for msg in messages:
            role = "学生" if msg.role.value == "user" else "AI助教"
            formatted.append(f"{role}: {msg.content[:100]}")

        return "\n".join(formatted)

    def _parse_analysis_result(self, content: str) -> Dict:
        """解析AI返回的分析结果"""
        try:
            import re

            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                result = json.loads(json_match.group())

                level_map = {
                    "excellent": UnderstandingLevel.EXCELLENT,
                    "high": UnderstandingLevel.HIGH,
                    "medium": UnderstandingLevel.MEDIUM,
                    "low": UnderstandingLevel.LOW,
                }

                result["understanding_level"] = level_map.get(
                    result.get("understanding_level", "medium").lower(),
                    UnderstandingLevel.MEDIUM,
                )

                return result
        except Exception as e:
            logger.warning(f"解析分析结果失败: {str(e)}")

        return self._get_default_analysis()

    def _get_default_analysis(self) -> Dict:
        """返回默认分析结果"""
        return {
            "understanding_level": UnderstandingLevel.MEDIUM,
            "understanding_score": 0.5,
            "keywords_mastered": [],
            "keywords_weak": [],
            "analysis_reason": "自动分析失败，使用默认中等理解度",
            "suggestions": "建议继续学习，如有疑问可随时提问",
            "need_review": False,
            "confidence_score": 0.5,
        }


class NodeLocator:
    """
    学习节点定位器
    根据学生提问内容，定位最相关的学习节点
    """

    async def locate_relevant_nodes(
        self,
        question: str,
        script_nodes: List[ScriptNode],
        current_node_id: int,
        top_k: int = 3,
    ) -> List[Tuple[int, float, str]]:
        """
        定位与提问最相关的节点

        Args:
            question: 学生提问
            script_nodes: 所有脚本节点
            current_node_id: 当前节点ID
            top_k: 返回前k个最相关节点

        Returns:
            [(node_id, relevance_score, reason), ...]
        """
        system_prompt = """你是一位教学导航专家。根据学生的提问，找出最相关的学习节点。

## 任务
1. 分析学生提问的核心知识点
2. 从给定的节点列表中找出最相关的节点
3. 判断是否需要回到之前的节点复习

## 输出格式
严格按照JSON格式返回：

```json
{
    "relevant_nodes": [
        {
            "node_id": 1,
            "relevance_score": 0.95,
            "reason": "学生问题涉及该节点的核心概念",
            "need_jump": false
        }
    ]
}
```

注意：
- relevance_score: 0.0-1.0，表示相关程度
- need_jump: true表示需要跳转到该节点，false表示仅作参考
- 最多返回3个节点，按相关性排序"""

        nodes_info = []
        for node in script_nodes:
            nodes_info.append(
                f"节点ID: {node.id}, 标题: {node.title}, 类型: {node.node_type.value}, "
                f"内容摘要: {node.content[:200]}"
            )

        user_prompt = f"""学生提问: {question}

当前节点ID: {current_node_id}

可选节点列表:
{chr(10).join(nodes_info)}

请找出最相关的学习节点。"""

        try:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]

            response = await llm_client.chat(messages, temperature=0.3, max_tokens=800)

            import re

            json_match = re.search(r"\{[\s\S]*\}", response.content)
            if json_match:
                result = json.loads(json_match.group())

                nodes = []
                for item in result.get("relevant_nodes", [])[:top_k]:
                    nodes.append(
                        (
                            item["node_id"],
                            item["relevance_score"],
                            item["reason"],
                            item.get("need_jump", False),
                        )
                    )

                return nodes

        except Exception as e:
            logger.error(f"节点定位失败: {str(e)}")

        return [(current_node_id, 1.0, "保持当前节点", False)]


class PaceAdjuster:
    """
    讲授节奏调节器
    根据学生理解程度，调整后续讲授的节奏
    """

    def calculate_pace_adjustment(
        self,
        understanding_level: UnderstandingLevel,
        understanding_score: float,
        question_count: int,
        time_spent: int,
    ) -> Dict:
        """
        计算节奏调整方案

        Args:
            understanding_level: 理解等级
            understanding_score: 理解分数
            question_count: 提问次数
            time_spent: 花费时间(秒)

        Returns:
            {
                "speed_factor": 0.8-1.5,  # 讲授速度系数
                "need_slow_down": True/False,
                "need_extra_examples": True/False,
                "need_review_previous": True/False,
                "recommended_actions": ["动作1", "动作2"],
                "next_node_strategy": "continue/review/skip/deepen"
            }
        """
        adjustment = {
            "speed_factor": 1.0,
            "need_slow_down": False,
            "need_extra_examples": False,
            "need_review_previous": False,
            "recommended_actions": [],
            "next_node_strategy": "continue",
        }

        if understanding_level == UnderstandingLevel.LOW:
            adjustment.update(
                {
                    "speed_factor": 0.7,
                    "need_slow_down": True,
                    "need_extra_examples": True,
                    "need_review_previous": True,
                    "next_node_strategy": "review",
                    "recommended_actions": [
                        "降低讲授速度至70%",
                        "提供更多实例演示",
                        "回顾前置知识点",
                        "建议学生重新学习当前节点",
                    ],
                }
            )

        elif understanding_level == UnderstandingLevel.MEDIUM:
            adjustment.update(
                {
                    "speed_factor": 0.85,
                    "need_slow_down": True,
                    "need_extra_examples": True,
                    "next_node_strategy": "deepen",
                    "recommended_actions": [
                        "适当降低讲授速度至85%",
                        "补充实例说明",
                        "重点讲解薄弱环节",
                    ],
                }
            )

        elif understanding_level == UnderstandingLevel.HIGH:
            adjustment.update(
                {
                    "speed_factor": 1.0,
                    "next_node_strategy": "continue",
                    "recommended_actions": ["保持正常讲授速度", "可以进入下一知识点"],
                }
            )

        else:
            adjustment.update(
                {
                    "speed_factor": 1.2,
                    "next_node_strategy": "skip",
                    "recommended_actions": [
                        "可以加快讲授速度至120%",
                        "提供拓展性内容",
                        "建议跳过基础示例",
                    ],
                }
            )

        if question_count > 3 and understanding_score < 0.6:
            adjustment["need_slow_down"] = True
            adjustment["speed_factor"] = min(adjustment["speed_factor"], 0.75)
            adjustment["recommended_actions"].append("多次提问且理解度较低，建议暂停新内容学习")

        logger.info(
            f"[节奏调整] 策略: {adjustment['next_node_strategy']}, "
            f"速度系数: {adjustment['speed_factor']}"
        )

        return adjustment


class ProgressService:
    """
    进度续接服务主类
    整合理解度分析、节点定位、节奏调节
    """

    def __init__(self):
        self.analyzer = UnderstandingAnalyzer()
        self.locator = NodeLocator()
        self.adjuster = PaceAdjuster()

    async def handle_student_question(
        self,
        session: Session,
        user_id: int,
        course_id: int,
        question: str,
        current_node_id: int,
        chat_messages: List[ChatMessage] = None,
    ) -> Dict:
        """
        处理学生提问的完整流程

        Returns:
            {
                "understanding": {...},
                "pace_adjustment": {...},
                "node_recommendation": {...},
                "progress_update": {...}
            }
        """
        logger.info(f"[进度服务] 处理用户 {user_id} 的提问")

        progress = self._get_or_create_progress(session, user_id, course_id)
        current_node = session.get(ScriptNode, current_node_id)

        if not current_node:
            logger.error(f"节点 {current_node_id} 不存在")
            return {"error": "节点不存在"}

        understanding = await self.analyzer.analyze_question(
            question=question,
            node_content=current_node.content,
            node_title=current_node.title,
            conversation_history=chat_messages,
        )

        analysis_record = UnderstandingAnalysis(
            progress_id=progress.id,
            node_id=current_node_id,
            understanding_level=understanding["understanding_level"],
            understanding_score=understanding["understanding_score"],
            analysis_reason=understanding["analysis_reason"],
            suggestions=understanding.get("suggestions"),
            keywords_mastered=json.dumps(
                understanding.get("keywords_mastered", []), ensure_ascii=False
            ),
            keywords_weak=json.dumps(
                understanding.get("keywords_weak", []), ensure_ascii=False
            ),
        )
        session.add(analysis_record)
        session.commit()

        script = session.exec(
            select(CourseScript).where(CourseScript.course_id == course_id)
        ).first()

        if script:
            all_nodes = session.exec(
                select(ScriptNode)
                .where(ScriptNode.script_id == script.id)
                .order_by(ScriptNode.node_index)
            ).all()

            relevant_nodes = await self.locator.locate_relevant_nodes(
                question=question,
                script_nodes=all_nodes,
                current_node_id=current_node_id,
            )
        else:
            relevant_nodes = [(current_node_id, 1.0, "保持当前节点", False)]

        node_progress = self._get_or_create_node_progress(
            session, progress.id, current_node_id, current_node.node_index
        )
        node_progress.question_count += 1
        node_progress.understanding_level = understanding["understanding_level"]
        node_progress.understanding_score = understanding["understanding_score"]
        session.commit()

        pace_adjustment = self.adjuster.calculate_pace_adjustment(
            understanding_level=understanding["understanding_level"],
            understanding_score=understanding["understanding_score"],
            question_count=node_progress.question_count,
            time_spent=node_progress.time_spent,
        )

        progress_update = self._update_progress(
            session, progress, node_progress, understanding, pace_adjustment
        )

        return {
            "understanding": {
                "level": understanding["understanding_level"].value,
                "score": understanding["understanding_score"],
                "keywords_mastered": understanding.get("keywords_mastered", []),
                "keywords_weak": understanding.get("keywords_weak", []),
                "reason": understanding["analysis_reason"],
                "suggestions": understanding.get("suggestions"),
            },
            "pace_adjustment": pace_adjustment,
            "node_recommendation": {
                "current_node": {
                    "id": current_node_id,
                    "title": current_node.title,
                },
                "relevant_nodes": [
                    {
                        "node_id": node_id,
                        "relevance": score,
                        "reason": reason,
                        "need_jump": need_jump,
                    }
                    for node_id, score, reason, need_jump in relevant_nodes
                ],
            },
            "progress_update": progress_update,
        }

    def _get_or_create_progress(
        self, session: Session, user_id: int, course_id: int
    ) -> LearningProgress:
        """获取或创建学习进度记录"""
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        if not progress:
            progress = LearningProgress(
                user_id=user_id,
                course_id=course_id,
                status=LearningStatus.IN_PROGRESS,
                started_at=datetime.utcnow(),
            )
            session.add(progress)
            session.commit()
            session.refresh(progress)

        return progress

    def _get_or_create_node_progress(
        self, session: Session, progress_id: int, node_id: int, node_index: int
    ) -> NodeProgress:
        """获取或创建节点进度记录"""
        node_progress = session.exec(
            select(NodeProgress).where(
                NodeProgress.progress_id == progress_id, NodeProgress.node_id == node_id
            )
        ).first()

        if not node_progress:
            node_progress = NodeProgress(
                progress_id=progress_id,
                node_id=node_id,
                node_index=node_index,
                first_accessed_at=datetime.utcnow(),
            )
            session.add(node_progress)
            session.commit()
            session.refresh(node_progress)

        return node_progress

    def _update_progress(
        self,
        session: Session,
        progress: LearningProgress,
        node_progress: NodeProgress,
        understanding: Dict,
        pace_adjustment: Dict,
    ) -> Dict:
        """更新学习进度"""
        progress.last_accessed_at = datetime.utcnow()
        progress.session_count += 1
        session.commit()

        return {
            "completion_rate": progress.completion_rate,
            "status": progress.status.value,
            "session_count": progress.session_count,
            "current_node_index": node_progress.node_index,
        }

    async def get_progress_visualization(
        self, session: Session, user_id: int, course_id: int
    ) -> Dict:
        """
        获取学习进度可视化数据
        """
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        if not progress:
            return {"error": "未找到学习进度"}

        script = session.exec(
            select(CourseScript).where(CourseScript.course_id == course_id)
        ).first()

        nodes_data = []
        if script:
            nodes = session.exec(
                select(ScriptNode)
                .where(ScriptNode.script_id == script.id)
                .order_by(ScriptNode.node_index)
            ).all()

            for node in nodes:
                node_prog = session.exec(
                    select(NodeProgress).where(
                        NodeProgress.progress_id == progress.id,
                        NodeProgress.node_id == node.id,
                    )
                ).first()

                nodes_data.append(
                    {
                        "id": node.id,
                        "index": node.node_index,
                        "title": node.title,
                        "type": node.node_type.value,
                        "is_key_point": node.is_key_point,
                        "duration": node.duration,
                        "is_completed": node_prog.is_completed if node_prog else False,
                        "understanding_level": node_prog.understanding_level.value
                        if node_prog and node_prog.understanding_level
                        else None,
                        "understanding_score": node_prog.understanding_score
                        if node_prog
                        else None,
                        "question_count": node_prog.question_count if node_prog else 0,
                    }
                )

        analyses = session.exec(
            select(UnderstandingAnalysis)
            .where(UnderstandingAnalysis.progress_id == progress.id)
            .order_by(UnderstandingAnalysis.created_at.desc())
            .limit(10)
        ).all()

        return {
            "overall_progress": {
                "completion_rate": progress.completion_rate,
                "status": progress.status.value,
                "total_learning_time": progress.total_learning_time,
                "session_count": progress.session_count,
                "current_node_index": progress.current_node_index,
            },
            "nodes_progress": nodes_data,
            "recent_analyses": [
                {
                    "node_id": a.node_id,
                    "level": a.understanding_level.value,
                    "score": a.understanding_score,
                    "reason": a.analysis_reason,
                    "created_at": a.created_at.isoformat(),
                }
                for a in analyses
            ],
        }


progress_service = ProgressService()
