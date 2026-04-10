"""
知识库导入工具
用于批量导入多学科知识到数据库
"""

import json
import asyncio
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlmodel import Session

from app.models.database import get_session
from app.models.knowledge_model import (
    KnowledgeBase,
    KnowledgePoint,
    SubjectType,
    KnowledgeLevel,
    KnowledgePointType,
)
from app.services.knowledge_service import (
    KnowledgeBaseService,
    KnowledgePointService,
    KnowledgeImportService,
)


async def import_from_markdown_folder(
    session: Session,
    kb_id: int,
    folder_path: str,
    recursive: bool = True,
) -> Dict[str, Any]:
    """
    从Markdown文件夹批量导入知识点
    
    Args:
        session: 数据库会话
        kb_id: 知识库ID
        folder_path: 文件夹路径
        recursive: 是否递归处理子文件夹
        
    Returns:
        dict: 导入结果
    """
    folder = Path(folder_path)
    if not folder.exists():
        return {"success": False, "error": f"文件夹不存在: {folder_path}"}
    
    md_files = list(folder.rglob("*.md")) if recursive else list(folder.glob("*.md"))
    
    total_files = len(md_files)
    success_count = 0
    fail_count = 0
    total_points = 0
    
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
            
            result = await KnowledgeImportService.import_from_document(
                session=session,
                kb_id=kb_id,
                markdown_content=content,
                doc_name=md_file.name,
            )
            
            if result.get("success"):
                success_count += 1
                total_points += result.get("total_points", 0)
            else:
                fail_count += 1
                
        except Exception as e:
            print(f"导入文件失败 {md_file}: {e}")
            fail_count += 1
    
    return {
        "success": True,
        "total_files": total_files,
        "success_count": success_count,
        "fail_count": fail_count,
        "total_points": total_points,
    }


async def import_from_json_file(
    session: Session,
    kb_id: int,
    json_file: str,
) -> Dict[str, Any]:
    """
    从JSON文件导入知识点
    
    JSON格式示例:
    {
        "knowledge_points": [
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
    }
    
    Args:
        session: 数据库会话
        kb_id: 知识库ID
        json_file: JSON文件路径
        
    Returns:
        dict: 导入结果
    """
    file_path = Path(json_file)
    if not file_path.exists():
        return {"success": False, "error": f"文件不存在: {json_file}"}
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        points_data = data.get("knowledge_points", data)
        
        if not isinstance(points_data, list):
            return {"success": False, "error": "JSON格式错误，需要知识点列表"}
        
        result = await KnowledgeImportService.import_from_json(
            session=session,
            kb_id=kb_id,
            json_data=points_data,
        )
        
        return result
        
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON解析错误: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_knowledge_base_for_subject(
    session: Session,
    subject: SubjectType,
    name: str,
    level: KnowledgeLevel = KnowledgeLevel.SENIOR,
    description: str = "",
) -> KnowledgeBase:
    """
    为学科创建知识库
    
    Args:
        session: 数据库会话
        subject: 学科类型
        name: 知识库名称
        level: 难度等级
        description: 描述
        
    Returns:
        KnowledgeBase: 创建的知识库
    """
    return KnowledgeBaseService.create_knowledge_base(
        session=session,
        name=name,
        subject=subject,
        description=description,
        level=level,
    )


async def init_multi_subject_knowledge_bases(session: Session) -> Dict[str, int]:
    """
    初始化多学科知识库
    
    创建各学科的基础知识库
    
    Args:
        session: 数据库会话
        
    Returns:
        dict: 学科 -> 知识库ID 映射
    """
    subjects_config = {
        SubjectType.MATH: ("数学知识库", "包含代数、几何、微积分等数学知识点"),
        SubjectType.PHYSICS: ("物理知识库", "包含力学、电磁学、热学等物理知识点"),
        SubjectType.CHEMISTRY: ("化学知识库", "包含无机化学、有机化学、物理化学等知识点"),
        SubjectType.BIOLOGY: ("生物知识库", "包含细胞生物学、遗传学、生态学等知识点"),
        SubjectType.COMPUTER: ("计算机科学知识库", "包含编程、数据结构、算法等知识点"),
        SubjectType.CHINESE: ("语文知识库", "包含文学、语法、写作等知识点"),
        SubjectType.ENGLISH: ("英语知识库", "包含语法、词汇、阅读理解等知识点"),
        SubjectType.HISTORY: ("历史知识库", "包含中国历史、世界历史等知识点"),
        SubjectType.GEOGRAPHY: ("地理知识库", "包含自然地理、人文地理等知识点"),
        SubjectType.POLITICS: ("政治知识库", "包含马克思主义、政治经济学等知识点"),
    }
    
    kb_ids = {}
    
    for subject, (name, description) in subjects_config.items():
        kb = create_knowledge_base_for_subject(
            session=session,
            subject=subject,
            name=name,
            description=description,
        )
        kb_ids[subject.value] = kb.id
        print(f"创建知识库: {name} (ID={kb.id})")
    
    return kb_ids


async def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="知识库导入工具")
    parser.add_argument("command", choices=["init", "import-md", "import-json", "list"],
                        help="命令: init=初始化知识库, import-md=导入Markdown, import-json=导入JSON, list=列出知识库")
    parser.add_argument("--kb-id", type=int, help="知识库ID")
    parser.add_argument("--path", type=str, help="文件或文件夹路径")
    parser.add_argument("--subject", type=str, help="学科类型")
    parser.add_argument("--recursive", action="store_true", help="递归处理子文件夹")
    
    args = parser.parse_args()
    
    session = next(get_session())
    
    try:
        if args.command == "init":
            kb_ids = await init_multi_subject_knowledge_bases(session)
            print("\n初始化完成，知识库ID映射:")
            for subject, kb_id in kb_ids.items():
                print(f"  {subject}: {kb_id}")
        
        elif args.command == "import-md":
            if not args.kb_id or not args.path:
                print("错误: 需要指定 --kb-id 和 --path")
                return
            
            result = await import_from_markdown_folder(
                session=session,
                kb_id=args.kb_id,
                folder_path=args.path,
                recursive=args.recursive,
            )
            print(f"\n导入结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        elif args.command == "import-json":
            if not args.kb_id or not args.path:
                print("错误: 需要指定 --kb-id 和 --path")
                return
            
            result = await import_from_json_file(
                session=session,
                kb_id=args.kb_id,
                json_file=args.path,
            )
            print(f"\n导入结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        elif args.command == "list":
            kbs = session.exec(
                "SELECT id, name, subject, total_points FROM knowledge_bases WHERE is_active = 1"
            ).all()
            print("\n知识库列表:")
            print("-" * 60)
            for kb in kbs:
                print(f"ID: {kb[0]}, 名称: {kb[1]}, 学科: {kb[2]}, 知识点数: {kb[3]}")
            print("-" * 60)
    
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
