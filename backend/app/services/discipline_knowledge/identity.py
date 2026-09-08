"""DK1 确定性身份与文本规范化（无模型、无网络、无 DB）。

约定（与实施计划 §3、``knowledge_data/pipeline/ontology.json`` 一致）：

- ``NORMALIZER_VERSION = "norm/1"``：``unicodedata.normalize("NFKC")`` +
  换行统一为 ``\\n``。原文定位 ``start/end`` 恒指**规范化后文本**的
  Python Unicode code-point 半开区间，``quote`` 必须精确等于该区间。
- ``CHUNKER_VERSION = "chunk/1"``：按空行分段、合并至目标长度附近的
  **连续切片**分块（区别于语料 FTS 索引的 rowid 身份；此处每个 chunk 的
  ``text[start:end]`` 恒等于 chunk 文本，可直接做 quote 精确比对）。
- ``chunk_id = hash(version_id + chunker_version + locator + content_hash)``；
  normalize/chunker 版本变化必须生成新 ID（调用方把版本号计入身份）。
- token 粗估 ``tok-est/1`` 与
  ``knowledge_data/corpus/prepare_knowledge_sample.py::estimate_tokens``
  同口径；任一处修改必须同步另一处。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

NORMALIZER_VERSION = "norm/1"
CHUNKER_VERSION = "chunk/1"
TOKEN_ESTIMATE_VERSION = "tok-est/1"

CHUNK_TARGET_CHARS = 1000
CHUNK_MAX_CHARS = 1600
CHUNK_MIN_CHARS = 40
CHUNK_FLUSH_MIN = 200

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WS_RUN_RE = re.compile(r"\s+")


def normalize_text(text: str, version: str = NORMALIZER_VERSION) -> str:
    """规范化原文。未知版本直接拒绝，不静默回退旧口径。"""
    if version != NORMALIZER_VERSION:
        raise ValueError(
            f"SCHEMA_INVALID: unknown normalizer version '{version}' "
            f"(expected '{NORMALIZER_VERSION}')"
        )
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return normalized.replace("\r\n", "\n").replace("\r", "\n")


def normalize_alias(alias: str) -> str:
    """别名规范化：NFKC + casefold + 空白折叠。

    注意：规范化相等不等于语义同义（见 ontology identity_rule）；
    跨语言/歧义别名必须经 Resolver 上下文决策，本函数只做键归一。
    """
    text = unicodedata.normalize("NFKC", str(alias or ""))
    return _WS_RUN_RE.sub(" ", text.casefold()).strip()


def estimate_tokens(text: str) -> int:
    """token 容量粗估（tok-est/1）：``len(text)//4 + cjk_chars``。

    只用于预算与吞吐估算，不作为计费依据。
    """
    text = str(text or "")
    if not text:
        return 0
    return max(1, len(text) // 4 + len(_CJK_RE.findall(text)))


def sha16(*parts: object) -> str:
    """多段拼接的 sha256 前 16 hex（稳定短身份）。"""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8"))
    return digest.hexdigest()[:16]


def version_id_for(
    source_kind: str,
    external_id: str,
    raw_hash: str,
    normalizer_version: str = NORMALIZER_VERSION,
) -> str:
    return "dkdv_" + sha16("discipline-version", source_kind, external_id, raw_hash, normalizer_version)


def content_hash_for(chunk_text: str) -> str:
    return hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()


def chunk_id_for(
    version_id: str,
    chunker_version: str,
    locator: str,
    content_hash: str,
) -> str:
    return "dkch_" + sha16("discipline-chunk", version_id, chunker_version, locator, content_hash)


def concept_id_for_legacy(legacy_id: str) -> str:
    """legacy seed 概念映射：新 concept_id 稳定派生，旧 ID 存 legacy_id 列保留。"""
    return "dkn_" + sha16("discipline-legacy-concept", legacy_id)


def assertion_id_for_legacy(subject_id: str, predicate: str, object_id: str) -> str:
    return "dka_" + sha16("discipline-legacy-assertion", subject_id, predicate, object_id)


def chunk_spans(
    normalized: str,
    target: int = CHUNK_TARGET_CHARS,
    max_chars: int = CHUNK_MAX_CHARS,
    min_chars: int = CHUNK_MIN_CHARS,
) -> list[tuple[int, int, int, str]]:
    """把规范化文本切为连续切片，返回 [(chunk_no, start, end, text)]。

    - 按空行分段，段在 ``target`` 附近合并；超长段在 ``max_chars`` 内
      优先换行处切断，否则硬切；过短残片（``< min_chars``）丢弃；
    - 恒有 ``text == normalized[start:end]``（quote 精确比对的前提）。
    """
    text = str(normalized or "")
    n = len(text)
    if not text.strip():
        return []

    # -- 1. 按空行切段落（保留原文偏移，段内含单换行） --
    paragraphs: list[tuple[int, int]] = []
    buf_start: int | None = None
    pos = 0
    for line in text.splitlines(keepends=True):
        line_start = pos
        pos += len(line)
        if line.strip():
            if buf_start is None:
                buf_start = line_start
            buf_end = pos
        else:
            if buf_start is not None and (pos - buf_start) >= CHUNK_FLUSH_MIN:
                paragraphs.append((buf_start, pos))
                buf_start = None
    if buf_start is not None:
        paragraphs.append((buf_start, pos))

    # -- 2. 段落合并为块（连续区间） --
    blocks: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end: int = 0
    for start, end in paragraphs:
        if end - start > max_chars:
            if cur_start is not None:
                blocks.append((cur_start, cur_end))
                cur_start = None
            blocks.extend(_hard_cut(text, start, end, max_chars))
            continue
        if cur_start is None:
            cur_start, cur_end = start, end
        elif end - cur_start > max_chars:
            blocks.append((cur_start, cur_end))
            cur_start, cur_end = start, end
        else:
            cur_end = end
        if cur_end - cur_start >= target:
            blocks.append((cur_start, cur_end))
            cur_start = None
    if cur_start is not None:
        blocks.append((cur_start, cur_end))

    # -- 3. 过滤过短残片并编号 --
    result: list[tuple[int, int, int, str]] = []
    for start, end in blocks:
        piece = text[start:end]
        if len(piece.strip()) < min_chars:
            continue
        result.append((len(result), start, end, piece))
    return result


def _hard_cut(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """超长段硬切：在窗口内优先换行处断开，否则按 max_chars 切。"""
    cuts: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        window_end = min(pos + max_chars, end)
        if window_end >= end:
            cuts.append((pos, end))
            break
        newline = text.rfind("\n", pos, window_end)
        cut = newline + 1 if newline > pos else window_end
        cuts.append((pos, cut))
        pos = cut
    return cuts
