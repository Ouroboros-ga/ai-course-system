"""
知识库批量导入脚本
循环调用Docling解析本地文档，导入到知识库数据库

使用方式:
    python -m app.tools.batch_import_knowledge --kb-name "数学知识库" --path "E:/知识库/数学"
    python -m app.tools.batch_import_knowledge --kb-id 1 --path "E:/知识库/数学" --recursive
"""

import os
import sys
import asyncio
import argparse
import logging
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

import chardet  # 新增依赖，用于编码检测

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

try:
    from sqlmodel import Session, select
except ImportError as e:
    print(f"错误: 无法导入sqlmodel - {e}")
    print("请确保已安装依赖: pip install sqlmodel")
    sys.exit(1)

try:
    from app.models.database import get_session, create_tables
    from app.models.knowledge_model import KnowledgeBase, SubjectType, KnowledgeLevel
    from app.services.knowledge_service import (
        KnowledgeBaseService,
        KnowledgeImportService,
    )
except ImportError as e:
    print(f"错误: 无法导入应用模块 - {e}")
    print("请确保在backend目录下运行此脚本")
    traceback.print_exc()
    sys.exit(1)


SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", 
    ".md", ".txt", ".html", ".htm"
}


def read_text_with_fallback(file_path: Path) -> str:
    """
    尝试多种编码读取文本文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: 文件内容
        
    Raises:
        UnicodeDecodeError: 所有编码尝试均失败
    """
    encodings = ['utf-8', 'gbk', 'gb18030', 'latin-1']
    # 先尝试用 chardet 检测
    try:
        raw_data = file_path.read_bytes()
        detected = chardet.detect(raw_data)
        if detected['encoding']:
            encodings.insert(0, detected['encoding'])
    except Exception:
        pass
    
    for enc in encodings:
        try:
            return raw_data.decode(enc) if 'raw_data' in locals() else file_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"无法使用任何已知编码读取文件: {file_path}")


class KnowledgeBatchImporter:
    """知识库批量导入器"""
    
    def __init__(self, session: Session):
        """
        初始化导入器
        
        Args:
            session: 数据库会话（外部传入，统一管理）
        """
        self.session = session
        self.total_files = 0
        self.success_count = 0
        self.fail_count = 0
        self.total_points = 0
        self.failed_files: List[str] = []
    
    async def import_from_folder(
        self,
        kb_id: int,
        folder_path: str,
        recursive: bool = True,
        extensions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        从文件夹批量导入文档到知识库
        
        Args:
            kb_id: 知识库ID
            folder_path: 文件夹路径
            recursive: 是否递归处理子文件夹
            extensions: 要处理的文件扩展名列表
            
        Returns:
            dict: 导入结果统计
        """
        kb = self.session.get(KnowledgeBase, kb_id)
        if not kb:
            return {
                "success": False,
                "error": f"知识库不存在: ID={kb_id}"
            }
        
        logger.info(f"目标知识库: {kb.name} (ID={kb_id}, 学科={kb.subject.value})")
        
        folder = Path(folder_path)
        if not folder.exists():
            return {
                "success": False,
                "error": f"文件夹不存在: {folder_path}"
            }
        
        # 统一转为小写集合
        ext_set = {ext.lower() for ext in (extensions or SUPPORTED_EXTENSIONS)}
        
        if recursive:
            files = [f for f in folder.rglob("*") if f.suffix.lower() in ext_set]
        else:
            files = [f for f in folder.glob("*") if f.suffix.lower() in ext_set]
        
        self.total_files = len(files)
        logger.info(f"发现 {self.total_files} 个待处理文件")
        
        if self.total_files == 0:
            return {
                "success": True,
                "message": "未找到符合条件的文件",
                "total_files": 0,
            }
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"[{i}/{self.total_files}] 处理文件: {file_path.name}")
            logger.info(f"{'='*60}")
            
            try:
                result = await self._process_single_file(
                    kb_id=kb_id,
                    file_path=file_path,
                )
                
                if result.get("success"):
                    self.success_count += 1
                    self.total_points += result.get("total_points", 0)
                    logger.info(f"✓ 成功: 导入 {result.get('total_points', 0)} 个知识点")
                else:
                    self.fail_count += 1
                    self.failed_files.append(str(file_path))
                    logger.error(f"✗ 失败: {result.get('error', '未知错误')}")
                    
            except Exception as e:
                self.fail_count += 1
                self.failed_files.append(str(file_path))
                logger.error(f"✗ 异常: {str(e)}", exc_info=True)
        
        return {
            "success": True,
            "total_files": self.total_files,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "total_points": self.total_points,
            "failed_files": self.failed_files,
        }
    
    async def _process_single_file(
        self,
        kb_id: int,
        file_path: Path,
    ) -> Dict[str, Any]:
        """
        处理单个文件：解析 + 导入
        
        Args:
            kb_id: 知识库ID
            file_path: 文件路径
            
        Returns:
            dict: 处理结果
        """
        try:
            logger.info(f"  [Step 1] 使用Docling解析文档...")
            markdown_content = await self._parse_with_docling(file_path)
            
            if not markdown_content or len(markdown_content.strip()) < 50:
                return {
                    "success": False,
                    "error": "解析结果为空或内容过短"
                }
            
            logger.info(f"  [Step 2] 导入到知识库...")
            result = await KnowledgeImportService.import_from_document(
                session=self.session,
                kb_id=kb_id,
                markdown_content=markdown_content,
                doc_name=file_path.name,
            )
            
            return result
            
        except Exception as e:
            logger.error(f"处理文件失败: {file_path}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _parse_with_docling(self, file_path: Path) -> str:
        """
        使用Docling解析文件为Markdown（异步非阻塞）
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: Markdown内容，失败返回空字符串
        """
        try:
            from docling.document_converter import DocumentConverter
            
            converter = DocumentConverter()
            # Docling 的 convert 是同步阻塞操作，放入线程池执行
            result = await asyncio.to_thread(converter.convert, str(file_path))
            markdown_content = result.document.export_to_markdown()
            
            logger.info(f"      解析完成: {len(markdown_content)} 字符")
            return markdown_content
            
        except ImportError:
            logger.warning("Docling未安装，尝试备用解析方法")
            return await self._fallback_parse(file_path)
        except Exception as e:
            logger.error(f"Docling解析失败: {e}", exc_info=True)
            return await self._fallback_parse(file_path)
    
    async def _fallback_parse(self, file_path: Path) -> str:
        """
        备用解析方法（仅支持纯文本、Markdown、HTML、PDF简易提取）
        
        Returns:
            str: Markdown内容，若无法解析则返回空字符串
        """
        suffix = file_path.suffix.lower()
        
        # 对于纯文本和 Markdown，尝试读取
        if suffix in [".md", ".txt"]:
            try:
                content = read_text_with_fallback(file_path)
                if suffix == ".md":
                    return content
                else:
                    return f"# {file_path.stem}\n\n{content}"
            except UnicodeDecodeError as e:
                logger.error(f"读取文本文件失败: {e}", exc_info=True)
                return ""
        
        # HTML 转 Markdown
        elif suffix in [".html", ".htm"]:
            try:
                import html2text
                html_content = read_text_with_fallback(file_path)
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.ignore_images = False
                return h.handle(html_content)
            except ImportError:
                logger.error("html2text未安装，无法解析HTML")
                return ""
            except Exception as e:
                logger.error(f"HTML解析失败: {e}", exc_info=True)
                return ""
        
        # PDF 简易文本提取（需要 PyMuPDF）
        elif suffix == ".pdf":
            try:
                import fitz
                doc = fitz.open(str(file_path))
                text_parts = [f"# {file_path.stem}\n"]
                for page in doc:
                    text_parts.append(page.get_text())
                content = "\n\n".join(text_parts)
                if len(content.strip()) < 50:
                    logger.warning(f"PDF提取内容过短: {file_path}")
                    return ""
                return content
            except ImportError:
                logger.error("PyMuPDF未安装，无法解析PDF")
                return ""
            except Exception as e:
                logger.error(f"PDF解析失败: {e}", exc_info=True)
                return ""
        
        else:
            logger.warning(f"不支持的文件类型: {suffix}，无法降级解析")
            return ""


def get_or_create_knowledge_base(
    session: Session,
    kb_name: str,
    subject: str = "general",
    level: str = "senior",
    description: str = "",
) -> int:
    """
    获取或创建知识库（注意：若创建则会提交事务）
    
    Args:
        session: 数据库会话
        kb_name: 知识库名称
        subject: 学科类型
        level: 难度等级
        description: 描述
        
    Returns:
        int: 知识库ID
    """
    existing_kb = session.exec(
        select(KnowledgeBase).where(KnowledgeBase.name == kb_name)
    ).first()
    
    if existing_kb:
        logger.info(f"使用现有知识库: {kb_name} (ID={existing_kb.id})")
        return existing_kb.id
    
    # 标准化枚举值
    try:
        subject_enum = SubjectType(subject)
    except ValueError:
        subject_enum = SubjectType.GENERAL
    
    try:
        level_enum = KnowledgeLevel(level)
    except ValueError:
        level_enum = KnowledgeLevel.SENIOR
    
    kb = KnowledgeBaseService.create_knowledge_base(
        session=session,
        name=kb_name,
        subject=subject_enum,
        description=description or f"自动创建的知识库: {kb_name}",
        level=level_enum,
    )
    # 立即提交，使其他会话可见
    session.commit()
    logger.info(f"创建新知识库: {kb_name} (ID={kb.id})")
    return kb.id


async def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="知识库批量导入工具 - 使用Docling解析文档并导入知识库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 指定知识库名称（自动创建或使用现有）
  python -m app.tools.batch_import_knowledge --kb-name "数学知识库" --path "E:/知识库/数学"
  
  # 指定知识库ID
  python -m app.tools.batch_import_knowledge --kb-id 1 --path "E:/知识库/数学"
  
  # 指定学科类型
  python -m app.tools.batch_import_knowledge --kb-name "物理知识库" --subject physics --path "E:/知识库/物理"
  
  # 非递归模式（只处理顶层文件夹）
  python -m app.tools.batch_import_knowledge --kb-name "化学知识库" --path "E:/知识库/化学" --no-recursive
  
  # 指定文件类型
  python -m app.tools.batch_import_knowledge --kb-name "英语知识库" --path "E:/知识库/英语" --ext .pdf .docx
        """
    )
    
    parser.add_argument(
        "--kb-id",
        type=int,
        help="知识库ID（与--kb-name二选一）"
    )
    parser.add_argument(
        "--kb-name",
        type=str,
        help="知识库名称（不存在则自动创建）"
    )
    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="文档文件夹路径"
    )
    parser.add_argument(
        "--subject",
        type=str,
        default="general",
        choices=["math", "physics", "chemistry", "biology", "computer", 
                 "chinese", "english", "history", "geography", "politics", "general"],
        help="学科类型（创建新知识库时使用）"
    )
    parser.add_argument(
        "--level",
        type=str,
        default="senior",
        choices=["primary", "junior", "senior", "college", "graduate"],
        help="难度等级（创建新知识库时使用）"
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="不递归处理子文件夹"
    )
    parser.add_argument(
        "--ext",
        nargs="+",
        default=list(SUPPORTED_EXTENSIONS),
        help=f"要处理的文件扩展名（默认: {' '.join(SUPPORTED_EXTENSIONS)}）"
    )
    parser.add_argument(
        "--description",
        type=str,
        default="",
        help="知识库描述（创建新知识库时使用）"
    )
    
    args = parser.parse_args()
    
    if not args.kb_id and not args.kb_name:
        parser.error("必须指定 --kb-id 或 --kb-name")
    
    # 确保数据库表存在（只调用一次）
    create_tables()
    
    # 获取数据库会话，整个流程共用同一个会话
    session = next(get_session())
    
    try:
        if args.kb_id:
            kb_id = args.kb_id
        else:
            kb_id = get_or_create_knowledge_base(
                session=session,
                kb_name=args.kb_name,
                subject=args.subject,
                level=args.level,
                description=args.description,
            )
        
        importer = KnowledgeBatchImporter(session=session)
        
        start_time = datetime.now()
        logger.info(f"\n{'#'*60}")
        logger.info(f"# 开始批量导入")
        logger.info(f"# 时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"# 知识库ID: {kb_id}")
        logger.info(f"# 源路径: {args.path}")
        logger.info(f"# 递归模式: {'否' if args.no_recursive else '是'}")
        logger.info(f"{'#'*60}\n")
        
        result = await importer.import_from_folder(
            kb_id=kb_id,
            folder_path=args.path,
            recursive=not args.no_recursive,
            extensions=args.ext,
        )
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"# 导入完成")
        logger.info(f"# 耗时: {duration:.2f} 秒")
        logger.info(f"# 总文件数: {result.get('total_files', 0)}")
        logger.info(f"# 成功: {result.get('success_count', 0)}")
        logger.info(f"# 失败: {result.get('fail_count', 0)}")
        logger.info(f"# 知识点总数: {result.get('total_points', 0)}")
        
        if result.get("failed_files"):
            logger.info(f"\n失败文件列表:")
            for f in result["failed_files"]:
                logger.info(f"  - {f}")
        
        logger.info(f"{'#'*60}")
        
    finally:
        session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断操作")
    except Exception as e:
        print(f"\n错误: {e}")
        traceback.print_exc()
        sys.exit(1)