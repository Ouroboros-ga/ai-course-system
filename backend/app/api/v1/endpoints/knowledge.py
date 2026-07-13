"""
知识库管理API接口
提供多学科知识库的创建、管理、检索功能
"""

from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException, Body, UploadFile, File
from sqlmodel import Session

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.knowledge_model import (
    SubjectType,
    KnowledgeLevel,
    KnowledgePointType,
    KnowledgeBase,
    KnowledgePoint,
    KnowledgeRelation,
)
from app.services.knowledge_service import (
    KnowledgeBaseService,
    KnowledgePointService,
    KnowledgeSearchService,
    KnowledgeImportService,
    KnowledgeRelationService,
)

router = APIRouter(tags=["知识库管理"])


# ==================== 知识库管理接口 ====================

@router.post("/bases", response_model=UnifiedResponse)
async def create_knowledge_base(
    name: str = Body(..., description="知识库名称"),
    subject: SubjectType = Body(..., description="学科类型"),
    description: Optional[str] = Body(None, description="知识库描述"),
    level: KnowledgeLevel = Body(KnowledgeLevel.SENIOR, description="适用难度等级"),
    is_public: bool = Body(False, description="是否公开"),
    config: dict = Body({}, description="知识库配置"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    创建知识库
    
    需要用户登录认证
    
    参数:
    - name: 知识库名称
    - subject: 学科类型 (math/physics/chemistry/...)
    - description: 知识库描述
    - level: 适用难度等级
    - is_public: 是否公开
    - config: 知识库配置
    """
    try:
        user_id = int(current_user["user_id"])
        
        kb = KnowledgeBaseService.create_knowledge_base(
            session=session,
            name=name,
            subject=subject,
            description=description,
            level=level,
            created_by=user_id,
            is_public=is_public,
            config=config,
        )
        
        return unified_response(
            code=200,
            message="知识库创建成功",
            data={
                "id": kb.id,
                "name": kb.name,
                "subject": kb.subject.value,
                "description": kb.description,
                "level": kb.level.value,
                "is_public": kb.is_public,
                "created_at": kb.created_at.isoformat() if kb.created_at else None,
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"创建知识库失败: {str(e)}",
            data=None
        )


@router.get("/bases", response_model=UnifiedResponse)
async def list_knowledge_bases(
    subject: Optional[SubjectType] = Query(None, description="学科过滤"),
    level: Optional[KnowledgeLevel] = Query(None, description="难度过滤"),
    is_public: Optional[bool] = Query(None, description="公开状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(20, ge=1, le=100, description="每页数量"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取知识库列表（分页）
    
    支持按学科、难度、公开状态过滤
    """
    try:
        result = KnowledgeBaseService.list_knowledge_bases(
            session=session,
            subject=subject,
            level=level,
            is_public=is_public,
            page=page,
            page_size=pageSize,
        )
        
        return unified_response(
            code=200,
            message="获取成功",
            data=result
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取知识库列表失败: {str(e)}",
            data=None
        )


@router.get("/bases/{kb_id}", response_model=UnifiedResponse)
async def get_knowledge_base(
    kb_id: int,
    includePoints: bool = Query(False, description="是否包含知识点列表"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取知识库详情
    
    参数:
    - kb_id: 知识库ID
    - includePoints: 是否包含知识点列表
    """
    try:
        result = KnowledgeBaseService.get_knowledge_base(
            session=session,
            kb_id=kb_id,
            include_points=includePoints,
        )
        
        if not result:
            return unified_response(
                code=404,
                message="知识库不存在",
                data=None
            )
        
        return unified_response(
            code=200,
            message="获取成功",
            data=result
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取知识库详情失败: {str(e)}",
            data=None
        )


@router.delete("/bases/{kb_id}", response_model=UnifiedResponse)
async def delete_knowledge_base(
    kb_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    删除知识库（软删除）
    """
    try:
        kb = session.get(KnowledgeBase, kb_id)
        if not kb:
            return unified_response(
                code=404,
                message="知识库不存在",
                data=None
            )
        
        kb.is_active = False
        session.commit()

        # 软删除成功后，清理该知识库的进程内 RAG 检索作用域（best-effort）。
        # 知识库导入时按 knowledge_base scope 建树用于知识点抽取；
        # 删除后清理避免残留内存索引被未来 KB 检索误读。
        try:
            from app.platform.retrieval import RetrievalScope, retrieval_gateway
            retrieval_gateway.clear_scope(RetrievalScope.knowledge_base(kb_id))
        except Exception as clear_err:
            print(f"[删除知识库] 清理知识库 RAG 索引失败（可忽略）: {clear_err}")

        return unified_response(
            code=200,
            message="删除成功",
            data=None
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"删除知识库失败: {str(e)}",
            data=None
        )


# ==================== 知识点管理接口 ====================

@router.post("/points", response_model=UnifiedResponse)
async def create_knowledge_point(
    kb_id: int = Body(..., description="知识库ID"),
    title: str = Body(..., description="知识点标题"),
    content: str = Body(..., description="知识点内容"),
    point_type: KnowledgePointType = Body(KnowledgePointType.CONCEPT, description="知识点类型"),
    parent_id: Optional[int] = Body(None, description="父知识点ID"),
    difficulty: int = Body(3, ge=1, le=5, description="难度等级"),
    importance: int = Body(3, ge=1, le=5, description="重要程度"),
    keywords: str = Body("", description="关键词"),
    tags: str = Body("", description="标签"),
    examples: Optional[List[dict]] = Body(None, description="示例列表"),
    related_formulas: Optional[List[dict]] = Body(None, description="相关公式"),
    prerequisites: str = Body("", description="前置知识点"),
    source: Optional[str] = Body(None, description="来源"),
    source_url: Optional[str] = Body(None, description="来源URL"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    创建知识点
    
    需要用户登录认证
    """
    try:
        point = KnowledgePointService.create_knowledge_point(
            session=session,
            kb_id=kb_id,
            title=title,
            content=content,
            point_type=point_type,
            parent_id=parent_id,
            difficulty=difficulty,
            importance=importance,
            keywords=keywords,
            tags=tags,
            examples=examples,
            related_formulas=related_formulas,
            prerequisites=prerequisites,
            source=source,
            source_url=source_url,
        )
        
        return unified_response(
            code=200,
            message="知识点创建成功",
            data={
                "id": point.id,
                "point_id": point.point_id,
                "title": point.title,
                "point_type": point.point_type.value,
                "difficulty": point.difficulty,
                "importance": point.importance,
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"创建知识点失败: {str(e)}",
            data=None
        )


@router.post("/points/batch", response_model=UnifiedResponse)
async def batch_create_knowledge_points(
    kb_id: int = Body(..., description="知识库ID"),
    points: List[dict] = Body(..., description="知识点列表"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    批量创建知识点
    
    参数:
    - kb_id: 知识库ID
    - points: 知识点列表，每个元素包含 title, content, point_type 等字段
    """
    try:
        success_count, fail_count = KnowledgePointService.batch_create_knowledge_points(
            session=session,
            kb_id=kb_id,
            points_data=points,
        )
        
        return unified_response(
            code=200,
            message=f"批量创建完成: 成功{success_count}个, 失败{fail_count}个",
            data={
                "total": len(points),
                "success_count": success_count,
                "fail_count": fail_count,
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"批量创建知识点失败: {str(e)}",
            data=None
        )


@router.get("/points/{point_id}", response_model=UnifiedResponse)
async def get_knowledge_point(
    point_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取知识点详情
    """
    try:
        point = session.get(KnowledgePoint, point_id)
        if not point:
            return unified_response(
                code=404,
                message="知识点不存在",
                data=None
            )
        
        point.view_count = (point.view_count or 0) + 1
        session.commit()
        
        return unified_response(
            code=200,
            message="获取成功",
            data={
                "id": point.id,
                "point_id": point.point_id,
                "kb_id": point.kb_id,
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
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取知识点详情失败: {str(e)}",
            data=None
        )


# ==================== 知识检索接口 ====================

@router.get("/search", response_model=UnifiedResponse)
async def search_knowledge(
    q: str = Query(..., description="搜索关键词"),
    kb_ids: Optional[str] = Query(None, description="知识库ID列表，逗号分隔"),
    subject: Optional[SubjectType] = Query(None, description="学科过滤"),
    point_type: Optional[KnowledgePointType] = Query(None, description="知识点类型过滤"),
    difficulty_min: Optional[int] = Query(None, ge=1, le=5, description="最小难度"),
    difficulty_max: Optional[int] = Query(None, ge=1, le=5, description="最大难度"),
    page: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(20, ge=1, le=100, description="每页数量"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    搜索知识点
    
    支持多条件组合搜索
    """
    try:
        user_id = int(current_user["user_id"])
        
        kb_id_list = None
        if kb_ids:
            kb_id_list = [int(x.strip()) for x in kb_ids.split(",") if x.strip().isdigit()]
        
        difficulty_range = None
        if difficulty_min is not None and difficulty_max is not None:
            difficulty_range = (difficulty_min, difficulty_max)
        
        result = KnowledgeSearchService.search(
            session=session,
            query=q,
            kb_ids=kb_id_list,
            subject=subject,
            point_type=point_type,
            difficulty_range=difficulty_range,
            page=page,
            page_size=pageSize,
            user_id=user_id,
        )
        
        return unified_response(
            code=200,
            message="搜索完成",
            data=result
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"搜索失败: {str(e)}",
            data=None
        )


@router.post("/search/context", response_model=UnifiedResponse)
async def get_context_for_question(
    question: str = Body(..., description="用户问题"),
    kb_ids: Optional[List[int]] = Body(None, description="知识库ID列表"),
    subject: Optional[SubjectType] = Body(None, description="学科过滤"),
    top_k: int = Body(5, ge=1, le=20, description="返回知识点数量"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    为问答获取上下文
    
    根据用户问题检索相关知识点，返回上下文文本供LLM使用
    """
    try:
        context_text, knowledge_points = await KnowledgeSearchService.get_context_for_question(
            session=session,
            question=question,
            kb_ids=kb_ids,
            subject=subject,
            top_k=top_k,
        )
        
        return unified_response(
            code=200,
            message="获取上下文成功",
            data={
                "context": context_text,
                "knowledge_points": knowledge_points,
                "point_count": len(knowledge_points),
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取上下文失败: {str(e)}",
            data=None
        )


# ==================== 知识导入接口 ====================

@router.post("/import/document", response_model=UnifiedResponse)
async def import_from_document(
    kb_id: int = Body(..., description="知识库ID"),
    course_id: int = Body(..., description="课程ID（已上传的文档）"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    从已上传的文档导入知识点
    
    会自动解析文档结构，提取知识点
    """
    try:
        from app.models.course_model import DoclingDocument
        from sqlmodel import select
        
        docling_doc = session.exec(
            select(DoclingDocument).where(DoclingDocument.course_id == course_id)
        ).first()
        
        if not docling_doc:
            return unified_response(
                code=404,
                message="文档不存在",
                data=None
            )
        
        if not docling_doc.raw_json or "raw_content" not in docling_doc.raw_json:
            return unified_response(
                code=400,
                message="文档内容为空",
                data=None
            )
        
        markdown_content = docling_doc.raw_json.get("raw_content", "")
        
        result = await KnowledgeImportService.import_from_document(
            session=session,
            kb_id=kb_id,
            markdown_content=markdown_content,
            doc_name=docling_doc.doc_name or "未命名文档",
        )
        
        return unified_response(
            code=200,
            message="导入完成",
            data=result
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"导入失败: {str(e)}",
            data=None
        )


@router.post("/import/json", response_model=UnifiedResponse)
async def import_from_json(
    kb_id: int = Body(..., description="知识库ID"),
    data: List[dict] = Body(..., description="知识点JSON数据"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    从JSON数据导入知识点
    
    JSON格式示例:
    [
        {
            "title": "知识点标题",
            "content": "知识点内容",
            "point_type": "concept",
            "difficulty": 3,
            "importance": 3,
            "keywords": "关键词1,关键词2",
            "tags": "标签1,标签2"
        }
    ]
    """
    try:
        user_id = int(current_user["user_id"])
        
        result = await KnowledgeImportService.import_from_json(
            session=session,
            kb_id=kb_id,
            json_data=data,
            created_by=user_id,
        )
        
        return unified_response(
            code=200,
            message="导入完成",
            data=result
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"导入失败: {str(e)}",
            data=None
        )


# ==================== 知识关系接口 ====================

@router.post("/relations", response_model=UnifiedResponse)
async def create_knowledge_relation(
    source_id: int = Body(..., description="源知识点ID"),
    target_id: int = Body(..., description="目标知识点ID"),
    relation_type: str = Body("related", description="关系类型: prerequisite/related/extends/applies_to"),
    weight: float = Body(1.0, description="关系权重"),
    description: str = Body("", description="关系描述"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    创建知识点关系
    
    关系类型:
    - prerequisite: 前置关系（学习目标知识点前需要先学习源知识点）
    - related: 相关关系
    - extends: 扩展关系
    - applies_to: 应用关系
    """
    try:
        relation = KnowledgeRelationService.create_relation(
            session=session,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=weight,
            description=description,
        )
        
        return unified_response(
            code=200,
            message="关系创建成功",
            data={
                "id": relation.id,
                "source_id": relation.source_id,
                "target_id": relation.target_id,
                "relation_type": relation.relation_type,
                "weight": relation.weight,
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"创建关系失败: {str(e)}",
            data=None
        )


@router.get("/points/{point_id}/related", response_model=UnifiedResponse)
async def get_related_points(
    point_id: int,
    relation_type: Optional[str] = Query(None, description="关系类型过滤"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取相关知识点的点
    """
    try:
        result = KnowledgeRelationService.get_related_points(
            session=session,
            point_id=point_id,
            relation_type=relation_type,
        )
        
        return unified_response(
            code=200,
            message="获取成功",
            data=result
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取相关知识点失败: {str(e)}",
            data=None
        )


# ==================== 统计接口 ====================

@router.get("/stats", response_model=UnifiedResponse)
async def get_knowledge_stats(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取知识库统计信息
    """
    try:
        from sqlmodel import select, func
        
        total_kbs = session.exec(
            select(func.count(KnowledgeBase.id)).where(KnowledgeBase.is_active == True)
        ).one()
        
        total_points = session.exec(
            select(func.count(KnowledgePoint.id)).where(KnowledgePoint.is_active == True)
        ).one()
        
        total_relations = session.exec(
            select(func.count(KnowledgeRelation.id))
        ).one()
        
        subject_stats = session.exec(
            select(KnowledgeBase.subject, func.count(KnowledgeBase.id))
            .where(KnowledgeBase.is_active == True)
            .group_by(KnowledgeBase.subject)
        ).all()
        
        return unified_response(
            code=200,
            message="获取成功",
            data={
                "total_knowledge_bases": total_kbs,
                "total_knowledge_points": total_points,
                "total_relations": total_relations,
                "subject_distribution": {
                    subject.value: count for subject, count in subject_stats
                },
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取统计信息失败: {str(e)}",
            data=None
        )
