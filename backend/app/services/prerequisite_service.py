"""
前置知识智能跳转服务
实现AI驱动的知识缺陷检测、多层跳转管理、学习路径可视化
"""

import json
import logging
import uuid
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, select, func

from app.common.llm_client import llm_client, Message
from app.core.time_utils import utcnow_aware
from app.models.progress_model import (
    LearningProgress,
    NodeProgress,
    UnderstandingAnalysis,
    LearningJumpHistory,
    UnderstandingLevel,
)
from app.models.course_model import Course, CourseScript, ScriptNode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PrerequisiteAnalyzer:
    """
    前置知识缺陷分析器
    使用AI分析学生提问，识别可能的前置知识盲区
    """

    async def analyze_prerequisite_gaps(
        self,
        question: str,
        current_node: ScriptNode,
        course_id: int,
        user_id: int,
        session: Session,
        conversation_history: List[Dict] = None,
    ) -> Dict:
        """
        分析学生提问是否涉及前置知识缺陷
        
        Args:
            question: 学生提问内容
            current_node: 当前学习的节点
            course_id: 课程ID
            user_id: 学生ID
            session: 数据库会话
            conversation_history: 历史对话记录
            
        Returns:
            {
                "has_gaps": bool,
                "overall_confidence": float (0-1),
                "weak_prerequisites": [
                    {
                        "prerequisite_id": int,
                        "title": str,
                        "reason": str,
                        "confidence": float,
                        "target_node_index": int,
                        "urgency_level": str  # high/medium/low
                    }
                ],
                "suggested_action": str,  # "jump_to_review" / "continue" / "suggest_review"
                "analysis_summary": str
            }
        """
        
        # 1. 获取当前节点关联的知识点及其前置关系
        prerequisite_kps = self._get_prerequisite_knowledge_points(
            session, current_node.id, course_id
        )
        
        if not prerequisite_kps:
            # 没有配置前置知识点，无需检测
            return {
                "has_gaps": False,
                "overall_confidence": 0.0,
                "weak_prerequisites": [],
                "suggested_action": "continue",
                "analysis_summary": "该知识点未配置前置依赖关系"
            }
        
        # 2. 查询学生这些前置知识点的历史理解度
        student_prereq_progress = self._get_student_prerequisite_progress(
            session, user_id, course_id, [kp["id"] for kp in prerequisite_kps]
        )
        
        # 3. 构建AI分析Prompt
        system_prompt = self._build_analysis_system_prompt()
        user_prompt = self._build_analysis_user_prompt(
            question=question,
            current_node=current_node,
            prerequisites=prerequisite_kps,
            student_progress=student_prereq_progress,
            history=conversation_history[-6:] if conversation_history else []
        )
        
        try:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]
            
            response = await llm_client.chat(
                messages, 
                temperature=0.3, 
                max_tokens=1500
            )
            
            result = self._parse_gap_analysis_result(response.content, prerequisite_kps)
            
            logger.info(
                f"[前置知识分析] has_gaps={result['has_gaps']}, "
                f"confident={result['overall_confidence']:.2f}, "
                f"weak_count={len(result['weak_prerequisites'])}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[前置知识分析失败] {str(e)}")
            return self._get_default_no_gap_result()

    def _get_prerequisite_knowledge_points(
        self, 
        session: Session, 
        node_id: int, 
        course_id: int
    ) -> List[Dict]:
        """
        获取当前节点的所有前置知识点

        基于ScriptNode的层级关系查找前置节点：
        1. 查找当前节点之前的同章节关键节点
        2. 查找父级章节的概览/概念类节点
        """
        results = []
        
        current_node = session.get(ScriptNode, node_id)
        if not current_node:
            return results
        
        script_id = current_node.script_id
        current_index = current_node.node_index
        
        prerequisite_nodes = session.exec(
            select(ScriptNode).where(
                ScriptNode.script_id == script_id,
                ScriptNode.node_index < current_index,
                ScriptNode.is_key_point == True
            ).order_by(
                ScriptNode.node_index.desc()
            ).limit(5)
        ).all()
        
        for node in prerequisite_nodes:
            if node.title and node.title.strip():
                results.append({
                    "id": node.id,
                    "title": node.title,
                    "description": (node.content[:200] if node.content else ""),
                    "difficulty": 3,
                    "relation_type": "prerequisite_direct",
                    "target_node_index": node.node_index
                })
        
        return results

    def _get_student_prerequisite_progress(
        self,
        session: Session,
        user_id: int,
        course_id: int,
        prereq_node_ids: List[int]
    ) -> Dict[int, Dict]:
        """
        查询学生对各前置知识点的学习进度和理解度
        """
        progress_map = {}
        
        learning_progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id
            )
        ).first()
        
        if not learning_progress:
            return progress_map
        
        node_progresses = session.exec(
            select(NodeProgress).where(
                NodeProgress.progress_id == learning_progress.id,
                NodeProgress.node_id.in_(prereq_node_ids)
            )
        ).all()
        
        for np in node_progresses:
            if np.node_id not in progress_map:
                progress_map[np.node_id] = {
                    "avg_score": np.understanding_score or 0,
                    "analysis_count": 1 if np.understanding_score else 0,
                    "last_level": np.understanding_level.value if np.understanding_level else "unknown",
                    "weak_keywords": []
                }
        
        analyses = session.exec(
            select(UnderstandingAnalysis).where(
                UnderstandingAnalysis.progress_id == learning_progress.id
            )
        ).all()
        
        for analysis in analyses:
            if analysis.keywords_weak:
                try:
                    weak_keywords = json.loads(analysis.keywords_weak)
                    for kw in weak_keywords:
                        for node_id in prereq_node_ids:
                            node = session.get(ScriptNode, node_id)
                            if node and kw.lower() in (node.title or "").lower():
                                if node_id not in progress_map:
                                    progress_map[node_id] = {
                                        "avg_score": analysis.understanding_score,
                                        "analysis_count": 1,
                                        "last_level": analysis.understanding_level.value,
                                        "weak_keywords": [kw]
                                    }
                                else:
                                    existing = progress_map[node_id]
                                    existing["avg_score"] = (
                                        existing["avg_score"] * existing["analysis_count"] + 
                                        analysis.understanding_score
                                    ) / (existing["analysis_count"] + 1)
                                    existing["analysis_count"] += 1
                                    existing["weak_keywords"].append(kw)
                except Exception:
                    pass
        
        return progress_map

    def _build_analysis_system_prompt(self) -> str:
        """构建系统提示词"""
        return """你是一位经验丰富的教育心理学专家和学科教学专家。请分析学生的提问内容，判断其是否存在前置知识缺陷。

## 分析目标
识别学生在学习当前知识点时，是否因为缺乏某些前置基础知识而导致理解困难。

## 判断维度

### 1. **问题特征识别**
- **概念混淆型**：学生将不同概念混为一谈（如混淆"极限"与"连续"）
- **基础缺失型**：问题涉及更基础的概念但学生未掌握（如问洛必达法则但不理解导数定义）
- **应用障碍型**：理解概念但无法应用，说明缺乏中间技能
- **符号误解型**：对数学符号、术语的理解存在偏差

### 2. **置信度评估**
- high (0.8-1.0): 明显存在前置知识缺陷，证据充分
- medium (0.6-0.79): 可能存在缺陷，建议关注
- low (0.4-0.59): 轻微迹象，可选复习
- very_low (0-0.39): 无明显缺陷

### 3. **紧急程度**
- **high**: 不复习会严重影响当前学习（如不理解极限就无法学洛必达法则）
- **medium**: 复习有助于更好理解，但不复习也能继续
- **low**: 锦上添花，非必需

## 输出格式
请严格按照以下JSON格式返回：

```json
{
    "has_gaps": true/false,
    "overall_confidence": 0.85,
    "weak_prerequisites": [
        {
            "prerequisite_id": 5,
            "matched_title": "函数极限",
            "reason": "学生问题显示其未掌握极限的ε-δ定义，这是理解洛必达法则的基础",
            "confidence": 0.9,
            "urgency_level": "high",
            "evidence_from_question": ["学生提到'不知道怎么求极限'", '混淆了极限与代入']
        }
    ],
    "suggested_action": "jump_to_review/continue/suggest_review",
    "analysis_summary": "综合判断..."
}
```

## 判断原则
1. **保守原则**：宁可漏判也不要误判，避免频繁打断学生学习
2. **证据导向**：必须从问题中找到具体证据，不能凭空猜测
3. **层次化**：优先推荐最基础的前置知识，而非高级拓展内容
4. **个性化**：结合学生的历史学习数据（如有）"""

    def _build_analysis_user_prompt(
        self,
        question: str,
        current_node: ScriptNode,
        prerequisites: List[Dict],
        student_progress: Dict[int, Dict],
        history: List[Dict]
    ) -> str:
        """构建用户提示词"""
        
        prereq_info = "\n".join([
            f"- ID:{p['id']} | {p['title']} | 难度:{p.get('difficulty', 3)}"
            for p in prerequisites
        ])
        
        progress_info = "无历史学习记录"
        if student_progress:
            progress_lines = []
            for kp_id, prog in student_progress.items():
                progress_lines.append(
                    f"- 知识点{kp_id}: 平均理解度{prog['avg_score']:.1%}, "
                    f"薄弱点: {', '.join(prog.get('weak_keywords', [])[:3])}"
                )
            progress_info = "\n".join(progress_lines) if progress_lines else "无明确薄弱点"
        
        history_text = "无历史对话"
        if history:
            formatted = []
            for msg in history[:6]:
                role = "学生" if msg.get("role") == "user" else "AI助教"
                content = msg.get("content", "")[:150]
                formatted.append(f"{role}: {content}")
            history_text = "\n".join(formatted)
        
        return f"""请分析以下学生的学习情况：

## 当前学习内容
**节点**: {current_node.title}
**类型**: {current_node.node_type}
**内容摘要**: {current_node.content[:500] if current_node.content else ''}

## 该知识点的前置要求
{prereq_info}

## 学生的历史学习情况（相关前置知识点）
{progress_info}

## 学生当前的提问
"{question}"

## 近期对话历史
{history_text}

请判断：
1. 学生的问题是否暴露了前置知识的缺陷？
2. 如果有，最可能是哪些前置知识点？
3. 缺陷的严重程度如何？是否需要立即跳转复习？

请给出详细的分析结果。"""

    def _parse_gap_analysis_result(self, content: str, prerequisites: List[Dict]) -> Dict:
        """解析AI返回的分析结果"""
        try:
            import re
            
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result = json.loads(json_match.group())
                
                # 验证并补充默认值
                result.setdefault("has_gaps", False)
                result.setdefault("overall_confidence", 0.0)
                result.setdefault("weak_prerequisites", [])
                result.setdefault("suggested_action", "continue")
                result.setdefault("analysis_summary", "")
                
                # 补充每个前置知识点的默认字段
                for wp in result.get("weak_prerequisites", []):
                    wp.setdefault("confidence", 0.5)
                    wp.setdefault("urgency_level", "medium")
                    wp.setdefault("target_node_index", -1)  # -1表示待后续匹配
                    wp.setdefault("evidence_from_question", [])
                
                return result
                
        except Exception as e:
            logger.error(f"[解析前置知识分析结果失败] {e}, 原始内容: {content[:200]}")
        
        return self._get_default_no_gap_result()

    def _get_default_no_gap_result(self) -> Dict:
        """返回默认的无缺陷结果"""
        return {
            "has_gaps": False,
            "overall_confidence": 0.0,
            "weak_prerequisites": [],
            "suggested_action": "continue",
            "analysis_summary": "未能完成分析，默认继续学习"
        }


class JumpHistoryManager:
    """
    跳转历史管理器
    管理多层跳转栈、返回原位置、学习路径追踪
    """
    
    def create_jump_record(
        self,
        session: Session,
        user_id: int,
        course_id: int,
        from_node_id: int,
        from_node_title: str,
        from_node_index: int,
        to_node_id: int,
        to_node_title: str,
        to_node_index: int,
        trigger_type: str,
        trigger_question: str,
        analysis_result: Dict,
        prerequisite_ids: List[int],
        prerequisite_titles: List[str],
        gap_description: str,
        confidence_score: float,
        urgency_level: str,
        parent_jump_id: Optional[int] = None,
    ) -> LearningJumpHistory:
        """
        创建一条跳转记录
        
        Args:
            ... (参数见字段定义)
            
        Returns:
            LearningJumpHistory: 新创建的跳转记录
        """
        
        # 计算跳转深度
        jump_depth = 1
        if parent_jump_id:
            parent_jump = session.get(LearningJumpHistory, parent_jump_id)
            if parent_jump:
                jump_depth = parent_jump.jump_depth + 1
        
        jump_record = LearningJumpHistory(
            user_id=user_id,
            course_id=course_id,
            session_id=str(uuid.uuid4())[:8],  # 简化的session ID
            from_node_id=from_node_id,
            from_node_title=from_node_title,
            from_node_index=from_node_index,
            to_node_id=to_node_id,
            to_node_title=to_node_title,
            to_node_index=to_node_index,
            trigger_type=trigger_type,
            trigger_question=trigger_question,
            analysis_result=json.dumps(analysis_result, ensure_ascii=False) if analysis_result else None,
            prerequisite_ids=",".join(map(str, prerequisite_ids)),
            prerequisite_titles=",".join(prerequisite_titles),
            gap_description=gap_description,
            confidence_score=confidence_score,
            urgency_level=urgency_level,
            parent_jump_id=parent_jump_id,
            jump_depth=jump_depth,
        )
        
        session.add(jump_record)
        session.commit()
        session.refresh(jump_record)
        
        logger.info(
            f"[跳转记录创建] 用户{user_id}: {from_node_title} -> {to_node_title}, "
            f"深度={jump_depth}, 触发原因={trigger_type}"
        )

        # ---- P1-09 G3D1: V2 learning-event shadow (after V1 commit) ----
        # Triggered AFTER the V1 jump record is committed. Maps the V1
        # jump into a P1-07 LearningEvent in an isolated shadow store.
        # trigger_learning_event_shadow catches ALL errors (business
        # fail-closed) so V1 is never affected; outer try/except is a
        # second safety net. Default flag v1_only = no-op.
        try:
            from app.platform.shadow.learning_shadow import trigger_learning_event_shadow
            trigger_learning_event_shadow(
                event_type="prerequisite_jump",
                student_id=user_id,
                course_id=course_id,
                sequence_number=jump_record.id,
                payload={
                    "from_node_id": from_node_id,
                    "to_node_id": to_node_id,
                    "trigger_type": trigger_type,
                    "urgency_level": urgency_level,
                    "confidence_score": confidence_score,
                },
            )
        except Exception as learning_shadow_err:  # noqa: BLE001
            logger.warning(f"[G3D1 learning shadow] suppressed (V1 unaffected): {learning_shadow_err}")
        
        return jump_record
    
    def get_jump_stack(
        self,
        session: Session,
        user_id: int,
        course_id: int,
        include_returned: bool = False
    ) -> List[LearningJumpHistory]:
        """
        获取用户的当前跳转栈（未返回的跳转记录）
        
        支持多层嵌套跳转的场景
        """
        query = select(LearningJumpHistory).where(
            LearningJumpHistory.user_id == user_id,
            LearningJumpHistory.course_id == course_id,
        )
        
        if not include_returned:
            query = query.where(LearningJumpHistory.is_returned == False)
        
        query = query.order_by(LearningJumpHistory.created_at.desc())
        
        return session.exec(query).all()
    
    def mark_as_returned(
        self,
        session: Session,
        jump_id: int,
        review_duration_seconds: int = 0
    ) -> bool:
        """
        标记跳转记录为已返回
        
        Returns:
            bool: 是否成功
        """
        jump_record = session.get(LearningJumpHistory, jump_id)
        if not jump_record:
            return False
        
        jump_record.is_returned = True
        jump_record.returned_at = utcnow_aware()
        jump_record.review_duration_seconds = review_duration_seconds
        jump_record.updated_at = utcnow_aware()
        
        session.add(jump_record)
        session.commit()
        
        logger.info(f"[跳转返回] 记录ID={jump_id}, 复习耗时={review_duration_seconds}秒")
        
        return True
    
    def mark_review_completed(
        self,
        session: Session,
        jump_id: int
    ) -> bool:
        """
        标记复习已完成
        
        Returns:
            bool: 是否成功
        """
        jump_record = session.get(LearningJumpHistory, jump_id)
        if not jump_record:
            return False
        
        jump_record.review_completed = True
        jump_record.updated_at = utcnow_aware()
        
        session.add(jump_record)
        session.commit()
        
        logger.info(f"[复习完成] 记录ID={jump_id}, 目标知识点={jump_record.to_node_title}")
        
        return True
    
    def get_learning_path_data(
        self,
        session: Session,
        user_id: int,
        course_id: int
    ) -> Dict:
        """
        获取学习路径可视化数据
        
        返回用于前端渲染路径图的数据结构
        """
        # 1. 获取课程的所有节点
        script = session.exec(
            select(CourseScript).where(CourseScript.course_id == course_id)
        ).first()
        
        if not script:
            return {"nodes": [], "edges": [], "currentPath": []}
        
        nodes_data = []
        script_nodes = session.exec(
            select(ScriptNode).where(
                ScriptNode.script_id == script.id
            ).order_by(ScriptNode.node_index)
        ).all()
        
        # 2. 构建节点数据（优化：批量查询避免N+1问题）
        lp = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id
            )
        ).first()
        
        node_progress_map = {}
        if lp:
            all_node_progresses = session.exec(
                select(NodeProgress).where(
                    NodeProgress.progress_id == lp.id
                )
            ).all()
            node_progress_map = {np.node_id: np for np in all_node_progresses}
        
        for node in script_nodes:
            node_status = "pending"
            understanding_score = None
            
            np = node_progress_map.get(node.id)
            if np:
                if np.is_completed:
                    node_status = "completed"
                elif np.understanding_score is not None:
                    node_status = "current"
                    understanding_score = np.understanding_score
            
            nodes_data.append({
                "id": node.id,
                "index": node.node_index,
                "title": node.title,
                "type": node.node_type,
                "status": node_status,
                "understandingScore": understanding_score,
            })
        
        # 3. 获取跳转历史（构建边）
        edges_data = []
        jumps = session.exec(
            select(LearningJumpHistory).where(
                LearningJumpHistory.user_id == user_id,
                LearningJumpHistory.course_id == course_id
            ).order_by(LearningJumpHistory.created_at)
        ).all()
        
        for jump in jumps:
            edges_data.append({
                "from": jump.from_node_id,
                "to": jump.to_node_id,
                "type": "prerequisite_jump",
                "label": f"跳转复习: {jump.gap_description[:30]}",
                "timestamp": jump.created_at.isoformat(),
                "isReturned": jump.is_returned,
                "triggerType": jump.trigger_type,
            })
        
        # 4. 构建当前学习路径（最近的跳转链）
        current_path = []
        unresolved_jumps = [j for j in jumps if not j.is_returned]
        if unresolved_jumps:
            latest_jump = unresolved_jumps[-1]
            current_path = self._build_jump_chain(session, latest_jump)
        
        return {
            "nodes": nodes_data,
            "edges": edges_data,
            "currentPath": current_path,
            "totalJumps": len(jumps),
            "completedJumps": sum(1 for j in jumps if j.is_returned and j.review_completed),
        }
    
    def _build_jump_chain(
        self,
        session: Session,
        jump: LearningJumpHistory
    ) -> List[Dict]:
        """
        递归构建跳转链（支持多层嵌套）
        """
        chain = [{
            "jumpId": jump.id,
            "fromNode": jump.from_node_title,
            "toNode": jump.to_node_title,
            "depth": jump.jump_depth,
            "timestamp": jump.created_at.isoformat(),
            "isReturned": jump.is_returned,
        }]
        
        # 如果有父级跳转，递归添加
        if jump.parent_jump_id:
            parent_jump = session.get(LearningJumpHistory, jump.parent_jump_id)
            if parent_jump and not parent_jump.is_returned:
                chain = self._build_jump_chain(session, parent_jump) + chain
        
        return chain


# 实例化全局服务
prerequisite_analyzer = PrerequisiteAnalyzer()
jump_history_manager = JumpHistoryManager()