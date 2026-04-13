"""
混合策略专业名词提取器

结合基础版本和优化版本的优势：
1. 使用基础版本提取所有候选术语
2. 应用白名单保护关键术语
3. 使用动态阈值调整
4. 应用优化版本过滤低质量术语
5. 合并并排序最终结果
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
    score: float = 0.0


class HybridStopWordsFilter:
    """混合策略停用词过滤器"""
    
    COMMON_VERBS = {
        "是", "有", "在", "为", "对", "与", "及", "等", "或", "和",
        "可以", "能够", "应该", "需要", "必须", "可能", "将", "要",
        "进行", "通过", "使用", "采用", "应用", "利用", "实现",
        "得到", "获得", "求出", "计算", "分析", "研究", "讨论",
        "说明", "表示", "表明", "认为", "假设", "设", "令",
    }
    
    CONNECTIVES = {
        "因此", "所以", "但是", "然而", "而且", "并且", "或者",
        "如果", "那么", "因为", "由于", "虽然", "即使", "无论",
        "当", "时", "后", "前", "中", "上", "下", "内", "外",
        "之间", "以上", "以下", "之前", "之后", "之中", "其中",
        "首先", "然后", "最后", "其次", "再次", "最终",
    }
    
    SINGLE_CHARS = {
        "的", "了", "和", "与", "或", "及", "等", "之", "所",
        "以", "为", "在", "于", "从", "到", "向", "往", "由",
        "被", "把", "将", "给", "让", "叫", "使", "令",
        "这", "那", "此", "彼", "该", "其", "各", "每",
    }
    
    MATERIAL_MECHANICS_WHITELIST = {
        "应力", "应变", "弯矩", "扭矩", "轴力", "剪力",
        "横截面", "正应力", "切应力", "中性轴", "中性层",
        "惯性矩", "极惯性矩", "截面模量", "静矩", "形心",
        "挠度", "转角", "扭转角", "弹性模量", "泊松比",
        "屈服强度", "抗拉强度", "许用应力", "工作应力",
        "安全系数", "强度理论", "屈服准则", "破坏准则",
        "应力集中", "应力集中系数", "应力分布", "应力状态",
        "主应力", "最大应力", "最小应力", "主平面", "主方向",
        "应力圆", "莫尔圆", "应变能", "比能",
        "胡克定律", "剪切胡克定律", "圣维南原理",
        "拉伸", "压缩", "弯曲", "扭转", "剪切", "变形",
        "梁", "柱", "板", "壳", "轴", "杆",
        "截面", "纵截面", "斜截面",
        "弹性变形", "塑性变形", "残余变形",
        "弹性极限", "比例极限", "屈服极限",
        "疲劳", "疲劳强度", "疲劳极限",
        "断裂力学", "裂纹", "应力强度因子",
        "压杆稳定", "临界力", "临界应力",
        "欧拉公式", "长度系数", "柔度",
        "惯性半径", "形心轴",
        "弯曲正应力", "弯曲切应力", "扭转切应力",
        "纯弯曲", "横力弯曲", "平面弯曲",
        "组合变形", "拉弯组合", "弯扭组合",
        "超静定", "静定", "多余约束",
        "能量法", "卡氏定理", "莫尔定理",
        "单位载荷法", "图乘法",
        "动载荷", "冲击载荷", "交变载荷",
        "平面应力", "空间应力",
        "材料力学", "力学性能", "机械性能",
        "低碳钢", "铸铁", "塑性材料", "脆性材料",
        "延伸率", "断面收缩率",
        "刚度", "强度", "稳定性",
        "载荷", "外力", "内力", "约束力",
        "支座", "固定端", "铰支座",
        "分布载荷", "集中载荷", "力偶",
        "平衡方程", "变形协调", "物理方程",
        "叠加原理", "力的独立作用原理",
        "轴力图", "剪力图", "弯矩图", "扭矩图", "应力图",
        "轴向拉伸", "轴向压缩", "拉伸压缩",
    }
    
    FRAGMENT_PATTERNS = [
        r'^[\u4e00-\u9fff]{1}$',
        r'^[0-9]+$',
        r'^[a-zA-Z]$',
        r'^第[一二三四五六七八九十百千万]+',
        r'.*[吗呢吧啊呀]$',
        r'^为[一二三四五六七八九十两]',
        r'^[上下左右内外]侧$',
        r'^[上下左右内外]的',
        r'^为[正负大小]',
        r'^[什么为什么]',
    ]
    
    @classmethod
    def is_stopword(cls, term: str) -> Tuple[bool, str]:
        """判断是否为停用词（白名单优先）"""
        if not term or len(term.strip()) == 0:
            return True, "空词"
        
        term = term.strip()
        
        if term in cls.MATERIAL_MECHANICS_WHITELIST:
            return False, ""
        
        if term in cls.SINGLE_CHARS:
            return True, "单字停用词"
        
        if term in cls.COMMON_VERBS:
            return True, "常见动词"
        
        if term in cls.CONNECTIVES:
            return True, "接续词"
        
        for pattern in cls.FRAGMENT_PATTERNS:
            if re.match(pattern, term):
                return True, f"匹配过滤模式"
        
        return False, ""


class HybridTermExtractor:
    """混合策略专业名词提取器"""
    
    def __init__(
        self,
        min_freq: int = 2,
        max_term_len: int = 8,
        min_term_len: int = 2,
    ):
        self.min_freq = min_freq
        self.max_term_len = max_term_len
        self.min_term_len = min_term_len
        
        self._char_freq: Counter = Counter()
        self._bigram_freq: Counter = Counter()
        self._term_candidates: Dict[str, TermCandidate] = {}
        self._left_context: Dict[str, Counter] = defaultdict(Counter)
        self._right_context: Dict[str, Counter] = defaultdict(Counter)
        
    def extract_from_texts(self, texts: List[str]) -> List[TermCandidate]:
        """从文本列表中提取专业名词"""
        logger.info(f"开始从 {len(texts)} 个文本中提取专业名词（混合策略）")
        
        logger.info("步骤1: 统计字频和双字频...")
        self._collect_statistics(texts)
        
        logger.info("步骤2: 生成候选术语...")
        self._generate_candidates(texts)
        
        logger.info("步骤3: 计算统计指标...")
        self._calculate_metrics()
        
        logger.info("步骤4: 应用动态阈值...")
        self._apply_dynamic_thresholds()
        
        logger.info("步骤5: 应用过滤规则...")
        valid_candidates = self._apply_filters()
        
        logger.info("步骤6: 计算综合得分并排序...")
        valid_candidates = self._rank_candidates(valid_candidates)
        
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
        """计算TF-IDF"""
        return float(freq)
    
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
    
    def _apply_dynamic_thresholds(self) -> None:
        """应用动态阈值"""
        for term, candidate in self._term_candidates.items():
            length = len(term)
            
            if length == 2:
                min_mi = 1.0
                min_entropy = 0.3
            elif length <= 4:
                min_mi = 1.5
                min_entropy = 0.5
            else:
                min_mi = 2.0
                min_entropy = 0.8
            
            avg_entropy = (candidate.left_entropy + candidate.right_entropy) / 2
            
            if term in HybridStopWordsFilter.MATERIAL_MECHANICS_WHITELIST:
                candidate.is_valid = True
            elif candidate.mutual_info < min_mi:
                candidate.is_valid = False
                candidate.invalid_reason = f"互信息过低: {candidate.mutual_info:.2f} < {min_mi}"
            elif avg_entropy < min_entropy:
                candidate.is_valid = False
                candidate.invalid_reason = f"平均熵过低: {avg_entropy:.2f} < {min_entropy}"
    
    def _apply_filters(self) -> List[TermCandidate]:
        """应用过滤规则"""
        valid_candidates = []
        
        for term, candidate in self._term_candidates.items():
            if not candidate.is_valid:
                continue
            
            is_stop, reason = HybridStopWordsFilter.is_stopword(term)
            if is_stop:
                candidate.is_valid = False
                candidate.invalid_reason = reason
                continue
            
            valid_candidates.append(candidate)
        
        return valid_candidates
    
    def _rank_candidates(self, candidates: List[TermCandidate]) -> List[TermCandidate]:
        """计算综合得分并排序"""
        import math
        
        for candidate in candidates:
            freq_score = math.log2(candidate.frequency + 1)
            mi_score = candidate.mutual_info / 10.0
            entropy_score = (candidate.left_entropy + candidate.right_entropy) / 2
            cvalue_score = math.log2(candidate.c_value + 1)
            
            in_whitelist = candidate.text in HybridStopWordsFilter.MATERIAL_MECHANICS_WHITELIST
            whitelist_bonus = 5.0 if in_whitelist else 0.0
            
            candidate.score = (
                freq_score * 2.0 +
                mi_score * 1.5 +
                entropy_score * 1.0 +
                cvalue_score * 0.5 +
                whitelist_bonus
            )
        
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates
    
    def get_top_terms(self, n: int = 100) -> List[str]:
        """获取Top N术语"""
        valid = [c for c in self._term_candidates.values() if c.is_valid]
        valid.sort(key=lambda c: c.score, reverse=True)
        return [c.text for c in valid[:n]]
