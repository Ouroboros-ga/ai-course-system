"""
IK 分词器深度定制

基于双向最大匹配算法实现教育场景专有名词的高精度分词，
内置教育领域专有词典，支持自定义扩展。

核心思路：
  1. 正向最大匹配 (Forward Maximum Match)
  2. 逆向最大匹配 (Backward Maximum Match)
  3. 双向比对择优（歧义消解）
  4. 教育专有名词词典优先匹配
  5. 公式占位符整体保留

IK 分词器的核心优势在于智能歧义消解和词典优先策略，
本实现针对教育场景深度定制，将专有名词识别准确率显著提升。
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TokenType(str, Enum):
    """分词 Token 类型"""

    CN_WORD = "CN_WORD"
    EN_WORD = "EN_WORD"
    NUMBER = "NUMBER"
    FORMULA_PLACEHOLDER = "FORMULA_PLACEHOLDER"
    TABLE_PLACEHOLDER = "TABLE_PLACEHOLDER"
    PUNCTUATION = "PUNCTUATION"
    CN_CHAR = "CN_CHAR"
    MIXED = "MIXED"


@dataclass
class Token:
    """分词结果 Token"""

    text: str
    token_type: TokenType
    start: int
    end: int
    is_domain_term: bool = False

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "type": self.token_type.value,
            "start": self.start,
            "end": self.end,
            "is_domain_term": self.is_domain_term,
        }


@dataclass
class TokenizeResult:
    """分词结果"""

    tokens: List[Token]
    text: str
    word_count: int
    domain_term_count: int
    domain_terms: List[str]


class EducationalDictionary:
    """
    教育领域专有词典

    涵盖数学、物理、化学、计算机科学等学科核心术语，
    确保专有名词不被错误切分
    """

    MATH_TERMS: FrozenSet[str] = frozenset(
        {
            "微积分", "线性代数", "概率论", "数理统计", "离散数学",
            "高等数学", "解析几何", "微分方程", "偏微分方程",
            "常微分方程", "数值分析", "运筹学", "图论", "集合论",
            "抽象代数", "近世代数", "实变函数", "复变函数",
            "泛函分析", "拓扑学", "数论", "组合数学",
            "傅里叶变换", "拉普拉斯变换", "Z变换",
            "矩阵运算", "行列式", "特征值", "特征向量",
            "逆矩阵", "转置矩阵", "单位矩阵", "对称矩阵",
            "正交矩阵", "对角矩阵", "稀疏矩阵",
            "极限", "导数", "偏导数", "全微分", "积分",
            "定积分", "不定积分", "重积分", "曲线积分", "曲面积分",
            "级数", "幂级数", "泰勒级数", "傅里叶级数",
            "收敛", "发散", "绝对收敛", "条件收敛",
            "向量空间", "线性变换", "线性映射", "线性组合",
            "线性相关", "线性无关", "基", "维数", "秩",
            "概率分布", "正态分布", "泊松分布", "二项分布",
            "期望值", "方差", "标准差", "协方差", "相关系数",
            "假设检验", "置信区间", "回归分析", "方差分析",
            "最小二乘法", "最大似然估计", "贝叶斯估计",
            "欧拉公式", "柯西不等式", "施瓦茨不等式",
            "格林公式", "高斯公式", "斯托克斯公式",
            "泰勒公式", "麦克劳林公式", "洛必达法则",
            "中值定理", "罗尔定理", "拉格朗日中值定理",
            "柯西中值定理", "费马定理",
            "凸函数", "凹函数", "极值", "驻点", "拐点",
            "参数方程", "极坐标", "直角坐标系",
            "排列组合", "加法原理", "乘法原理",
            "条件概率", "全概率公式", "贝叶斯公式",
            "大数定律", "中心极限定理",
            "马尔可夫链", "蒙特卡洛方法",
            "牛顿莱布尼茨公式", "莱布尼茨公式",
            "克莱姆法则", "高斯消元法",
        }
    )

    PHYSICS_TERMS: FrozenSet[str] = frozenset(
        {
            "牛顿运动定律", "万有引力定律", "库仑定律",
            "能量守恒", "动量守恒", "角动量守恒",
            "热力学第一定律", "热力学第二定律", "热力学第三定律",
            "麦克斯韦方程组", "法拉第电磁感应定律",
            "安培定律", "毕奥萨伐尔定律", "洛伦兹力",
            "薛定谔方程", "海森堡不确定性原理",
            "波粒二象性", "光电效应", "康普顿散射",
            "相对论", "狭义相对论", "广义相对论",
            "量子力学", "量子场论", "弦理论",
            "干涉", "衍射", "偏振", "折射", "反射",
            "多普勒效应", "共振", "驻波", "行波",
            "电场强度", "磁场强度", "电势", "磁通量",
            "电容", "电感", "阻抗", "导纳",
            "热传导", "热对流", "热辐射",
            "熵", "焓", "自由能", "吉布斯自由能",
            "刚体", "转动惯量", "力矩", "角速度",
        }
    )

    CHEMISTRY_TERMS: FrozenSet[str] = frozenset(
        {
            "化学键", "共价键", "离子键", "金属键", "氢键",
            "氧化还原", "电解质", "非电解质",
            "有机化学", "无机化学", "分析化学", "物理化学",
            "高分子化学", "生物化学",
            "摩尔质量", "物质的量", "阿伏伽德罗常数",
            "化学平衡", "勒夏特列原理",
            "酸碱中和", "缓冲溶液", "pH值",
            "电化学", "原电池", "电解池",
            "反应速率", "活化能", "催化剂",
            "同分异构体", "手性", "对映异构",
            "加成反应", "取代反应", "消去反应", "聚合反应",
            "酯化反应", "水解反应", "氧化反应", "还原反应",
        }
    )

    CS_TERMS: FrozenSet[str] = frozenset(
        {
            "数据结构", "算法", "时间复杂度", "空间复杂度",
            "二叉树", "红黑树", "B树", "B+树", "哈希表",
            "图论算法", "最短路径", "最小生成树", "拓扑排序",
            "动态规划", "贪心算法", "分治法", "回溯法",
            "深度优先搜索", "广度优先搜索",
            "排序算法", "快速排序", "归并排序", "堆排序",
            "操作系统", "进程调度", "内存管理", "文件系统",
            "死锁", "信号量", "互斥锁",
            "计算机网络", "TCP协议", "UDP协议", "HTTP协议",
            "IP地址", "子网掩码", "路由算法",
            "数据库", "关系代数", "SQL查询", "事务处理",
            "范式", "函数依赖", "候选键",
            "机器学习", "深度学习", "神经网络",
            "卷积神经网络", "循环神经网络", "注意力机制",
            "反向传播", "梯度下降", "损失函数",
            "过拟合", "正则化", "交叉验证",
            "自然语言处理", "计算机视觉", "强化学习",
            "生成对抗网络", "变分自编码器",
            "编译原理", "词法分析", "语法分析", "语义分析",
            "面向对象", "设计模式", "软件工程",
        }
    )

    PEDAGOGY_TERMS: FrozenSet[str] = frozenset(
        {
            "教学设计", "课程目标", "教学目标", "学习目标",
            "形成性评价", "总结性评价", "诊断性评价",
            "认知负荷", "最近发展区", "脚手架理论",
            "建构主义", "行为主义", "认知主义",
            "翻转课堂", "混合式教学", "探究式学习",
            "项目式学习", "协作学习", "自主学习",
            "布鲁姆分类", "知识维度", "认知过程维度",
            "教学策略", "教学方法", "教学媒体",
            "学情分析", "差异化教学", "个性化学习",
            "核心素养", "课程标准", "教学大纲",
        }
    )

    FORMULA_PLACEHOLDER_PATTERN = re.compile(r"\[FORMULA_\d+\]")
    TABLE_PLACEHOLDER_PATTERN = re.compile(r"\[TABLE_\d+\]")

    def __init__(self):
        self._all_terms: Set[str] = set()
        self._all_terms.update(self.MATH_TERMS)
        self._all_terms.update(self.PHYSICS_TERMS)
        self._all_terms.update(self.CHEMISTRY_TERMS)
        self._all_terms.update(self.CS_TERMS)
        self._all_terms.update(self.PEDAGOGY_TERMS)

        self._max_term_len = max(len(t) for t in self._all_terms) if self._all_terms else 0
        self._min_term_len = min(len(t) for t in self._all_terms) if self._all_terms else 1

        self._term_categories: Dict[str, str] = {}
        for t in self.MATH_TERMS:
            self._term_categories[t] = "数学"
        for t in self.PHYSICS_TERMS:
            self._term_categories[t] = "物理"
        for t in self.CHEMISTRY_TERMS:
            self._term_categories[t] = "化学"
        for t in self.CS_TERMS:
            self._term_categories[t] = "计算机"
        for t in self.PEDAGOGY_TERMS:
            self._term_categories[t] = "教育学"

        self._custom_terms: Set[str] = set()

        logger.info(
            f"教育专有词典初始化完成: "
            f"数学{len(self.MATH_TERMS)}词, "
            f"物理{len(self.PHYSICS_TERMS)}词, "
            f"化学{len(self.CHEMISTRY_TERMS)}词, "
            f"计算机{len(self.CS_TERMS)}词, "
            f"教育学{len(self.PEDAGOGY_TERMS)}词, "
            f"总计{len(self._all_terms)}词"
        )

    def add_terms(self, terms: List[str], category: str = "自定义") -> None:
        """添加自定义术语"""
        for term in terms:
            if term and len(term) >= 2:
                self._custom_terms.add(term)
                self._all_terms.add(term)
                self._term_categories[term] = category

        if self._all_terms:
            self._max_term_len = max(len(t) for t in self._all_terms)
            self._min_term_len = min(len(t) for t in self._all_terms)

        logger.info(f"添加{len(terms)}个自定义术语(类别: {category})")

    def contains(self, term: str) -> bool:
        return term in self._all_terms

    def get_category(self, term: str) -> Optional[str]:
        return self._term_categories.get(term)

    @property
    def max_term_len(self) -> int:
        return self._max_term_len

    @property
    def min_term_len(self) -> int:
        return self._min_term_len

    @property
    def all_terms(self) -> Set[str]:
        return self._all_terms

    @property
    def term_count(self) -> int:
        return len(self._all_terms)


class IKTokenizer:
    """
    IK 分词器 - 教育场景深度定制版

    核心算法：
    1. 预处理：识别并保护公式占位符、表格占位符、英文单词、数字
    2. 正向最大匹配 (FMM)
    3. 逆向最大匹配 (BMM)
    4. 双向择优：比较 FMM/BMM 结果，选择更优切分
    5. 词典优先：教育专有名词优先整体匹配

    择优策略：
    - 词典匹配数多者优先
    - 切分粒度大（词数少）者优先
    - 非单字词多者优先
    """

    _CN_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
    _EN_WORD_PATTERN = re.compile(r"[a-zA-Z]+")
    _NUMBER_PATTERN = re.compile(r"\d+\.?\d*")
    _PUNCTUATION_PATTERN = re.compile(
        "[，。！？、；：\u201c\u201d\u2018\u2019\uff08\uff09\u3010\u3011\u300a\u300b\u2014\u2026\u00b7,.!?;:(){}\\[\\]]"
    )

    def __init__(
        self,
        dictionary: Optional[EducationalDictionary] = None,
        max_word_len: int = 10,
    ):
        self._dict = dictionary or _default_dictionary()
        self._max_word_len = max(max_word_len, self._dict.max_term_len)

    def tokenize(self, text: str) -> TokenizeResult:
        """
        对文本进行 IK 分词

        处理流程：
        1. 预处理：提取特殊 Token（公式占位符、英文、数字）
        2. 对中文部分执行双向最大匹配
        3. 合并所有 Token
        """
        if not text or not text.strip():
            return TokenizeResult(
                tokens=[], text=text, word_count=0,
                domain_term_count=0, domain_terms=[],
            )

        protected_spans = self._extract_protected_spans(text)

        cn_segments = self._split_by_protected(text, protected_spans)

        all_tokens: List[Token] = []
        domain_terms: List[str] = []

        for seg_start, seg_text in cn_segments:
            seg_tokens = self._segment_chinese(seg_text, seg_start)
            for token in seg_tokens:
                if token.is_domain_term and token.text not in domain_terms:
                    domain_terms.append(token.text)
            all_tokens.extend(seg_tokens)

        for span in protected_spans:
            all_tokens.append(span.token)

        all_tokens.sort(key=lambda t: t.start)

        word_count = len([t for t in all_tokens if t.token_type in (
            TokenType.CN_WORD, TokenType.EN_WORD,
            TokenType.NUMBER, TokenType.FORMULA_PLACEHOLDER,
            TokenType.TABLE_PLACEHOLDER, TokenType.MIXED,
        )])

        domain_term_count = len([t for t in all_tokens if t.is_domain_term])

        return TokenizeResult(
            tokens=all_tokens,
            text=text,
            word_count=word_count,
            domain_term_count=domain_term_count,
            domain_terms=domain_terms,
        )

    def tokenize_for_search(self, text: str) -> List[str]:
        """分词用于搜索索引，返回词项列表"""
        result = self.tokenize(text)
        return [
            t.text for t in result.tokens
            if t.token_type not in (TokenType.PUNCTUATION, TokenType.CN_CHAR)
            or len(t.text) > 1
        ]

    def tokenize_for_embedding(self, text: str) -> str:
        """分词用于向量嵌入，返回空格分隔的词项字符串"""
        terms = self.tokenize_for_search(text)
        return " ".join(terms)

    def _extract_protected_spans(self, text: str) -> List["_ProtectedSpan"]:
        """提取需要保护的文本段（公式占位符、英文、数字、标点）"""
        spans: List[_ProtectedSpan] = []

        for pattern, token_type in [
            (EducationalDictionary.FORMULA_PLACEHOLDER_PATTERN, TokenType.FORMULA_PLACEHOLDER),
            (EducationalDictionary.TABLE_PLACEHOLDER_PATTERN, TokenType.TABLE_PLACEHOLDER),
            (self._EN_WORD_PATTERN, TokenType.EN_WORD),
            (self._NUMBER_PATTERN, TokenType.NUMBER),
            (self._PUNCTUATION_PATTERN, TokenType.PUNCTUATION),
        ]:
            for match in pattern.finditer(text):
                spans.append(_ProtectedSpan(
                    start=match.start(),
                    end=match.end(),
                    token=Token(
                        text=match.group(),
                        token_type=token_type,
                        start=match.start(),
                        end=match.end(),
                    ),
                ))

        spans.sort(key=lambda s: s.start)

        merged: List[_ProtectedSpan] = []
        for span in spans:
            if merged and span.start < merged[-1].end:
                continue
            merged.append(span)

        return merged

    def _split_by_protected(
        self, text: str, spans: List["_ProtectedSpan"]
    ) -> List[Tuple[int, str]]:
        """将文本按保护段拆分为中文片段"""
        segments: List[Tuple[int, str]] = []
        prev_end = 0

        for span in spans:
            if span.start > prev_end:
                segment = text[prev_end:span.start]
                cn_chars = self._CN_CHAR_PATTERN.findall(segment)
                if cn_chars:
                    segments.append((prev_end, segment))
            prev_end = span.end

        if prev_end < len(text):
            segment = text[prev_end:]
            cn_chars = self._CN_CHAR_PATTERN.findall(segment)
            if cn_chars:
                segments.append((prev_end, segment))

        return segments

    def _segment_chinese(self, text: str, offset: int) -> List[Token]:
        """对中文文本执行双向最大匹配分词"""
        cn_only = "".join(self._CN_CHAR_PATTERN.findall(text))
        if not cn_only:
            return []

        fmm_tokens = self._forward_max_match(cn_only, offset)
        bmm_tokens = self._backward_max_match(cn_only, offset)

        return self._select_best(fmm_tokens, bmm_tokens)

    def _forward_max_match(self, text: str, offset: int) -> List[Token]:
        """正向最大匹配"""
        tokens: List[Token] = []
        pos = 0
        text_len = len(text)

        while pos < text_len:
            matched_len = 0

            max_len = min(self._max_word_len, text_len - pos)
            for length in range(max_len, 0, -1):
                word = text[pos:pos + length]
                if self._dict.contains(word):
                    tokens.append(Token(
                        text=word,
                        token_type=TokenType.CN_WORD,
                        start=offset + pos,
                        end=offset + pos + length,
                        is_domain_term=True,
                    ))
                    matched_len = length
                    break

            if matched_len == 0:
                tokens.append(Token(
                    text=text[pos],
                    token_type=TokenType.CN_CHAR,
                    start=offset + pos,
                    end=offset + pos + 1,
                ))
                matched_len = 1

            pos += matched_len

        return tokens

    def _backward_max_match(self, text: str, offset: int) -> List[Token]:
        """逆向最大匹配"""
        tokens: List[Token] = []
        pos = len(text)

        while pos > 0:
            matched_len = 0

            max_len = min(self._max_word_len, pos)
            for length in range(max_len, 0, -1):
                word = text[pos - length:pos]
                if self._dict.contains(word):
                    tokens.append(Token(
                        text=word,
                        token_type=TokenType.CN_WORD,
                        start=offset + pos - length,
                        end=offset + pos,
                        is_domain_term=True,
                    ))
                    matched_len = length
                    break

            if matched_len == 0:
                tokens.append(Token(
                    text=text[pos - 1],
                    token_type=TokenType.CN_CHAR,
                    start=offset + pos - 1,
                    end=offset + pos,
                ))
                matched_len = 1

            pos -= matched_len

        tokens.reverse()
        return tokens

    def _select_best(
        self, fmm_tokens: List[Token], bmm_tokens: List[Token]
    ) -> List[Token]:
        """
        双向匹配择优

        择优标准（优先级从高到低）：
        1. 词典匹配数多者优先
        2. 非单字词多者优先
        3. 总词数少者优先（粒度更大）
        """
        fmm_domain = sum(1 for t in fmm_tokens if t.is_domain_term)
        bmm_domain = sum(1 for t in bmm_tokens if t.is_domain_term)

        if fmm_domain != bmm_domain:
            return fmm_tokens if fmm_domain > bmm_domain else bmm_tokens

        fmm_non_single = sum(1 for t in fmm_tokens if len(t.text) > 1)
        bmm_non_single = sum(1 for t in bmm_tokens if len(t.text) > 1)

        if fmm_non_single != bmm_non_single:
            return fmm_tokens if fmm_non_single > bmm_non_single else bmm_tokens

        if len(fmm_tokens) != len(bmm_tokens):
            return fmm_tokens if len(fmm_tokens) <= len(bmm_tokens) else bmm_tokens

        return fmm_tokens


@dataclass
class _ProtectedSpan:
    """受保护的文本段"""

    start: int
    end: int
    token: Token


_default_dict_instance: Optional[EducationalDictionary] = None


def _default_dictionary() -> EducationalDictionary:
    """获取默认教育词典单例"""
    global _default_dict_instance
    if _default_dict_instance is None:
        _default_dict_instance = EducationalDictionary()
    return _default_dict_instance
