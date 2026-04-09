"""
公式占位替换算法

针对 Docling 生成的 Markdown 文件中的 LaTeX 公式进行占位替换，
将行内公式 ($...$) 和块级公式 ($$...$$) 替换为语义化占位符，
避免公式符号干扰分词器和向量检索，同时保留公式的语义信息。

核心思路：
  1. 识别 Markdown 中的 LaTeX 公式（行内 / 块级）
  2. 为每个公式生成唯一占位符 [FORMULA_N]，并提取公式语义描述
  3. 替换原文中的公式为占位符 + 语义描述
  4. 维护占位符映射表，支持公式还原
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FormulaInfo:
    """公式信息记录"""

    placeholder: str
    original_latex: str
    formula_type: str
    semantic_desc: str
    position: int


@dataclass
class FormulaReplaceResult:
    """公式替换结果"""

    processed_text: str
    formula_map: Dict[str, FormulaInfo]
    formula_count: int
    inline_count: int
    block_count: int


class FormulaPlaceholderReplacer:
    """
    公式占位替换器

    针对 Docling 输出的 Markdown 特性，处理以下公式格式：
    - 块级公式: $$...$$ 或 \\[...\\]
    - 行内公式: $...$ 或 \\(...\\)
    - Docling 特有的公式标注格式
    """

    _BLOCK_FORMULA_PATTERN = re.compile(
        r"\$\$\s*([\s\S]*?)\s*\$\$"
        r"|"
        r"\\\\\[\s*([\s\S]*?)\s*\\\\\]",
        re.MULTILINE,
    )

    _INLINE_FORMULA_PATTERN = re.compile(
        r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)"
        r"|"
        r"\\\\\(\s*(.+?)\s*\\\\\)",
    )

    _DOCLING_FORMULA_PATTERN = re.compile(
        r"<!-- \[FORMULA\]([\s\S]*?)-->"
        r"|"
        r"\[formula:([^\]]+)\]",
        re.IGNORECASE,
    )

    _COMMON_MATH_SYMBOLS = {
        r"\int": "积分",
        r"\sum": "求和",
        r"\prod": "连乘",
        r"\lim": "极限",
        r"\frac": "分式",
        r"\sqrt": "开方",
        r"\sin": "正弦",
        r"\cos": "余弦",
        r"\tan": "正切",
        r"\log": "对数",
        r"\ln": "自然对数",
        r"\exp": "指数",
        r"\partial": "偏导",
        r"\nabla": "梯度",
        r"\infty": "无穷",
        r"\alpha": "alpha",
        r"\beta": "beta",
        r"\gamma": "gamma",
        r"\delta": "delta",
        r"\epsilon": "epsilon",
        r"\theta": "theta",
        r"\lambda": "lambda",
        r"\mu": "mu",
        r"\sigma": "sigma",
        r"\omega": "omega",
        r"\phi": "phi",
        r"\psi": "psi",
        r"\rightarrow": "右箭头",
        r"\leftarrow": "左箭头",
        r"\Rightarrow": "推出",
        r"\Leftrightarrow": "等价",
        r"\leq": "小于等于",
        r"\geq": "大于等于",
        r"\neq": "不等于",
        r"\approx": "约等于",
        r"\equiv": "恒等于",
        r"\in": "属于",
        r"\subset": "子集",
        r"\cup": "并集",
        r"\cap": "交集",
        r"\forall": "任意",
        r"\exists": "存在",
        r"\mathbb": "数集",
        r"\mathbf": "向量",
        r"\hat": "帽子",
        r"\bar": "横线",
        r"\tilde": "波浪",
        r"\dot": "点",
        r"\ddot": "双点",
        r"\vec": "向量",
        r"\binom": "组合数",
        r"\det": "行列式",
        r"\max": "最大值",
        r"\min": "最小值",
        r"\sup": "上确界",
        r"\inf": "下确界",
    }

    _FORMULA_TYPE_KEYWORDS = {
        "积分公式": [r"\int", r"\iint", r"\iiint", r"\oint"],
        "求和公式": [r"\sum"],
        "极限公式": [r"\lim"],
        "微分方程": [r"\frac{d", r"\frac{\partial", r"\dot", r"\ddot"],
        "矩阵公式": [r"\begin{matrix", r"\begin{pmatrix", r"\begin{bmatrix", r"\begin{vmatrix"],
        "概率公式": [r"P(", r"\Pr", r"\mathbb{E}", r"\mathbb{P}"],
        "三角函数": [r"\sin", r"\cos", r"\tan", r"\cot", r"\sec", r"\csc"],
        "对数公式": [r"\log", r"\ln"],
        "级数公式": [r"\sum", r"\prod", r"\bigcup", r"\bigcap"],
        "集合运算": [r"\cup", r"\cap", r"\setminus", r"\subset", r"\in"],
        "向量运算": [r"\vec", r"\mathbf", r"\hat", r"\overrightarrow"],
    }

    def __init__(self, placeholder_prefix: str = "FORMULA"):
        self._placeholder_prefix = placeholder_prefix
        self._counter = 0

    def _next_placeholder(self) -> str:
        self._counter += 1
        return f"[{self._placeholder_prefix}_{self._counter:03d}]"

    def _extract_semantic_desc(self, latex: str) -> str:
        """
        从 LaTeX 公式中提取语义描述

        通过识别公式中的数学符号和结构，生成自然语言描述，
        使占位符在分词和检索时具有语义信息
        """
        descriptions = []

        for desc, keywords in self._FORMULA_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in latex:
                    descriptions.append(desc)
                    break

        symbol_descs = []
        for symbol, desc in self._COMMON_MATH_SYMBOLS.items():
            if symbol in latex:
                symbol_descs.append(desc)

        if descriptions:
            type_str = "/".join(descriptions[:3])
            if symbol_descs:
                return f"{type_str}({','.join(symbol_descs[:5])})"
            return type_str

        if symbol_descs:
            return ",".join(symbol_descs[:5])

        clean = re.sub(r"[{}\\_^&%$#~]", " ", latex)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) > 30:
            clean = clean[:30] + "..."
        return clean if clean else "数学表达式"

    def _replace_block_formulas(
        self, text: str, formula_map: Dict[str, FormulaInfo]
    ) -> Tuple[str, int]:
        """替换块级公式"""
        count = 0

        def _replacer(match: re.Match) -> str:
            nonlocal count
            latex = match.group(1) or match.group(2) or ""
            latex = latex.strip()
            if not latex:
                return match.group(0)

            placeholder = self._next_placeholder()
            semantic_desc = self._extract_semantic_desc(latex)
            pos = match.start()

            formula_map[placeholder] = FormulaInfo(
                placeholder=placeholder,
                original_latex=latex,
                formula_type="block",
                semantic_desc=semantic_desc,
                position=pos,
            )
            count += 1

            return f"\n{placeholder}[{semantic_desc}]\n"

        result = self._BLOCK_FORMULA_PATTERN.sub(_replacer, text)
        return result, count

    def _replace_inline_formulas(
        self, text: str, formula_map: Dict[str, FormulaInfo]
    ) -> Tuple[str, int]:
        """替换行内公式"""
        count = 0

        def _replacer(match: re.Match) -> str:
            nonlocal count
            latex = match.group(1) or match.group(2) or ""
            latex = latex.strip()
            if not latex:
                return match.group(0)

            placeholder = self._next_placeholder()
            semantic_desc = self._extract_semantic_desc(latex)
            pos = match.start()

            formula_map[placeholder] = FormulaInfo(
                placeholder=placeholder,
                original_latex=latex,
                formula_type="inline",
                semantic_desc=semantic_desc,
                position=pos,
            )
            count += 1

            return f"{placeholder}[{semantic_desc}]"

        result = self._INLINE_FORMULA_PATTERN.sub(_replacer, text)
        return result, count

    def _replace_docling_formulas(
        self, text: str, formula_map: Dict[str, FormulaInfo]
    ) -> Tuple[str, int]:
        """替换 Docling 特有公式标注"""
        count = 0

        def _replacer(match: re.Match) -> str:
            nonlocal count
            latex = match.group(1) or match.group(2) or ""
            latex = latex.strip()
            if not latex:
                return match.group(0)

            placeholder = self._next_placeholder()
            semantic_desc = self._extract_semantic_desc(latex)
            pos = match.start()

            formula_map[placeholder] = FormulaInfo(
                placeholder=placeholder,
                original_latex=latex,
                formula_type="docling_annotated",
                semantic_desc=semantic_desc,
                position=pos,
            )
            count += 1

            return f"{placeholder}[{semantic_desc}]"

        result = self._DOCLING_FORMULA_PATTERN.sub(_replacer, text)
        return result, count

    def replace(self, markdown_text: str) -> FormulaReplaceResult:
        """
        对 Markdown 文本执行公式占位替换

        替换顺序：Docling标注 → 块级公式 → 行内公式
        先替换长模式避免误匹配
        """
        self._counter = 0
        formula_map: Dict[str, FormulaInfo] = {}

        text = markdown_text

        text, docling_count = self._replace_docling_formulas(text, formula_map)
        text, block_count = self._replace_block_formulas(text, formula_map)
        text, inline_count = self._replace_inline_formulas(text, formula_map)

        total = docling_count + block_count + inline_count

        logger.info(
            f"公式占位替换完成: 共{total}个公式 "
            f"(块级:{block_count}, 行内:{inline_count}, Docling标注:{docling_count})"
        )

        return FormulaReplaceResult(
            processed_text=text,
            formula_map=formula_map,
            formula_count=total,
            inline_count=inline_count,
            block_count=block_count + docling_count,
        )

    def restore(self, processed_text: str, formula_map: Dict[str, FormulaInfo]) -> str:
        """
        将占位符还原为原始 LaTeX 公式
        """
        result = processed_text
        for placeholder, info in formula_map.items():
            if info.formula_type == "block" or info.formula_type == "docling_annotated":
                original = f"$${info.original_latex}$$"
            else:
                original = f"${info.original_latex}$"
            result = result.replace(f"{placeholder}[{info.semantic_desc}]", original)
            result = result.replace(placeholder, original)
        return result

    def get_formula_summary(self, formula_map: Dict[str, FormulaInfo]) -> List[Dict]:
        """
        生成公式摘要列表，用于 RAG 检索时的元数据
        """
        summary = []
        for placeholder, info in formula_map.items():
            summary.append(
                {
                    "placeholder": placeholder,
                    "type": info.formula_type,
                    "semantic_desc": info.semantic_desc,
                    "latex_preview": (
                        info.original_latex[:50] + "..."
                        if len(info.original_latex) > 50
                        else info.original_latex
                    ),
                }
            )
        return summary
