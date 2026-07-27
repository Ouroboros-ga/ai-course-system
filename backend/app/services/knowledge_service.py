"""
知识库服务
多学科知识数据库的核心业务逻辑
支持知识点的增删改查、关系管理、批量导入、智能检索
"""

import json
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select, or_, and_

from app.core.time_utils import utcnow_aware
from app.models.knowledge_model import (
    KnowledgeBase,
    KnowledgePoint,
    KnowledgeRelation,
    KnowledgeImportLog,
    KnowledgeSearchHistory,
    SubjectType,
    KnowledgeLevel,
    KnowledgePointType,
)
from app.common.RAG import rag_pipeline
from app.platform.retrieval import RetrievalScope
from app.common.RAG.tree_rag import TreeNode, TreeBuildResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """知识库管理服务"""

    @staticmethod
    def create_knowledge_base(
        session: Session,
        name: str,
        subject: SubjectType,
        description: str = "",
        level: KnowledgeLevel = KnowledgeLevel.SENIOR,
        created_by: Optional[int] = None,
        config: Optional[dict] = None,
    ) -> KnowledgeBase:
        """
        创建新的知识库
        
        Args:
            session: 数据库会话
            name: 知识库名称
            subject: 学科类型
            description: 描述
            level: 难度等级
            created_by: 创建者ID
            config: 配置信息
            
        Returns:
            KnowledgeBase: 创建的知识库
        """
        kb = KnowledgeBase(
            name=name,
            subject=subject,
            description=description,
            level=level,
            created_by=created_by,
            config=config or {},
        )
        session.add(kb)
        session.commit()
        session.refresh(kb)
        
        logger.info(f"[KnowledgeBase] 创建知识库: {name} (ID={kb.id}, 学科={subject.value})")
        return kb

    @staticmethod
    def get_knowledge_base(
        session: Session,
        kb_id: int,
        include_points: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        获取知识库详情
        
        Args:
            session: 数据库会话
            kb_id: 知识库ID
            include_points: 是否包含知识点列表
            
        Returns:
            dict: 知识库信息
        """
        kb = session.get(KnowledgeBase, kb_id)
        if not kb:
            return None
        
        result = {
            "id": kb.id,
            "name": kb.name,
            "subject": kb.subject.value,
            "description": kb.description,
            "level": kb.level.value,
            "total_points": kb.total_points,
            "total_relations": kb.total_relations,
            "is_active": kb.is_active,
            "is_public": kb.is_public,
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
            "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
        }
        
        if include_points:
            points = session.exec(
                select(KnowledgePoint)
                .where(KnowledgePoint.kb_id == kb_id)
                .where(KnowledgePoint.is_active == True)
                .order_by(KnowledgePoint.created_at)
            ).all()
            
            result["points"] = [
                {
                    "id": p.id,
                    "point_id": p.point_id,
                    "title": p.title,
                    "point_type": p.point_type.value,
                    "difficulty": p.difficulty,
                    "importance": p.importance,
                    "view_count": p.view_count,
                }
                for p in points
            ]
        
        return result

    @staticmethod
    def list_knowledge_bases(
        session: Session,
        subject: Optional[SubjectType] = None,
        level: Optional[KnowledgeLevel] = None,
        is_public: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        列出知识库（分页）
        
        Args:
            session: 数据库会话
            subject: 学科过滤
            level: 难度过滤
            is_public: 公开状态过滤
            page: 页码
            page_size: 每页数量
            
        Returns:
            dict: 分页结果
        """
        conditions = [KnowledgeBase.is_active == True]
        
        if subject:
            conditions.append(KnowledgeBase.subject == subject)
        if level:
            conditions.append(KnowledgeBase.level == level)
        if is_public is not None:
            conditions.append(KnowledgeBase.is_public == is_public)
        
        statement = select(KnowledgeBase).where(and_(*conditions))
        
        total = len(session.exec(statement).all())
        
        statement = (
            statement
            .order_by(KnowledgeBase.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        
        kbs = session.exec(statement).all()
        
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": [
                {
                    "id": kb.id,
                    "name": kb.name,
                    "subject": kb.subject.value,
                    "description": kb.description,
                    "level": kb.level.value,
                    "total_points": kb.total_points,
                    "is_public": kb.is_public,
                    "created_at": kb.created_at.isoformat() if kb.created_at else None,
                }
                for kb in kbs
            ],
        }


class KnowledgePointService:
    """知识点管理服务"""

    @staticmethod
    def create_knowledge_point(
        session: Session,
        kb_id: int,
        title: str,
        content: str,
        point_type: KnowledgePointType = KnowledgePointType.CONCEPT,
        point_id: Optional[str] = None,
        parent_id: Optional[int] = None,
        difficulty: int = 3,
        importance: int = 3,
        keywords: str = "",
        tags: str = "",
        examples: Optional[List[dict]] = None,
        related_formulas: Optional[List[dict]] = None,
        prerequisites: str = "",
        source: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> KnowledgePoint:
        """
        创建知识点
        
        Args:
            session: 数据库会话
            kb_id: 知识库ID
            title: 标题
            content: 内容
            point_type: 知识点类型
            point_id: 唯一标识
            parent_id: 父知识点ID
            difficulty: 难度(1-5)
            importance: 重要程度(1-5)
            keywords: 关键词
            tags: 标签
            examples: 示例列表
            related_formulas: 相关公式
            prerequisites: 前置知识点
            source: 来源
            source_url: 来源URL
            
        Returns:
            KnowledgePoint: 创建的知识点
        """
        if not point_id:
            kb = session.get(KnowledgeBase, kb_id)
            subject_prefix = kb.subject.value.upper() if kb else "GEN"
            point_id = f"KP_{subject_prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{hash(title) % 10000:04d}"
        
        point = KnowledgePoint(
            kb_id=kb_id,
            point_id=point_id,
            title=title,
            content=content,
            point_type=point_type,
            parent_id=parent_id,
            difficulty=difficulty,
            importance=importance,
            keywords=keywords,
            tags=tags,
            examples=examples or [],
            related_formulas=related_formulas or [],
            prerequisites=prerequisites,
            source=source,
            source_url=source_url,
        )
        session.add(point)
        session.commit()
        session.refresh(point)
        
        kb = session.get(KnowledgeBase, kb_id)
        if kb:
            kb.total_points = (kb.total_points or 0) + 1
            session.commit()
        
        logger.info(f"[KnowledgePoint] 创建知识点: {title} (ID={point.id}, KB={kb_id})")
        return point

    @staticmethod
    def batch_create_knowledge_points(
        session: Session,
        kb_id: int,
        points_data: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        """
        批量创建知识点
        
        Args:
            session: 数据库会话
            kb_id: 知识库ID
            points_data: 知识点数据列表
            
        Returns:
            tuple: (成功数量, 失败数量)
        """
        success_count = 0
        fail_count = 0
        
        for data in points_data:
            try:
                KnowledgePointService.create_knowledge_point(
                    session=session,
                    kb_id=kb_id,
                    **data
                )
                success_count += 1
            except Exception as e:
                logger.error(f"[KnowledgePoint] 创建失败: {e}")
                fail_count += 1
        
        return success_count, fail_count

    @staticmethod
    def get_knowledge_point(
        session: Session,
        point_id: int,
        increment_view: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        获取知识点详情
        
        Args:
            session: 数据库会话
            point_id: 知识点ID
            increment_view: 是否增加查看次数
            
        Returns:
            dict: 知识点信息
        """
        point = session.get(KnowledgePoint, point_id)
        if not point:
            return None
        
        if increment_view:
            point.view_count = (point.view_count or 0) + 1
            session.commit()
        
        result = {
            "id": point.id,
            "kb_id": point.kb_id,
            "point_id": point.point_id,
            "title": point.title,
            "content": point.content,
            "point_type": point.point_type.value,
            "parent_id": point.parent_id,
            "difficulty": point.difficulty,
            "importance": point.importance,
            "keywords": point.keywords,
            "tags": point.tags,
            "examples": point.examples,
            "related_formulas": point.related_formulas,
            "prerequisites": point.prerequisites,
            "source": point.source,
            "source_url": point.source_url,
            "view_count": point.view_count,
            "reference_count": point.reference_count,
            "created_at": point.created_at.isoformat() if point.created_at else None,
            "updated_at": point.updated_at.isoformat() if point.updated_at else None,
        }
        
        if point.parent_id:
            parent = session.get(KnowledgePoint, point.parent_id)
            if parent:
                result["parent_title"] = parent.title
        
        children = session.exec(
            select(KnowledgePoint)
            .where(KnowledgePoint.parent_id == point_id)
            .where(KnowledgePoint.is_active == True)
        ).all()
        
        if children:
            result["children"] = [
                {"id": c.id, "title": c.title, "point_type": c.point_type.value}
                for c in children
            ]
        
        return result

    @staticmethod
    def update_knowledge_point(
        session: Session,
        point_id: int,
        **kwargs
    ) -> Optional[KnowledgePoint]:
        """
        更新知识点
        
        Args:
            session: 数据库会话
            point_id: 知识点ID
            **kwargs: 要更新的字段
            
        Returns:
            KnowledgePoint: 更新后的知识点
        """
        point = session.get(KnowledgePoint, point_id)
        if not point:
            return None
        
        for key, value in kwargs.items():
            if hasattr(point, key) and value is not None:
                setattr(point, key, value)
        
        point.updated_at = utcnow_aware()
        session.commit()
        session.refresh(point)
        
        logger.info(f"[KnowledgePoint] 更新知识点: {point.title} (ID={point_id})")
        return point

    @staticmethod
    def delete_knowledge_point(
        session: Session,
        point_id: int,
        soft_delete: bool = True,
    ) -> bool:
        """
        删除知识点
        
        Args:
            session: 数据库会话
            point_id: 知识点ID
            soft_delete: 是否软删除
            
        Returns:
            bool: 是否成功
        """
        point = session.get(KnowledgePoint, point_id)
        if not point:
            return False
        
        if soft_delete:
            point.is_active = False
            session.commit()
        else:
            session.delete(point)
            session.commit()
        
        kb = session.get(KnowledgeBase, point.kb_id)
        if kb and kb.total_points > 0:
            kb.total_points -= 1
            session.commit()
        
        logger.info(f"[KnowledgePoint] 删除知识点: {point.title} (ID={point_id})")
        return True


class KnowledgeSearchService:
    """知识库检索服务"""

    @staticmethod
    def search(
        session: Session,
        query: str,
        kb_ids: Optional[List[int]] = None,
        subject: Optional[SubjectType] = None,
        point_type: Optional[KnowledgePointType] = None,
        difficulty_range: Optional[Tuple[int, int]] = None,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        搜索知识点
        
        Args:
            session: 数据库会话
            query: 搜索关键词
            kb_ids: 知识库ID列表
            subject: 学科过滤
            point_type: 知识点类型过滤
            difficulty_range: 难度范围 (min, max)
            page: 页码
            page_size: 每页数量
            user_id: 用户ID（用于记录搜索历史）
            
        Returns:
            dict: 搜索结果
        """
        conditions = [KnowledgePoint.is_active == True]
        
        if kb_ids:
            conditions.append(KnowledgePoint.kb_id.in_(kb_ids))
        
        if subject:
            kb_ids_with_subject = session.exec(
                select(KnowledgeBase.id).where(KnowledgeBase.subject == subject)
            ).all()
            if kb_ids_with_subject:
                conditions.append(KnowledgePoint.kb_id.in_(kb_ids_with_subject))
        
        if point_type:
            conditions.append(KnowledgePoint.point_type == point_type)
        
        if difficulty_range:
            conditions.append(KnowledgePoint.difficulty >= difficulty_range[0])
            conditions.append(KnowledgePoint.difficulty <= difficulty_range[1])
        
        search_conditions = []
        for word in query.split():
            search_conditions.append(KnowledgePoint.title.contains(word))
            search_conditions.append(KnowledgePoint.content.contains(word))
            search_conditions.append(KnowledgePoint.keywords.contains(word))
        
        conditions.append(or_(*search_conditions))
        
        statement = select(KnowledgePoint).where(and_(*conditions))
        
        total = len(session.exec(statement).all())
        
        statement = (
            statement
            .order_by(KnowledgePoint.importance.desc(), KnowledgePoint.view_count.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        
        points = session.exec(statement).all()
        
        if user_id:
            for point in points[:3]:
                history = KnowledgeSearchHistory(
                    user_id=user_id,
                    kb_id=point.kb_id,
                    query=query,
                    result_count=total,
                    clicked_point_id=point.id,
                )
                session.add(history)
            session.commit()
        
        return {
            "query": query,
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": [
                {
                    "id": p.id,
                    "kb_id": p.kb_id,
                    "point_id": p.point_id,
                    "title": p.title,
                    "content_preview": p.content[:200] + "..." if len(p.content) > 200 else p.content,
                    "point_type": p.point_type.value,
                    "difficulty": p.difficulty,
                    "importance": p.importance,
                    "keywords": p.keywords,
                    "view_count": p.view_count,
                }
                for p in points
            ],
        }

    @staticmethod
    def get_context_for_question(
        session: Session,
        question: str,
        kb_ids: Optional[List[int]] = None,
        subject: Optional[SubjectType] = None,
        top_k: int = 5,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        为问答获取上下文
        
        Args:
            session: 数据库会话
            question: 用户问题
            kb_ids: 知识库ID列表
            subject: 学科过滤
            top_k: 返回数量
            
        Returns:
            tuple: (上下文文本, 知识点列表)
        """
        result = KnowledgeSearchService.search(
            session=session,
            query=question,
            kb_ids=kb_ids,
            subject=subject,
            page=1,
            page_size=top_k,
        )
        
        context_parts = []
        knowledge_points = []
        
        for i, point in enumerate(result["results"]):
            full_point = session.get(KnowledgePoint, point["id"])
            if full_point:
                context_parts.append(
                    f"【知识点{i+1}: {full_point.title}】\n"
                    f"类型: {full_point.point_type.value}\n"
                    f"难度: {full_point.difficulty}/5\n"
                    f"内容: {full_point.content}\n"
                )
                
                knowledge_points.append({
                    "id": full_point.point_id,
                    "title": full_point.title,
                    "content": full_point.content[:500],
                    "type": full_point.point_type.value,
                    "difficulty": full_point.difficulty,
                })
        
        context = "\n---\n".join(context_parts) if context_parts else ""
        
        return context, knowledge_points


class KnowledgeImportService:
    """知识库导入服务"""

    @staticmethod
    async def import_from_document(
        session: Session,
        kb_id: int,
        markdown_content: str,
        doc_name: str,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        从文档导入知识点
        
        Args:
            session: 数据库会话
            kb_id: 知识库ID
            markdown_content: Markdown内容
            doc_name: 文档名称
            created_by: 创建者ID
            
        Returns:
            dict: 导入结果
        """
        import_log = KnowledgeImportLog(
            kb_id=kb_id,
            file_name=doc_name,
            status="processing",
            created_by=created_by,
        )
        session.add(import_log)
        session.commit()
        session.refresh(import_log)
        
        try:
            # 知识库导入使用显式 knowledge_base 作用域，与课程作用域隔离，
            # 避免 kb_id 与 course_id 同值时在注册表中冲突。
            rag_result = rag_pipeline.process_document(
                markdown_text=markdown_content,
                doc_name=doc_name,
                doc_id=str(kb_id),
                scope=RetrievalScope.knowledge_base(kb_id),
            )
            
            knowledge_points = KnowledgeImportService._extract_points_from_tree(
                rag_result.tree_result.tree,
                session,
                kb_id,
                doc_name,
            )
            
            import_log.total_points = len(knowledge_points)
            import_log.success_count = len(knowledge_points)
            import_log.status = "completed"
            import_log.completed_at = utcnow_aware()
            session.commit()
            
            logger.info(f"[KnowledgeImport] 从文档导入完成: {doc_name}, {len(knowledge_points)}个知识点")
            
            return {
                "success": True,
                "total_points": len(knowledge_points),
                "knowledge_points": [
                    {"id": p.id, "title": p.title}
                    for p in knowledge_points
                ],
                "rag_info": {
                    "formula_count": rag_result.formula_result.formula_count,
                    "table_count": len(rag_result.table_results),
                    "tree_nodes": rag_result.tree_result.total_nodes,
                },
            }
            
        except Exception as e:
            import_log.status = "failed"
            import_log.error_message = str(e)
            session.commit()
            
            logger.error(f"[KnowledgeImport] 导入失败: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @staticmethod
    def _extract_points_from_tree(
        node: Optional[TreeNode],
        session: Session,
        kb_id: int,
        source: str,
        parent_id: Optional[int] = None,
        points: Optional[List[KnowledgePoint]] = None,
    ) -> List[KnowledgePoint]:
        """
        从知识树提取知识点
        """
        if points is None:
            points = []
        
        if node is None:
            return points
        
        if node.content and len(node.content.strip()) > 30:
            point_type = KnowledgeImportService._determine_point_type(node)
            
            point = KnowledgePointService.create_knowledge_point(
                session=session,
                kb_id=kb_id,
                title=node.title or f"知识点_{node.node_id}",
                content=node.content,
                point_type=point_type,
                parent_id=parent_id,
                source=source,
                difficulty=KnowledgeImportService._estimate_difficulty(node),
                importance=5 if node.metadata.get("is_key_point") else 3,
            )
            points.append(point)
            
            for child in node.children:
                KnowledgeImportService._extract_points_from_tree(
                    child, session, kb_id, source, point.id, points
                )
        else:
            for child in node.children:
                KnowledgeImportService._extract_points_from_tree(
                    child, session, kb_id, source, parent_id, points
                )
        
        return points

    @staticmethod
    def _determine_point_type(node: TreeNode) -> KnowledgePointType:
        """根据节点内容判断知识点类型"""
        content = node.content.lower() if node.content else ""
        title = node.title.lower() if node.title else ""
        
        if "公式" in title or "公式" in content or "$$" in content:
            return KnowledgePointType.FORMULA
        elif "定理" in title or "定理" in content:
            return KnowledgePointType.THEOREM
        elif "例" in title or "例题" in content:
            return KnowledgePointType.EXAMPLE
        elif "练习" in title or "习题" in content:
            return KnowledgePointType.EXERCISE
        elif "总结" in title or "小结" in content:
            return KnowledgePointType.SUMMARY
        else:
            return KnowledgePointType.CONCEPT

    @staticmethod
    def _estimate_difficulty(node: TreeNode) -> int:
        """估算知识点难度"""
        level = node.level
        content_len = len(node.content) if node.content else 0
        
        if level <= 1:
            base_diff = 2
        elif level <= 2:
            base_diff = 3
        elif level <= 3:
            base_diff = 4
        else:
            base_diff = 3
        
        if content_len > 1000:
            base_diff = min(5, base_diff + 1)
        
        return base_diff

    @staticmethod
    async def import_from_json(
        session: Session,
        kb_id: int,
        json_data: List[Dict[str, Any]],
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        从JSON数据导入知识点
        
        Args:
            session: 数据库会话
            kb_id: 知识库ID
            json_data: JSON数据列表
            created_by: 创建者ID
            
        Returns:
            dict: 导入结果
        """
        import_log = KnowledgeImportLog(
            kb_id=kb_id,
            file_name="json_import",
            status="processing",
            created_by=created_by,
        )
        session.add(import_log)
        session.commit()
        session.refresh(import_log)
        
        try:
            success_count, fail_count = KnowledgePointService.batch_create_knowledge_points(
                session=session,
                kb_id=kb_id,
                points_data=json_data,
            )
            
            import_log.total_points = len(json_data)
            import_log.success_count = success_count
            import_log.fail_count = fail_count
            import_log.status = "completed"
            import_log.completed_at = utcnow_aware()
            session.commit()
            
            return {
                "success": True,
                "total": len(json_data),
                "success_count": success_count,
                "fail_count": fail_count,
            }
            
        except Exception as e:
            import_log.status = "failed"
            import_log.error_message = str(e)
            session.commit()
            
            return {
                "success": False,
                "error": str(e),
            }


class KnowledgeRelationService:
    """知识点关系服务"""

    @staticmethod
    def create_relation(
        session: Session,
        source_id: int,
        target_id: int,
        relation_type: str = "related",
        weight: float = 1.0,
        description: str = "",
    ) -> KnowledgeRelation:
        """
        创建知识点关系
        
        Args:
            session: 数据库会话
            source_id: 源知识点ID
            target_id: 目标知识点ID
            relation_type: 关系类型
            weight: 权重
            description: 描述
            
        Returns:
            KnowledgeRelation: 创建的关系
        """
        relation = KnowledgeRelation(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=weight,
            description=description,
        )
        session.add(relation)
        session.commit()
        session.refresh(relation)
        
        source = session.get(KnowledgePoint, source_id)
        if source:
            source.reference_count = (source.reference_count or 0) + 1
            session.commit()
        
        kb = session.get(KnowledgeBase, source.kb_id if source else None)
        if kb:
            kb.total_relations = (kb.total_relations or 0) + 1
            session.commit()
        
        logger.info(f"[KnowledgeRelation] 创建关系: {source_id} -> {target_id} ({relation_type})")
        return relation

    @staticmethod
    def get_related_points(
        session: Session,
        point_id: int,
        relation_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取相关知识点
        
        Args:
            session: 数据库会话
            point_id: 知识点ID
            relation_type: 关系类型过滤
            
        Returns:
            list: 相关知识点列表
        """
        conditions = [
            or_(
                KnowledgeRelation.source_id == point_id,
                KnowledgeRelation.target_id == point_id,
            )
        ]
        
        if relation_type:
            conditions.append(KnowledgeRelation.relation_type == relation_type)
        
        relations = session.exec(
            select(KnowledgeRelation).where(and_(*conditions))
        ).all()
        
        related_points = []
        for rel in relations:
            related_id = rel.target_id if rel.source_id == point_id else rel.source_id
            point = session.get(KnowledgePoint, related_id)
            if point and point.is_active:
                related_points.append({
                    "id": point.id,
                    "title": point.title,
                    "point_type": point.point_type.value,
                    "relation_type": rel.relation_type,
                    "weight": rel.weight,
                })
        
        return related_points


knowledge_base_service = KnowledgeBaseService()
knowledge_point_service = KnowledgePointService()
knowledge_search_service = KnowledgeSearchService()
knowledge_import_service = KnowledgeImportService()
knowledge_relation_service = KnowledgeRelationService()
