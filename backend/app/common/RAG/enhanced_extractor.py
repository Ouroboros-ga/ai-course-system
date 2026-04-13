"""
优化的统计专业名词提取器

针对材料力学领域优化，提高召回率和精确率
"""

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TermCandidate:
    """候选术语"""
    text: str
    frequency: int
    mutual_info: float
    left_entropy: float
    right_entropy: float
    tfidf_score: float
    c_value: float
    is_valid: bool = True
    invalid_reason: str = ""


class EnhancedStopWordsFilter:
    """增强的停用词和过滤规则"""
    
    COMMON_VERBS = {
        "是", "有", "在", "为", "对", "与", "及", "等", "或", "和",
        "可以", "能够", "应该", "需要", "必须", "可能", "将", "要",
        "进行", "通过", "使用", "采用", "应用", "利用", "实现",
        "得到", "获得", "求出", "计算", "分析", "研究", "讨论",
        "说明", "表示", "表明", "认为", "假设", "设", "令",
        "如图", "如图所示", "如下", "如下所示", "见", "参见",
        "如图中", "由图", "从图", "图中", "表中", "如表",
    }
    
    CONNECTIVES = {
        "因此", "所以", "但是", "然而", "而且", "并且", "或者",
        "如果", "那么", "因为", "由于", "虽然", "即使", "无论",
        "当", "时", "后", "前", "中", "上", "下", "内", "外",
        "之间", "以上", "以下", "之前", "之后", "之中", "其中",
        "首先", "然后", "最后", "其次", "再次", "最终",
        "一方面", "另一方面", "同时", "此时", "这时", "那时",
    }
    
    SINGLE_CHARS = {
        "的", "了", "和", "与", "或", "及", "等", "之", "所",
        "以", "为", "在", "于", "从", "到", "向", "往", "由",
        "被", "把", "将", "给", "让", "叫", "使", "令",
        "这", "那", "此", "彼", "该", "其", "各", "每",
        "某", "任", "何", "凡", "全", "总", "共", "仅",
        "只", "才", "就", "便", "又", "再", "也", "还",
        "都", "均", "即", "则", "却", "仍", "已", "曾",
        "将", "要", "会", "能", "可", "应", "须", "必",
    }
    
    FRAGMENT_PATTERNS = [
        r'^[\u4e00-\u9fff]{1}$',  # 单个汉字
        r'^[0-9]+$',  # 纯数字
        r'^[a-zA-Z]$',  # 单个字母
        r'^第[一二三四五六七八九十百千万]+',  # 第X章/节
        r'.*[的得地]$',  # 以"的得地"结尾
        r'^[一二三四五六七八九十]+',  # 以数字开头
        r'.*[了着过]$',  # 以时态助词结尾
        r'^[当在从向往由]',  # 以介词开头
        r'.*[吗呢吧啊呀]',  # 以语气词结尾
        r'^为[一二三四五六七八九十两]',  # "为一"、"为两"等
        r'^与[横轴截]',  # "与横"、"与轴"等
        r'^[上下左右内外]侧$',  # "上侧"、"下侧"等
        r'^[上下左右内外]的',  # "上的"、"下的"等
        r'.*[的][\u4e00-\u9fff]{1,2}$',  # "的X"、"的XX"
        r'^[\u4e00-\u9fff]{1,2}的',  # "X的"、"XX的"
        r'^为[正负大小]',  # "为正"、"为负"等
        r'^[两个几根]',  # "两"、"个"等开头
        r'.*[且仍]',  # 包含"且仍"
        r'^[什么为什么]',  # 疑问词开头
    ]
    
    MATERIAL_MECHANICS_STOPWORDS = {
        "如图所示", "如图中", "由图可知", "从图中", "图中所示",
        "如表所示", "如表中", "由表可知", "从表中", "表中所示",
        "可以看出", "可以看出", "由此可见", "由此可知",
        "一般来说", "通常情况下", "一般情况下", "在实际中",
        "在本章中", "在本节中", "在本章", "在本节",
        "综上所述", "总而言之", "简而言之", "概括来说",
        "不变", "不同", "两个", "两杆", "两根", "两端",
        "问题", "关系", "规律", "称为", "金属", "晶体",
    }
    
    MATERIAL_MECHANICS_FRAGMENT_RULES = {
        "横截": "横截面",
        "正应": "正应力",
        "切应": "切应力",
        "中性": "中性轴",
        "纯弯": "纯弯曲",
        "弯曲时": "纯弯曲",
        "力分": "力分布",
        "应力分": "应力分布",
        "轴力图": "轴力图",
        "应力计": "应力计算",
    }
    
    @classmethod
    def is_stopword(cls, term: str) -> Tuple[bool, str]:
        """判断是否为停用词"""
        if not term or len(term.strip()) == 0:
            return True, "空词"
        
        term = term.strip()
        
        if term in cls.SINGLE_CHARS:
            return True, "单字停用词"
        
        if term in cls.COMMON_VERBS:
            return True, "常见动词"
        
        if term in cls.CONNECTIVES:
            return True, "接续词"
        
        if term in cls.MATERIAL_MECHANICS_STOPWORDS:
            return True, "材料力学停用词"
        
        for pattern in cls.FRAGMENT_PATTERNS:
            if re.match(pattern, term):
                return True, f"匹配过滤模式: {pattern}"
        
        if term in cls.MATERIAL_MECHANICS_FRAGMENT_RULES:
            longer = cls.MATERIAL_MECHANICS_FRAGMENT_RULES[term]
            return True, f"片段术语，完整形式: {longer}"
        
        return False, ""
    
    @classmethod
    def is_fragment(cls, term: str, all_terms: Set[str]) -> bool:
        """判断是否为片段（是否是更长术语的子串）"""
        if len(term) < 2:
            return False
        
        for other_term in all_terms:
            if other_term != term and term in other_term:
                return True
        
        return False


class EnhancedStatisticalTermExtractor:
    """增强的统计专业名词提取器"""
    
    def __init__(
        self,
        min_freq: int = 2,
        min_mutual_info: float = 2.0,
        min_entropy: float = 0.8,
        max_term_len: int = 8,
        min_term_len: int = 2,
    ):
        self.min_freq = min_freq
        self.min_mutual_info = min_mutual_info
        self.min_entropy = min_entropy
        self.max_term_len = max_term_len
        self.min_term_len = min_term_len
        
        self._char_freq: Counter = Counter()
        self._bigram_freq: Counter = Counter()
        self._term_candidates: Dict[str, TermCandidate] = {}
        self._left_context: Dict[str, Counter] = defaultdict(Counter)
        self._right_context: Dict[str, Counter] = defaultdict(Counter)
        
    def extract_from_texts(self, texts: List[str]) -> List[TermCandidate]:
        """从文本列表中提取专业名词"""
        logger.info(f"开始从 {len(texts)} 个文本中提取专业名词")
        
        logger.info("步骤1: 统计字频和双字频...")
        self._collect_statistics(texts)
        
        logger.info("步骤2: 生成候选术语...")
        self._generate_candidates(texts)
        
        logger.info("步骤3: 计算统计指标...")
        self._calculate_metrics()
        
        logger.info("步骤4: 应用过滤规则...")
        valid_candidates = self._apply_filters()
        
        logger.info("步骤5: 去除片段术语...")
        valid_candidates = self._remove_fragments(valid_candidates)
        
        logger.info(f"提取完成，共 {len(valid_candidates)} 个有效候选术语")
        return valid_candidates
    
    def _collect_statistics(self, texts: List[str]) -> None:
        """收集统计信息"""
        for text in texts:
            cn_chars = re.findall(r'[\u4e00-\u9fff]+', text)
            for segment in cn_chars:
                for i, char in enumerate(segment):
                    self._char_freq[char] += 1
                    
                    if i < len(segment) - 1:
                        bigram = segment[i:i+2]
                        self._bigram_freq[bigram] += 1
    
    def _generate_candidates(self, texts: List[str]) -> None:
        """生成候选术语"""
        term_freq: Counter = Counter()
        
        for text in texts:
            cn_segments = re.findall(r'[\u4e00-\u9fff]+', text)
            for segment in cn_segments:
                for length in range(self.min_term_len, min(self.max_term_len + 1, len(segment) + 1)):
                    for i in range(len(segment) - length + 1):
                        term = segment[i:i+length]
                        term_freq[term] += 1
                        
                        if i > 0:
                            left_char = segment[i-1]
                            self._left_context[term][left_char] += 1
                        
                        if i + length < len(segment):
                            right_char = segment[i+length]
                            self._right_context[term][right_char] += 1
        
        for term, freq in term_freq.items():
            if freq >= self.min_freq:
                self._term_candidates[term] = TermCandidate(
                    text=term,
                    frequency=freq,
                    mutual_info=0.0,
                    left_entropy=0.0,
                    right_entropy=0.0,
                    tfidf_score=0.0,
                    c_value=0.0,
                )
    
    def _calculate_metrics(self) -> None:
        """计算统计指标"""
        total_chars = sum(self._char_freq.values())
        
        for term, candidate in self._term_candidates.items():
            candidate.mutual_info = self._calculate_mutual_info(term)
            candidate.left_entropy = self._calculate_entropy(self._left_context[term])
            candidate.right_entropy = self._calculate_entropy(self._right_context[term])
            candidate.tfidf_score = self._calculate_tfidf(term, candidate.frequency)
            candidate.c_value = self._calculate_c_value(term, candidate.frequency)
    
    def _calculate_mutual_info(self, term: str) -> float:
        """计算互信息"""
        if len(term) < 2:
            return 0.0
        
        total_chars = sum(self._char_freq.values())
        if total_chars == 0:
            return 0.0
        
        term_freq = self._bigram_freq.get(term[:2], 0)
        if term_freq == 0:
            return 0.0
        
        p_term = term_freq / total_chars
        
        p_char1 = self._char_freq.get(term[0], 0) / total_chars
        p_char2 = self._char_freq.get(term[1], 0) / total_chars
        
        if p_char1 == 0 or p_char2 == 0:
            return 0.0
        
        import math
        return math.log2(p_term / (p_char1 * p_char2)) if p_term > 0 else 0.0
    
    def _calculate_entropy(self, context: Counter) -> float:
        """计算熵"""
        if not context:
            return 0.0
        
        total = sum(context.values())
        if total == 0:
            return 0.0
        
        import math
        entropy = 0.0
        for count in context.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        
        return entropy
    
    def _calculate_tfidf(self, term: str, freq: int) -> float:
        """计算TF-IDF（简化版）"""
        import math
        tf = freq
        idf = 1.0
        return tf * idf
    
    def _calculate_c_value(self, term: str, freq: int) -> float:
        """计算C-value"""
        longer_terms = [
            t for t in self._term_candidates.keys()
            if term in t and t != term
        ]
        
        if not longer_terms:
            import math
            return math.log2(len(term)) * freq
        
        import math
        longer_freq = sum(self._term_candidates[t].frequency for t in longer_terms)
        c_value = math.log2(len(term)) * (freq - longer_freq / len(longer_terms))
        
        return max(0, c_value)
    
    def _apply_filters(self) -> List[TermCandidate]:
        """应用过滤规则"""
        valid_candidates = []
        
        for term, candidate in self._term_candidates.items():
            is_stop, reason = EnhancedStopWordsFilter.is_stopword(term)
            if is_stop:
                candidate.is_valid = False
                candidate.invalid_reason = reason
                continue
            
            if candidate.mutual_info < self.min_mutual_info:
                candidate.is_valid = False
                candidate.invalid_reason = f"互信息过低: {candidate.mutual_info:.2f}"
                continue
            
            avg_entropy = (candidate.left_entropy + candidate.right_entropy) / 2
            if avg_entropy < self.min_entropy:
                candidate.is_valid = False
                candidate.invalid_reason = f"平均熵过低: {avg_entropy:.2f}"
                continue
            
            valid_candidates.append(candidate)
        
        valid_candidates.sort(key=lambda c: c.frequency, reverse=True)
        return valid_candidates
    
    def _remove_fragments(self, candidates: List[TermCandidate]) -> List[TermCandidate]:
        """去除片段术语"""
        all_terms = {c.text for c in candidates}
        non_fragment_candidates = []
        
        for candidate in candidates:
            if not EnhancedStopWordsFilter.is_fragment(candidate.text, all_terms):
                non_fragment_candidates.append(candidate)
            else:
                candidate.is_valid = False
                candidate.invalid_reason = "片段术语"
        
        return non_fragment_candidates
    
    def get_top_terms(self, n: int = 100) -> List[str]:
        """获取Top N术语"""
        valid = [c for c in self._term_candidates.values() if c.is_valid]
        valid.sort(key=lambda c: c.frequency, reverse=True)
        return [c.text for c in valid[:n]]
