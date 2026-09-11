"""OJ 题目元数据：难度与标签的**纯领域逻辑**。

本模块与 `domain/oj/intelligence/` 同一约束：**不 import `app.models` /
`app.services`、不接收 session**。它定义的是「合法取值是什么、怎么规范化」，
不含任何持久化。

为什么难度用**三档枚举**而不是 1–5 整数：

仓库里有两个互相冲突的先例 ——
`models/question_bank_model.py:35 QuestionDifficulty`（easy / medium / hard）
与 `api/v1/endpoints/knowledge.py`（1–5 整数）。
但 `services/question_generation_llm.py:258` 已经在用三档并**硬编码兜底 `medium`**，
`QuestionDifficulty` 也是全仓唯一被持久化的难度枚举。
**选三档是为了全站难度语义统一** —— 将来「练习问答」与「OJ 编程题」若要在
同一页混排或按难度统一筛，两套取值域会立刻变成麻烦。
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable

__all__ = [
    "DEFAULT_DIFFICULTY",
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "ProblemDifficulty",
    "normalize_difficulty",
    "normalize_tags",
    "valid_difficulty_values",
]


class ProblemDifficulty(str, Enum):
    """题目难度——**与 `QuestionDifficulty` 取值集一致**（easy / medium / hard）。

    刻意保留为独立枚举而非直接 import `QuestionDifficulty`：两者属于不同
    bounded context（问答库 vs OJ），共用一个 Python 枚举会把两个域绑死。
    取值集一致由测试守住（`test_oj_problem_metadata.py`）。
    """

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


#: 新建题目未指定难度时的默认值。与 `question_generation_llm` 的兜底一致。
DEFAULT_DIFFICULTY = ProblemDifficulty.MEDIUM.value

#: 单个题目最多标签数。超出即拒，不静默截断——截断会让教师以为自己填的都在。
MAX_TAGS = 20

#: 单个标签最大长度（字符）。同样超出即拒。
MAX_TAG_LENGTH = 32


def valid_difficulty_values() -> frozenset[str]:
    """全部合法难度取值（小写字符串）。供契约测试与文档生成引用。"""
    return frozenset(d.value for d in ProblemDifficulty)


def normalize_difficulty(value: object) -> str:
    """规范化难度：枚举 / 字符串双接受，大小写与首尾空白不敏感。

    **非法值抛 `ValueError`，不兜底。** 这与 `question_generation_llm:258`
    的「非法 → medium」策略**有意不同**：

    - 那里是 **LLM 输出解析**，模型偶尔给出脏值是预期内的，兜底才能保住流水线；
    - 这里是 **教师显式填写**，填错必须让他知道。静默兜底会出现
      「我明明写了 hard，怎么存成了 medium」这类无从排查的问题。

    `None` 与空串归 `DEFAULT_DIFFICULTY` —— 「没填」是合法输入，「填错」不是。
    """
    if value is None:
        return DEFAULT_DIFFICULTY
    raw = getattr(value, "value", value)
    text = str(raw).strip().lower()
    if not text:
        return DEFAULT_DIFFICULTY
    if text not in valid_difficulty_values():
        allowed = ", ".join(sorted(valid_difficulty_values()))
        raise ValueError(f"难度取值非法：{value!r}；允许 {allowed}")
    return text


def normalize_tags(values: Iterable[object] | None) -> list[str]:
    """规范化标签列表：去空白、保序去重（大小写不敏感）、逐条校验。

    规则：

    1. 非字符串项先 `str()` 再处理（容忍 JSON 里的数字标签）；
    2. 每条 `strip()`；**空串丢弃**（教师在输入框多敲个回车不该变成空标签）；
    3. **大小写不敏感去重且保序** —— `["DP", "dp"]` → `["DP"]`，
       保留**首次出现**的写法，因为那是教师的原始意图；
    4. 单条超 `MAX_TAG_LENGTH` 抛错；
    5. 去重后超 `MAX_TAGS` 抛错。

    **不做大小写归并**（不把 `DP` 变成 `dp`）：中文标签无大小写概念，
    英文缩写 `DP` / `SQL` 全大写才是惯用写法。归并会破坏教师意图，
    而去重已足够防止 `DP` 与 `dp` 同时出现的脏数据。
    """
    if values is None:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        if len(text) > MAX_TAG_LENGTH:
            raise ValueError(
                f"标签过长（{len(text)} 字符 > {MAX_TAG_LENGTH}）：{text[:MAX_TAG_LENGTH]}…"
            )
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)

    if len(result) > MAX_TAGS:
        raise ValueError(f"标签过多（{len(result)} > {MAX_TAGS}）")
    return result
