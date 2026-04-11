"""
关键词提取器

基于统计方法的关键词提取，无需预定义词典。

核心思路：
  1. N-gram 统计：统计文本中连续字符的出现频率
  2. 互信息：衡量两个字符一起出现的概率是否高于随机
  3. 左右熵：衡量词边界的确定性
  4. 滑动窗口重叠检测：去除因 N-gram 偏移产生的冗余词
  5. 词边界规则：过滤无意义的组合
"""

import re
import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple


@dataclass
class KeywordCandidate:
    """关键词候选"""

    text: str
    score: float
    freq: int
    left_entropy: float
    right_entropy: float
    mutual_info: float


@dataclass
class ExtractionResult:
    """关键词提取结果"""

    keywords: List[Tuple[str, float]]
    candidates: List[KeywordCandidate]
    total_candidates: int


class StatisticalKeywordExtractor:
    """
    基于统计的关键词提取器

    无需预定义词典，通过统计方法自动发现文本中的关键词。
    """

    _CN_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")

    _STOP_CHARS = frozenset(
        "的了是在有和与或但如而被把让向从到对为以这那它他她我你你们它们"
        "这个那个这些那些什么怎么如何为什么哪是否就也都很还又再已"
        "一二三四五六七八九十百千万亿"
    )

    _BOUNDARY_HEAD = frozenset(
        "则而但如或因所如果那么虽然即使不过然而可是并且"
        "以及及其其中此外另外同时一般通常因此于是"
    )

    _BOUNDARY_TAIL = frozenset(
        "则而但如或的得地着了过把被让向从到对在"
        "以及及其其中此外另外同时"
    )

    _MAX_TEXT_LEN = 50000

    def __init__(
        self,
        min_freq: int = 2,
        min_len: int = 2,
        max_len: int = 6,
        min_score: float = 0.1,
        overlap_threshold: float = 0.6,
    ):
        self._min_freq = min_freq
        self._min_len = min_len
        self._max_len = max_len
        self._min_score = min_score
        self._overlap_threshold = overlap_threshold

    def extract(self, text: str, top_k: int = 20) -> ExtractionResult:
        """从文本中提取关键词"""
        cn_text = self._extract_chinese(text)
        if not cn_text:
            return ExtractionResult(keywords=[], candidates=[], total_candidates=0)

        ngram_stats, ngram_positions = self._compute_ngram_stats_and_positions(cn_text)
        candidates = self._compute_scores(cn_text, ngram_stats, ngram_positions)
        candidates = self._filter_by_boundary(candidates)
        candidates = self._remove_overlapping(candidates)
        candidates.sort(key=lambda c: c.score, reverse=True)

        keywords = [
            (c.text, c.score)
            for c in candidates[:top_k]
            if c.score >= self._min_score
        ]

        return ExtractionResult(
            keywords=keywords,
            candidates=candidates[:100],
            total_candidates=len(candidates),
        )

    def extract_for_indexing(self, text: str, top_k: int = 30) -> List[str]:
        """提取关键词用于索引，返回词列表"""
        result = self.extract(text, top_k=top_k)
        return [kw for kw, score in result.keywords]

    def _extract_chinese(self, text: str) -> str:
        """提取纯中文文本，截断过长文本"""
        cn = "".join(self._CN_CHAR_PATTERN.findall(text))
        if len(cn) > self._MAX_TEXT_LEN:
            cn = cn[: self._MAX_TEXT_LEN]
        return cn

    def _compute_ngram_stats_and_positions(
        self, text: str
    ) -> Tuple[Dict[int, Counter], Dict[str, List[int]]]:
        """一次遍历同时计算 N-gram 频率统计和位置索引"""
        stats: Dict[int, Counter] = {}
        positions: Dict[str, List[int]] = {}
        text_len = len(text)

        for n in range(self._min_len, self._max_len + 1):
            counter = Counter()
            for i in range(text_len - n + 1):
                ngram = text[i : i + n]
                if not self._is_valid_ngram(ngram):
                    continue
                counter[ngram] += 1
                if ngram not in positions:
                    positions[ngram] = []
                positions[ngram].append(i)
            if counter:
                stats[n] = counter

        return stats, positions

    def _is_valid_ngram(self, ngram: str) -> bool:
        """检查 N-gram 是否有效（含停用字则跳过）"""
        for c in ngram:
            if c in self._STOP_CHARS:
                return False
        return True

    def _compute_scores(
        self,
        text: str,
        ngram_stats: Dict[int, Counter],
        ngram_positions: Dict[str, List[int]],
    ) -> List[KeywordCandidate]:
        """计算每个候选词的综合得分"""
        char_freq = Counter(text)
        total_chars = sum(char_freq.values())

        candidates: List[KeywordCandidate] = []

        for n, counter in ngram_stats.items():
            for ngram, freq in counter.items():
                if freq < self._min_freq:
                    continue

                mutual_info = self._compute_mutual_info(
                    ngram, char_freq, total_chars, freq
                )

                positions = ngram_positions.get(ngram, [])
                left_entropy = self._compute_entropy_at_positions(text, positions, -1)
                right_entropy = self._compute_entropy_at_positions(text, positions, n)

                score = self._compute_final_score(
                    freq, mutual_info, left_entropy, right_entropy, n
                )

                candidates.append(
                    KeywordCandidate(
                        text=ngram,
                        score=score,
                        freq=freq,
                        left_entropy=left_entropy,
                        right_entropy=right_entropy,
                        mutual_info=mutual_info,
                    )
                )

        return candidates

    def _filter_by_boundary(
        self, candidates: List[KeywordCandidate]
    ) -> List[KeywordCandidate]:
        """词边界规则过滤"""
        filtered = []
        for c in candidates:
            if c.text[0] in self._BOUNDARY_HEAD:
                continue
            if c.text[-1] in self._BOUNDARY_TAIL:
                continue
            filtered.append(c)
        return filtered

    def _remove_overlapping(
        self, candidates: List[KeywordCandidate]
    ) -> List[KeywordCandidate]:
        """滑动窗口重叠检测去重（使用最长公共子串）"""
        sorted_cands = sorted(candidates, key=lambda x: x.score, reverse=True)
        kept: List[KeywordCandidate] = []

        for cand in sorted_cands:
            is_overlap = False
            for existing in kept:
                if abs(len(cand.text) - len(existing.text)) > 1:
                    continue
                lcs_len = self._longest_common_substring_len(cand.text, existing.text)
                shorter_len = min(len(cand.text), len(existing.text))

                if shorter_len > 0 and lcs_len / shorter_len > self._overlap_threshold:
                    is_overlap = True
                    break

            if not is_overlap:
                kept.append(cand)

        return kept

    @staticmethod
    def _longest_common_substring_len(s1: str, s2: str) -> int:
        """计算两个字符串的最长公共子串长度"""
        if len(s1) < len(s2):
            s1, s2 = s2, s1

        prev = [0] * (len(s2) + 1)
        max_len = 0

        for i in range(1, len(s1) + 1):
            curr = [0] * (len(s2) + 1)
            for j in range(1, len(s2) + 1):
                if s1[i - 1] == s2[j - 1]:
                    curr[j] = prev[j - 1] + 1
                    if curr[j] > max_len:
                        max_len = curr[j]
            prev = curr

        return max_len

    def _compute_mutual_info(
        self,
        ngram: str,
        char_freq: Counter,
        total_chars: int,
        ngram_freq: int,
    ) -> float:
        """计算互信息"""
        if len(ngram) < 2:
            return 0.0

        p_ngram = ngram_freq / total_chars
        p_chars = 1.0
        for c in ngram:
            p_c = char_freq.get(c, 0) / total_chars
            if p_c == 0:
                return 0.0
            p_chars *= p_c

        if p_chars == 0:
            return 0.0

        pmi = math.log(p_ngram / p_chars)
        return max(0, pmi)

    def _compute_entropy_at_positions(
        self, text: str, positions: List[int], offset: int
    ) -> float:
        """根据位置列表计算左右熵"""
        chars: List[str] = []
        text_len = len(text)
        for pos in positions:
            idx = pos + offset
            if 0 <= idx < text_len:
                chars.append(text[idx])
        return self._compute_entropy_from_list(chars)

    def _compute_entropy_from_list(self, chars: List[str]) -> float:
        """从字符列表计算信息熵"""
        if not chars:
            return 0.0

        counter = Counter(chars)
        total = len(chars)

        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        return entropy

    def _compute_final_score(
        self,
        freq: int,
        mutual_info: float,
        left_entropy: float,
        right_entropy: float,
        length: int,
    ) -> float:
        """计算综合得分"""
        freq_score = math.log(freq + 1)
        entropy_score = (left_entropy + right_entropy) / 2
        length_score = 1.0 + 0.1 * (length - 2)

        return (
            freq_score * 0.3
            + mutual_info * 0.3
            + entropy_score * 0.3
            + length_score * 0.1
        )


class HybridKeywordExtractor:
    """
    混合关键词提取器

    结合 IK 分词器（领域术语）和统计方法（普通关键词）
    """

    def __init__(self, dictionary=None):
        """
        初始化混合关键词提取器

        Args:
            dictionary: 自定义词典，如果为 None 则使用默认词典
        """
        self._statistical_extractor = StatisticalKeywordExtractor()
        self._dictionary = dictionary

    def extract(
        self,
        text: str,
        top_k: int = 30,
        use_ik: bool = True,
    ) -> List[Tuple[str, float, str]]:
        """
        提取关键词

        返回: [(关键词, 得分, 来源)]
        来源: "ik_dict" | "statistical"
        """
        results: List[Tuple[str, float, str]] = []

        if use_ik:
            from app.common.RAG.ik_tokenizer import IKTokenizer

            tokenizer = IKTokenizer(dictionary=self._dictionary)
            tokenize_result = tokenizer.tokenize(text)

            for term in tokenize_result.domain_terms:
                results.append((term, 10.0, "ik_dict"))

        stat_result = self._statistical_extractor.extract(text, top_k=top_k * 2)

        seen = {r[0] for r in results}
        for kw, score in stat_result.keywords:
            if kw not in seen:
                results.append((kw, score, "statistical"))
                seen.add(kw)

        results.sort(key=lambda x: x[1], reverse=True)

        return results[:top_k]

    def extract_for_indexing(self, text: str, top_k: int = 30) -> List[str]:
        """提取关键词用于索引"""
        results = self.extract(text, top_k=top_k)
        return [kw for kw, score, source in results]
