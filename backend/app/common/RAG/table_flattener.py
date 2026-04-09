"""
表格展平算法

针对 Docling 生成的 Markdown 文件中的表格进行展平处理，
将结构化的 Markdown 表格转换为自然语言描述，
使分词器和向量检索能更好地理解表格内容。

核心思路：
  1. 解析 Markdown 表格（含多级表头、合并单元格）
  2. 展平策略：
     - 多级表头 → 级联路径描述（如"成绩/语文/期中"）
     - 合并单元格 → 上下文继承填充
     - 整表 → 结构化自然语言描述
  3. 保留原始表格的语义关系，生成适合 RAG 检索的文本
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TableCell:
    """表格单元格"""

    text: str
    row_idx: int
    col_idx: int
    is_header: bool = False
    row_span: int = 1
    col_span: int = 1


@dataclass
class ParsedTable:
    """解析后的表格结构"""

    headers: List[List[str]]
    rows: List[List[str]]
    caption: Optional[str] = None
    raw_markdown: str = ""
    row_count: int = 0
    col_count: int = 0
    has_multi_header: bool = False


@dataclass
class FlattenResult:
    """展平结果"""

    original_table: str
    flattened_text: str
    structured_desc: str
    key_value_pairs: List[Dict[str, str]]
    table_summary: str


class MarkdownTableParser:
    """
    Markdown 表格解析器

    解析 Docling 输出的标准 Markdown 表格格式，
    支持多级表头和合并单元格的识别
    """

    _TABLE_PATTERN = re.compile(
        r"((?:^[ \t]*\|?.+\|[ \t]*$\n?)+)",
        re.MULTILINE,
    )

    _SEPARATOR_PATTERN = re.compile(
        r"^\|?[\s:-]+(\|[\s:-]+)*\|?\s*$",
        re.MULTILINE,
    )

    _CAPTION_PATTERN = re.compile(
        r"(?:^|\n)(?:表\s*\d*[\.:：]\s*|.+:)\s*(.+?)(?:\n|$)",
    )

    @classmethod
    def parse_tables(cls, markdown_text: str) -> List[ParsedTable]:
        """
        从 Markdown 文本中提取并解析所有表格
        """
        tables = []
        table_blocks = cls._split_table_blocks(markdown_text)

        for block in table_blocks:
            parsed = cls._parse_single_table(block)
            if parsed and parsed.row_count > 0:
                tables.append(parsed)

        logger.info(f"表格解析完成: 共发现 {len(tables)} 个表格")
        return tables

    @classmethod
    def _split_table_blocks(cls, text: str) -> List[str]:
        """将文本拆分为独立的表格块"""
        blocks = []
        lines = text.split("\n")
        current_block: List[str] = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            is_table_line = stripped.startswith("|") and stripped.endswith("|")
            is_separator = bool(cls._SEPARATOR_PATTERN.match(stripped))

            if is_table_line or is_separator:
                current_block.append(line)
                in_table = True
            elif in_table and not stripped:
                if current_block:
                    blocks.append("\n".join(current_block))
                    current_block = []
                in_table = False
            elif in_table and stripped:
                current_block.append(line)
            else:
                if current_block:
                    blocks.append("\n".join(current_block))
                    current_block = []
                in_table = False

        if current_block:
            blocks.append("\n".join(current_block))

        return blocks

    @classmethod
    def _parse_single_table(cls, block: str) -> Optional[ParsedTable]:
        """解析单个表格块"""
        lines = block.strip().split("\n")
        data_lines = []

        for line in lines:
            stripped = line.strip()
            if cls._SEPARATOR_PATTERN.match(stripped):
                continue
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = cls._parse_row(stripped)
                data_lines.append(cells)

        if not data_lines:
            return None

        caption = cls._extract_caption(block)

        header_rows = []
        body_rows = []

        if len(data_lines) >= 1:
            header_rows.append(data_lines[0])

        if len(data_lines) > 1:
            body_rows = data_lines[1:]

        col_count = max(len(row) for row in data_lines) if data_lines else 0
        has_multi = len(header_rows) > 1

        return ParsedTable(
            headers=header_rows,
            rows=body_rows,
            caption=caption,
            raw_markdown=block,
            row_count=len(body_rows),
            col_count=col_count,
            has_multi_header=has_multi,
        )

    @classmethod
    def _parse_row(cls, line: str) -> List[str]:
        """解析表格行，提取单元格文本"""
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]

        cells = line.split("|")
        return [cell.strip() for cell in cells]

    @classmethod
    def _extract_caption(cls, block: str) -> Optional[str]:
        """提取表格标题"""
        match = cls._CAPTION_PATTERN.search(block)
        if match:
            return match.group(1).strip()
        return None


class TableFlattener:
    """
    表格展平器

    将结构化表格转换为多种自然语言表示形式，
    适配不同的 RAG 检索场景
    """

    def __init__(
        self,
        max_row_desc: int = 50,
        include_summary: bool = True,
        cascade_header: bool = True,
    ):
        self._max_row_desc = max_row_desc
        self._include_summary = include_summary
        self._cascade_header = cascade_header

    def flatten_table(self, table: ParsedTable) -> FlattenResult:
        """
        展平单个表格，生成多种文本表示
        """
        key_value_pairs = self._extract_key_value_pairs(table)
        flattened_text = self._generate_flattened_text(table, key_value_pairs)
        structured_desc = self._generate_structured_desc(table)
        summary = self._generate_summary(table) if self._include_summary else ""

        return FlattenResult(
            original_table=table.raw_markdown,
            flattened_text=flattened_text,
            structured_desc=structured_desc,
            key_value_pairs=key_value_pairs,
            table_summary=summary,
        )

    def flatten_all(self, markdown_text: str) -> List[FlattenResult]:
        """
        展平 Markdown 文本中的所有表格
        """
        tables = MarkdownTableParser.parse_tables(markdown_text)
        results = [self.flatten_table(t) for t in tables]
        logger.info(f"表格展平完成: 共处理 {len(results)} 个表格")
        return results

    def replace_tables_in_text(self, markdown_text: str) -> str:
        """
        将 Markdown 文本中的表格替换为展平后的自然语言描述
        """
        tables = MarkdownTableParser.parse_tables(markdown_text)
        if not tables:
            return markdown_text

        result = markdown_text
        for table in reversed(tables):
            flatten_result = self.flatten_table(table)
            replacement = self._build_replacement(flatten_result)
            result = result.replace(table.raw_markdown, replacement)

        return result

    def _extract_key_value_pairs(
        self, table: ParsedTable
    ) -> List[Dict[str, str]]:
        """
        提取表格的键值对表示

        将每行数据与表头组合，生成"属性-值"对列表
        """
        if not table.headers or not table.rows:
            return []

        header = table.headers[0]
        pairs = []

        for row in table.rows:
            row_pair = {}
            for i, cell in enumerate(row):
                if i < len(header):
                    key = self._cascade_header_path(table.headers, i)
                    row_pair[key] = cell
                else:
                    row_pair[f"列{i+1}"] = cell
            pairs.append(row_pair)

        return pairs

    def _cascade_header_path(
        self, headers: List[List[str]], col_idx: int
    ) -> str:
        """
        生成多级表头的级联路径

        例如: ["成绩", "语文", "期中"] → "成绩/语文/期中"
        """
        if not self._cascade_header or len(headers) <= 1:
            if col_idx < len(headers[0]):
                return headers[0][col_idx]
            return f"列{col_idx+1}"

        path_parts = []
        for header_level in headers:
            if col_idx < len(header_level) and header_level[col_idx].strip():
                path_parts.append(header_level[col_idx].strip())

        return "/".join(path_parts) if path_parts else f"列{col_idx+1}"

    def _generate_flattened_text(
        self,
        table: ParsedTable,
        key_value_pairs: List[Dict[str, str]],
    ) -> str:
        """
        生成展平的自然语言描述

        将表格转换为"表头: 值"的句子列表
        """
        lines = []

        if table.caption:
            lines.append(f"表格: {table.caption}")

        for i, pair in enumerate(key_value_pairs[: self._max_row_desc]):
            parts = [f"{k}是{v}" for k, v in pair.items() if v.strip()]
            if parts:
                lines.append(f"第{i+1}行: {', '.join(parts)}")

        return "\n".join(lines)

    def _generate_structured_desc(self, table: ParsedTable) -> str:
        """
        生成结构化描述

        保留表格的层次结构信息，适合精确检索
        """
        parts = []

        if table.caption:
            parts.append(f"[表格标题: {table.caption}]")

        if table.headers:
            header_text = " | ".join(table.headers[0])
            parts.append(f"表头: {header_text}")

        if table.has_multi_header:
            for i, h in enumerate(table.headers[1:], 1):
                parts.append(f"二级表头: {' | '.join(h)}")

        parts.append(f"数据: {table.row_count}行 × {table.col_count}列")

        if table.rows:
            sample_row = table.rows[0]
            sample_text = " | ".join(sample_row)
            parts.append(f"首行数据: {sample_text}")

        return "\n".join(parts)

    def _generate_summary(self, table: ParsedTable) -> str:
        """
        生成表格摘要

        用简洁的自然语言概括表格内容
        """
        parts = []

        if table.caption:
            parts.append(f"关于{table.caption}的表格")
        else:
            parts.append("数据表格")

        if table.headers and table.headers[0]:
            header_names = [h for h in table.headers[0] if h.strip()]
            if header_names:
                parts.append(f"包含字段: {'、'.join(header_names[:5])}")

        parts.append(f"共{table.row_count}条数据记录")

        return "，".join(parts) + "。"

    def _build_replacement(self, result: FlattenResult) -> str:
        """构建表格替换文本"""
        parts = []

        if result.table_summary:
            parts.append(f"[表格摘要] {result.table_summary}")

        if result.structured_desc:
            parts.append(f"[结构信息] {result.structured_desc}")

        if result.flattened_text:
            parts.append(f"[详细数据]\n{result.flattened_text}")

        return "\n\n".join(parts)
