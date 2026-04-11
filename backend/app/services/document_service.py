"""
文档解析服务
负责文件解析、Markdown转换、智课脚本生成、RAG预处理
"""

import os
import json
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from app.common.llm_client import llm_client, Message
from app.common.RAG import rag_pipeline
from app.common.prompts.document_analysis import (
    KNOWLEDGE_EXTRACTION_PROMPT,
    build_knowledge_extraction_prompt
)
from app.common.prompts.knowledge_to_script import (
    KNOWLEDGE_TO_SCRIPT_PROMPT,
    build_knowledge_to_script_prompt
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """文件解析结果"""
    markdown_content: str
    filename: str
    file_path: str
    file_size: int
    parse_method: str
    error: Optional[str] = None


@dataclass
class StructureResult:
    """结构化解析结果"""
    groups: List[Dict[str, Any]] = field(default_factory=list)
    texts: List[Dict[str, Any]] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    pictures: List[Dict[str, Any]] = field(default_factory=list)
    raw_content: str = ""


@dataclass
class ScriptNode:
    """脚本节点"""
    chapter_id: str
    node_type: str
    title: str
    content: str
    page_start: int = 1
    page_end: int = 1
    duration: int = 60
    is_key_point: bool = False


@dataclass
class ScriptResult:
    """智课脚本结果"""
    title: str
    summary: str
    keywords: List[str]
    total_duration: int
    nodes: List[ScriptNode]
    script_content: Dict[str, Any]
    beautiful_markdown: str = ""


@dataclass
class RAGProcessResult:
    """RAG预处理结果"""
    formula_count: int = 0
    table_count: int = 0
    domain_term_count: int = 0
    tree_node_count: int = 0
    processed_text: str = ""
    knowledge_points: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class DocumentProcessResult:
    """完整文档处理结果"""
    parse_result: ParseResult
    structure_result: StructureResult
    script_result: ScriptResult
    rag_result: RAGProcessResult
    mind_map: Dict[str, Any]


class DocumentParser:
    """文档解析器"""
    
    @staticmethod
    async def parse_file(file_path: Path, filename: str) -> ParseResult:
        """
        解析文件，返回Markdown内容
        
        Args:
            file_path: 文件路径
            filename: 文件名
            
        Returns:
            ParseResult: 解析结果
        """
        file_size = file_path.stat().st_size if file_path.exists() else 0
        
        try:
            markdown_content = await DocumentParser._parse_with_docling(file_path, filename)
            return ParseResult(
                markdown_content=markdown_content,
                filename=filename,
                file_path=str(file_path),
                file_size=file_size,
                parse_method="docling"
            )
        except Exception as e:
            logger.warning(f"Docling解析失败，使用备用方法: {e}")
            markdown_content = await DocumentParser._fallback_parse(file_path, filename)
            return ParseResult(
                markdown_content=markdown_content,
                filename=filename,
                file_path=str(file_path),
                file_size=file_size,
                parse_method="fallback"
            )
    
    @staticmethod
    async def _parse_with_docling(file_path: Path, filename: str) -> str:
        """
        使用Docling解析文件，返回Markdown内容
        """
        try:
            from docling.document_converter import DocumentConverter
            
            logger.info(f"[Docling] 开始解析: {filename}")
            converter = DocumentConverter()
            result = converter.convert(str(file_path))
            markdown_content = result.document.export_to_markdown()
            logger.info(f"[Docling] 解析完成，生成 {len(markdown_content)} 字符Markdown")
            return markdown_content
            
        except ImportError:
            raise ImportError("Docling未安装")
        except Exception as e:
            raise Exception(f"Docling解析失败: {e}")
    
    @staticmethod
    async def _fallback_parse(file_path: Path, filename: str) -> str:
        """
        备用解析方法（当Docling不可用时）
        """
        suffix = file_path.suffix.lower()
        
        if suffix == ".pdf":
            return await DocumentParser._parse_pdf(file_path, filename)
        elif suffix in [".docx", ".doc"]:
            return await DocumentParser._parse_docx(file_path, filename)
        elif suffix in [".pptx", ".ppt"]:
            return await DocumentParser._parse_pptx(file_path, filename)
        elif suffix in [".txt", ".md", ".json", ".py", ".js", ".html", ".css"]:
            return await DocumentParser._parse_text(file_path, filename)
        else:
            return f"# {filename}\n\n[不支持的文件格式: {suffix}]"
    
    @staticmethod
    async def _parse_pdf(file_path: Path, filename: str) -> str:
        """解析PDF文件"""
        try:
            import pdfplumber
            text_parts = [f"# {Path(filename).stem}\n"]
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text:
                        text_parts.append(f"\n## 第{page_num}页\n")
                        text_parts.append(f"{text}\n")
            return "\n".join(text_parts)
        except ImportError:
            return f"# {filename}\n\n[PDF文件需要安装pdfplumber库才能解析]"
    
    @staticmethod
    async def _parse_docx(file_path: Path, filename: str) -> str:
        """解析Word文件"""
        try:
            from docx import Document
            doc = Document(file_path)
            text_parts = [f"# {Path(filename).stem}\n"]
            
            for para in doc.paragraphs:
                if para.text.strip():
                    if para.style.name.startswith('Heading'):
                        level = int(para.style.name.replace('Heading ', '')) if para.style.name != 'Heading' else 1
                        text_parts.append(f"\n{'#' * level} {para.text.strip()}\n")
                    else:
                        text_parts.append(f"{para.text.strip()}\n")
            
            return "\n".join(text_parts)
        except ImportError:
            return f"# {filename}\n\n[Word文件需要安装python-docx库才能解析]"
    
    @staticmethod
    async def _parse_pptx(file_path: Path, filename: str) -> str:
        """解析PPT文件"""
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            text_parts = [f"# {Path(filename).stem}\n"]
            text_parts.append("\n> 本文档由PPT自动解析生成\n")
            
            for slide_num, slide in enumerate(prs.slides, 1):
                title = ""
                if slide.shapes.title and slide.shapes.title.text:
                    title = slide.shapes.title.text.strip()
                
                text_parts.append(f"\n## 第{slide_num}页{': ' + title if title else ''}\n")
                
                content_items = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        text = shape.text.strip()
                        if text != title:
                            content_items.append(text)
                
                for item in content_items:
                    if len(item) < 50 and not item.endswith(('。', '，', '：', '.', ',', ':')):
                        if item.endswith('?') or item.endswith('？'):
                            text_parts.append(f"\n### ❓ {item}\n")
                        else:
                            text_parts.append(f"\n### {item}\n")
                    else:
                        text_parts.append(f"\n{item}\n")
            
            return "\n".join(text_parts)
        except ImportError:
            return f"# {filename}\n\n[PPT文件需要安装python-pptx库才能解析]"
    
    @staticmethod
    async def _parse_text(file_path: Path, filename: str) -> str:
        """解析纯文本文件"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        suffix = file_path.suffix.lower()
        if suffix == ".md":
            return content
        else:
            return f"# {filename}\n\n```\n{content}\n```"


class StructureParser:
    """结构化解析器"""
    
    @staticmethod
    def parse_markdown_to_structure(markdown_content: str, filename: str) -> StructureResult:
        """
        将Markdown内容解析为结构化数据
        """
        lines = markdown_content.split("\n")
        texts = []
        groups = []
        
        current_group_idx = 0
        text_idx = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("##"):
                groups.append({
                    "self_ref": f"#/groups/{current_group_idx}",
                    "name": line.lstrip("#").strip(),
                    "label": "section",
                    "content_layer": "body",
                })
                current_group_idx += 1
            else:
                texts.append({
                    "self_ref": f"#/texts/{text_idx}",
                    "label": "paragraph",
                    "text": line,
                    "page_no": 1,
                })
                text_idx += 1
        
        if not groups:
            groups.append({
                "self_ref": "#/groups/0",
                "name": filename,
                "label": "section",
                "content_layer": "body",
            })
        
        return StructureResult(
            groups=groups,
            texts=texts,
            tables=[],
            pictures=[],
            raw_content=markdown_content
        )


class KnowledgeExtractor:
    """知识点提取器 - 使用LLM从文档中提取结构化知识点"""

    @staticmethod
    async def extract_knowledge_points(
        document_content: str,
        filename: str = "",
        max_content_length: int = 8000
    ) -> str:
        """
        从文档内容中提取知识点，返回结构化Markdown

        Args:
            document_content: 文档内容
            filename: 文件名
            max_content_length: 最大内容长度

        Returns:
            str: 结构化的Markdown知识点文档
        """
        logger.info(f"[KnowledgeExtractor] 开始提取知识点: {filename}")

        # 截断内容以适应模型上下文限制
        if len(document_content) > max_content_length:
            truncated_content = document_content[:max_content_length]
            truncated_content += f"\n\n[内容已截断，原长度: {len(document_content)} 字符]"
        else:
            truncated_content = document_content

        # 使用提示词构建函数
        user_prompt = build_knowledge_extraction_prompt(truncated_content, filename)

        try:
            messages = [
                Message(role="system", content=KNOWLEDGE_EXTRACTION_PROMPT),
                Message(role="user", content=user_prompt)
            ]

            logger.info(f"[KnowledgeExtractor] 发送AI请求，内容长度: {len(user_prompt)} 字符")
            response = await llm_client.chat(messages, temperature=0.3)
            logger.info(f"[KnowledgeExtractor] 收到AI响应，长度: {len(response.content)} 字符")

            return response.content

        except Exception as e:
            logger.error(f"[KnowledgeExtractor] 知识点提取失败: {e}")
            # 返回一个基本的错误提示Markdown
            return f"""# {filename or '文档'} - 知识点提取失败

由于技术原因，无法自动提取知识点。请手动整理文档内容。

**错误信息**: {str(e)}
"""

    @staticmethod
    def parse_knowledge_markdown(markdown_content: str) -> List[Dict[str, Any]]:
        """
        解析知识点Markdown，提取结构化的知识点列表

        Args:
            markdown_content: 知识点Markdown内容

        Returns:
            List[Dict]: 知识点列表，每项包含 id, title, level, content
        """
        knowledge_points = []
        lines = markdown_content.split('\n')

        current_kp = None
        content_buffer = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检测标题行
            if line.startswith('#'):
                # 保存上一个知识点
                if current_kp:
                    current_kp['content'] = '\n'.join(content_buffer).strip()
                    knowledge_points.append(current_kp)
                    content_buffer = []

                # 解析标题级别
                level = len(line) - len(line.lstrip('#'))
                title = line.lstrip('#').strip()

                current_kp = {
                    'id': f"知识点{len(knowledge_points) + 1}",
                    'title': title,
                    'level': level,
                    'content': ''
                }
            else:
                # 累积内容
                if current_kp:
                    content_buffer.append(line)

        # 保存最后一个知识点
        if current_kp:
            current_kp['content'] = '\n'.join(content_buffer).strip()
            knowledge_points.append(current_kp)

        logger.info(f"[KnowledgeExtractor] 解析出 {len(knowledge_points)} 个知识点")
        return knowledge_points

    @staticmethod
    async def generate_script_from_knowledge(
        knowledge_markdown: str,
        filename: str = "",
        max_content_length: int = 8000
    ) -> Dict[str, Any]:
        """
        从知识点 Markdown 生成结构化智课脚本

        Args:
            knowledge_markdown: 知识点 Markdown 内容
            filename: 文件名
            max_content_length: 最大内容长度

        Returns:
            Dict: 结构化脚本 JSON
        """
        logger.info(f"[KnowledgeExtractor] 开始从知识点生成脚本: {filename}")

        # 截断内容以适应模型上下文限制
        if len(knowledge_markdown) > max_content_length:
            truncated_content = knowledge_markdown[:max_content_length]
            truncated_content += f"\n\n[内容已截断，原长度: {len(knowledge_markdown)} 字符]"
        else:
            truncated_content = knowledge_markdown

        # 使用提示词构建函数
        user_prompt = build_knowledge_to_script_prompt(truncated_content, filename)

        try:
            messages = [
                Message(role="system", content=KNOWLEDGE_TO_SCRIPT_PROMPT),
                Message(role="user", content=user_prompt)
            ]

            logger.info(f"[KnowledgeExtractor] 发送脚本生成请求，内容长度: {len(user_prompt)} 字符")
            response = await llm_client.chat(messages, temperature=0.5)
            logger.info(f"[KnowledgeExtractor] 收到脚本响应，长度: {len(response.content)} 字符")

            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                script_content = json.loads(json_match.group())
            else:
                # 如果无法解析 JSON，返回默认结构
                script_content = KnowledgeExtractor._create_default_script(filename, knowledge_markdown)

            return script_content

        except Exception as e:
            logger.error(f"[KnowledgeExtractor] 脚本生成失败: {e}")
            return KnowledgeExtractor._create_default_script(filename, knowledge_markdown)

    @staticmethod
    def _create_default_script(filename: str, knowledge_markdown: str) -> Dict[str, Any]:
        """
        创建默认脚本（当AI调用失败时）
        """
        lines = [l.strip() for l in knowledge_markdown.split("\n") if l.strip().startswith('#')]

        sections = []

        # 开场白
        sections.append({
            "type": "opening",
            "id": "sec_000",
            "title": "课程开场",
            "content": f"同学们好！欢迎学习《{Path(filename).stem if filename else '本课程'}》。在今天的课程中，我们将一起探索这个有趣的主题。希望通过今天的学习，大家能够掌握核心概念，并能够灵活运用到实际问题中。",
            "duration": 45,
            "tone": "enthusiastic",
            "transitions": {
                "next": "接下来，让我们进入今天的第一个知识点。"
            }
        })

        # 知识点
        for idx, line in enumerate(lines[:8]):
            if idx == 0:  # 跳过主标题
                continue

            title = line.lstrip('#').strip()
            prev_transition = "首先，" if idx == 1 else ("最后，" if idx == len(lines[:8]) - 1 else "接下来，")
            next_transition = "" if idx == len(lines[:8]) - 1 else "理解了概念后，我们继续往下看。"

            sections.append({
                "type": "knowledge_point",
                "id": f"sec_{idx:03d}",
                "title": title[:40] + ("..." if len(title) > 40 else ""),
                "definition": title,
                "explanation": f"这是关于{title[:20]}的详细解释。",
                "examples": [f"示例：相关应用场景"],
                "content": f"{prev_transition}我们来学习{title[:40]}。{title}这个概念非常重要。",
                "duration": 90,
                "difficulty": "medium",
                "is_key_point": idx % 2 == 0,
                "transitions": {
                    "prev": prev_transition.strip('，'),
                    "next": next_transition
                }
            })

        # 总结语
        sections.append({
            "type": "summary",
            "id": "sec_999",
            "title": "课程总结",
            "key_points": ["核心要点回顾"],
            "content": "今天我们学习了本课程的核心内容，希望大家课后能够复习巩固。",
            "duration": 60,
            "next_preview": "下节课我们将继续深入学习。"
        })

        return {
            "title": Path(filename).stem if filename else "课程",
            "summary": f"本课程《{Path(filename).stem if filename else '课程'}》共包含 {len(sections)} 个教学环节。",
            "keywords": ["知识点", "课程"],
            "total_duration": sum(s.get("duration", 60) for s in sections),
            "sections": sections
        }


class ScriptGenerator:
    """智课脚本生成器"""
    
    @staticmethod
    async def generate_script(
        markdown_content: str,
        filename: str,
        max_content_length: int = 6000
    ) -> ScriptResult:
        """
        调用AI生成智课脚本
        
        Args:
            markdown_content: Markdown内容
            filename: 文件名
            max_content_length: 最大内容长度
            
        Returns:
            ScriptResult: 脚本结果
        """
        logger.info(f"[ScriptGenerator] 开始生成脚本: {filename}")
        
        if len(markdown_content) > max_content_length:
            truncated_content = markdown_content[:max_content_length]
            truncated_content += f"\n\n[内容已截断，原长度: {len(markdown_content)} 字符]"
        else:
            truncated_content = markdown_content
        
        system_prompt = """你是一位专业的课程设计师。请根据用户提供的文档内容，生成一份结构化的智课脚本。

你需要完成以下任务：
1. 分析文档内容，提取核心知识点
2. 将内容拆分为多个教学节点（每个节点60-120秒）
3. 为每个节点生成标题、内容摘要和时长
4. 识别重点知识点
5. 生成课程总结

请以JSON格式返回，结构如下：
{
    "title": "课程标题",
    "summary": "课程摘要",
    "keywords": ["关键词1", "关键词2", ...],
    "total_duration": 总时长(秒),
    "nodes": [
        {
            "chapter_id": "chap_000",
            "node_type": "lecture",
            "title": "节点标题",
            "content": "节点内容/讲解文本",
            "page_start": 1,
            "page_end": 1,
            "duration": 60,
            "is_key_point": false
        },
        ...
    ]
}

节点类型(node_type)可选值：
- lecture: 讲解
- question: 问题
- summary: 总结
- interactive: 交互

请确保返回的是有效的JSON格式。"""

        user_prompt = f"""请根据以下文档内容生成智课脚本：

文件名: {filename}

文档内容：
{truncated_content}

请生成结构化的智课脚本JSON。"""

        try:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ]
            
            logger.info(f"[ScriptGenerator] 发送AI请求，内容长度: {len(user_prompt)} 字符")
            response = await llm_client.chat(messages)
            logger.info(f"[ScriptGenerator] 收到AI响应，长度: {len(response.content)} 字符")
            
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                script_content = json.loads(json_match.group())
            else:
                script_content = ScriptGenerator._create_default_script(filename, markdown_content)
            
        except Exception as e:
            logger.warning(f"[ScriptGenerator] AI调用失败: {e}，使用默认脚本")
            script_content = ScriptGenerator._create_default_script(filename, markdown_content)
        
        return ScriptGenerator._build_script_result(script_content, filename, markdown_content)
    
    @staticmethod
    def _create_default_script(filename: str, content: str) -> dict:
        """
        创建默认脚本（当AI调用失败时）
        """
        lines = [l.strip() for l in content.split("\n") if l.strip() and len(l.strip()) > 10]
        
        nodes = []
        for idx, line in enumerate(lines[:15]):
            node_type = "lecture"
            if idx == len(lines[:15]) - 1:
                node_type = "summary"
            
            nodes.append({
                "chapter_id": f"chap_{idx:03d}",
                "node_type": node_type,
                "title": line[:50] + ("..." if len(line) > 50 else ""),
                "content": line,
                "page_start": 1,
                "page_end": 1,
                "duration": 60,
                "is_key_point": idx % 3 == 0,
            })
        
        if not nodes:
            nodes = [{
                "chapter_id": "chap_000",
                "node_type": "lecture",
                "title": "课程导入",
                "content": f"欢迎学习本课程，本课程来源于文件 {filename}",
                "page_start": 1,
                "page_end": 1,
                "duration": 60,
                "is_key_point": True,
            }]
        
        return {
            "title": Path(filename).stem,
            "summary": f"本课程《{Path(filename).stem}》共包含 {len(nodes)} 个知识点。",
            "keywords": ["知识点", "课程", Path(filename).stem],
            "total_duration": sum(n["duration"] for n in nodes),
            "nodes": nodes,
        }
    
    @staticmethod
    def _build_script_result(script_content: dict, filename: str, markdown_content: str) -> ScriptResult:
        """构建脚本结果对象"""
        summary_text = script_content.get("summary", f"本课程《{Path(filename).stem}》包含 {len(script_content.get('nodes', []))} 个知识点。")
        keywords = script_content.get("keywords", ["知识点", "课程", Path(filename).stem])
        
        nodes = []
        for node_data in script_content.get("nodes", []):
            nodes.append(ScriptNode(
                chapter_id=node_data.get("chapter_id", "chap_000"),
                node_type=node_data.get("node_type", "lecture"),
                title=node_data.get("title", "未命名节点"),
                content=node_data.get("content", ""),
                page_start=node_data.get("page_start", 1),
                page_end=node_data.get("page_end", 1),
                duration=node_data.get("duration", 60),
                is_key_point=node_data.get("is_key_point", False),
            ))
        
        logger.info(f"[ScriptGenerator] 生成完成: {len(nodes)} 个节点")
        
        return ScriptResult(
            title=script_content.get("title", Path(filename).stem),
            summary=summary_text,
            keywords=keywords,
            total_duration=script_content.get("total_duration", sum(n.duration for n in nodes)),
            nodes=nodes,
            script_content=script_content,
            beautiful_markdown=markdown_content
        )


class MindMapGenerator:
    """思维导图生成器"""
    
    @staticmethod
    def generate(script_result: ScriptResult) -> Dict[str, Any]:
        """
        根据脚本内容生成思维导图JSON结构
        """
        nodes = script_result.nodes
        title = script_result.title
        keywords = script_result.keywords
        
        children = []
        
        for node in nodes:
            child = {
                "text": node.title,
            }
            if node.is_key_point:
                child["highlight"] = True
            children.append(child)
        
        if not children:
            for kw in keywords[:5]:
                children.append({"text": kw})
        
        if not children:
            children = [
                {"text": "知识点1"},
                {"text": "知识点2"},
                {"text": "知识点3"},
            ]
        
        return {
            "text": title,
            "children": children
        }


class RAGProcessor:
    """RAG预处理器"""
    
    @staticmethod
    def process(
        markdown_content: str,
        doc_name: str,
        doc_id: str
    ) -> RAGProcessResult:
        """
        执行RAG预处理流水线
        
        Args:
            markdown_content: Markdown内容
            doc_name: 文档名称
            doc_id: 文档ID
            
        Returns:
            RAGProcessResult: RAG处理结果
        """
        logger.info(f"[RAGProcessor] 开始RAG预处理: {doc_name}")
        
        try:
            rag_result = rag_pipeline.process_document(
                markdown_text=markdown_content,
                doc_name=doc_name,
                doc_id=doc_id,
            )
            
            knowledge_points = RAGProcessor._extract_knowledge_points(rag_result)
            
            result = RAGProcessResult(
                formula_count=rag_result.formula_result.formula_count,
                table_count=len(rag_result.table_results),
                domain_term_count=rag_result.tokenize_result.domain_term_count,
                tree_node_count=rag_result.tree_result.total_nodes,
                processed_text=rag_result.processed_text,
                knowledge_points=knowledge_points,
            )
            
            logger.info(f"[RAGProcessor] 预处理完成:")
            logger.info(f"  - 公式: {result.formula_count}个")
            logger.info(f"  - 表格: {result.table_count}个")
            logger.info(f"  - 领域术语: {result.domain_term_count}个")
            logger.info(f"  - 知识树节点: {result.tree_node_count}个")
            logger.info(f"  - 知识点: {len(knowledge_points)}个")
            
            return result
            
        except Exception as e:
            logger.error(f"[RAGProcessor] 预处理失败: {e}")
            return RAGProcessResult(error=str(e))
    
    @staticmethod
    def _extract_knowledge_points(rag_result) -> List[Dict[str, Any]]:
        """
        从RAG结果中提取知识点列表
        """
        knowledge_points = []
        
        if hasattr(rag_result, 'tree_result') and rag_result.tree_result:
            tree = rag_result.tree_result.tree
            if tree:
                RAGProcessor._traverse_tree(tree, knowledge_points)
        
        return knowledge_points
    
    @staticmethod
    def _traverse_tree(node, knowledge_points: List[Dict[str, Any]], path: str = ""):
        """
        遍历知识树，提取知识点
        """
        if node is None:
            return
        
        current_path = f"{path}/{node.title}" if path else node.title
        
        if node.content and len(node.content.strip()) > 20:
            knowledge_points.append({
                "id": f"知识点{len(knowledge_points) + 1}",
                "title": node.title,
                "content": node.content[:500],
                "path": current_path,
                "level": node.level,
            })
        
        for child in node.children:
            RAGProcessor._traverse_tree(child, knowledge_points, current_path)


class DocumentService:
    """文档处理服务"""

    def __init__(self):
        self.parser = DocumentParser()
        self.structure_parser = StructureParser()
        self.knowledge_extractor = KnowledgeExtractor()
        self.script_generator = ScriptGenerator()
        self.mind_map_generator = MindMapGenerator()
        self.rag_processor = RAGProcessor()
    
    async def process_document(
        self,
        file_path: Path,
        filename: str,
        enable_rag: bool = True,
        enable_script: bool = True
    ) -> DocumentProcessResult:
        """
        完整的文档处理流程
        
        Args:
            file_path: 文件路径
            filename: 文件名
            enable_rag: 是否启用RAG预处理
            enable_script: 是否生成智课脚本
            
        Returns:
            DocumentProcessResult: 完整处理结果
        """
        logger.info(f"[DocumentService] 开始处理文档: {filename}")
        
        parse_result = await self.parser.parse_file(file_path, filename)
        
        structure_result = self.structure_parser.parse_markdown_to_structure(
            parse_result.markdown_content, filename
        )
        
        if enable_script:
            script_result = await self.script_generator.generate_script(
                parse_result.markdown_content, filename
            )
        else:
            script_result = ScriptResult(
                title=Path(filename).stem,
                summary="",
                keywords=[],
                total_duration=0,
                nodes=[],
                script_content={},
                beautiful_markdown=parse_result.markdown_content
            )
        
        if enable_rag:
            rag_result = self.rag_processor.process(
                parse_result.markdown_content,
                filename,
                str(hash(file_path))
            )
        else:
            rag_result = RAGProcessResult()
        
        mind_map = self.mind_map_generator.generate(script_result)
        
        logger.info(f"[DocumentService] 文档处理完成: {filename}")
        
        return DocumentProcessResult(
            parse_result=parse_result,
            structure_result=structure_result,
            script_result=script_result,
            rag_result=rag_result,
            mind_map=mind_map
        )
    
    async def parse_only(self, file_path: Path, filename: str) -> ParseResult:
        """
        仅解析文件，不进行其他处理
        """
        return await self.parser.parse_file(file_path, filename)

    async def extract_knowledge_only(
        self,
        markdown_content: str,
        filename: str = ""
    ) -> Dict[str, Any]:
        """
        仅提取知识点

        Args:
            markdown_content: Markdown内容
            filename: 文件名

        Returns:
            Dict: 包含 knowledge_markdown 和 knowledge_points 的结果
        """
        knowledge_markdown = await self.knowledge_extractor.extract_knowledge_points(
            markdown_content, filename
        )
        knowledge_points = self.knowledge_extractor.parse_knowledge_markdown(
            knowledge_markdown
        )
        return {
            "knowledge_markdown": knowledge_markdown,
            "knowledge_points": knowledge_points
        }

    async def generate_script_from_knowledge_only(
        self,
        knowledge_markdown: str,
        filename: str = ""
    ) -> Dict[str, Any]:
        """
        仅从知识点生成智课脚本

        Args:
            knowledge_markdown: 知识点 Markdown 内容
            filename: 文件名

        Returns:
            Dict: 结构化脚本 JSON
        """
        return await self.knowledge_extractor.generate_script_from_knowledge(
            knowledge_markdown, filename
        )

    async def extract_and_generate_script(
        self,
        markdown_content: str,
        filename: str = ""
    ) -> Dict[str, Any]:
        """
        完整流程：提取知识点并生成智课脚本

        Args:
            markdown_content: 文档 Markdown 内容
            filename: 文件名

        Returns:
            Dict: 包含 knowledge_markdown, knowledge_points, script 的完整结果
        """
        logger.info(f"[DocumentService] 开始完整流程：提取知识点并生成脚本 - {filename}")

        # 步骤1：提取知识点
        knowledge_result = await self.extract_knowledge_only(markdown_content, filename)
        knowledge_markdown = knowledge_result["knowledge_markdown"]
        knowledge_points = knowledge_result["knowledge_points"]

        # 步骤2：从知识点生成脚本
        script = await self.knowledge_extractor.generate_script_from_knowledge(
            knowledge_markdown, filename
        )

        logger.info(f"[DocumentService] 完整流程完成：提取了 {len(knowledge_points)} 个知识点，生成了 {len(script.get('sections', []))} 个教学环节")

        return {
            "knowledge_markdown": knowledge_markdown,
            "knowledge_points": knowledge_points,
            "script": script
        }

    async def generate_script_only(
        self,
        markdown_content: str,
        filename: str
    ) -> ScriptResult:
        """
        仅生成智课脚本（基于原始文档内容）
        """
        return await self.script_generator.generate_script(markdown_content, filename)

    def process_rag_only(
        self,
        markdown_content: str,
        doc_name: str,
        doc_id: str
    ) -> RAGProcessResult:
        """
        仅执行RAG预处理
        """
        return self.rag_processor.process(markdown_content, doc_name, doc_id)


document_service = DocumentService()
