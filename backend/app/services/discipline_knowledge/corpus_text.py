"""CR1 语料正文：新规范化、分块与对象存储闭环（无模型、无网络）。

与 DK1 identity.py 的分工（旧口径冻结不动）：

- ``corpus-norm/2``：NFC + 换行统一，**保留大小写、代码与公式原样**
  （NFKC 的兼容折叠不适用于全部技术文本，由调用方按版本选择）；
- ``corpus-chunk/1``：按 embedding tokenizer 计数的窗口分块
  （目标 320 tokens、重叠 32，标题另计），超长显式拆分、**禁止静默截断**、
  短代码/公式不因短删除；
- 正文先写对象存储、读回校验通过才登记；``read_chunk_text`` 按
  ``(object_key, start, end, content_hash)`` 回读并验 hash，缺失/损坏
  直接报错，不用内存或清单文本兜底。

tokenizer 由调用方注入（``.count(text) -> int`` 与 ``.name``）；
无真实 tokenizer 时用 ``CharFallbackTokenizer``（字符粗估，名称明示，
CR2 接 E5 后替换）。chunker 有效版本含 tokenizer 名：
``corpus-chunk/1+<tokenizer-name>+t<target>+o<overlap>+m<max>``，换
tokenizer 或任一分块参数即新分块身份。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

CORPUS_NORMALIZER_VERSION = "corpus-norm/2"
CORPUS_CHUNKER_BASE = "corpus-chunk/1"
TEXT_STORE_VERSION = "corpus-texts/v1"

_SENTENCE_END_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?|[^。！？.!?\n]+$")


class CorpusTextError(ValueError):
    """携带错误码的正文存储失败（TEXT_UNAVAILABLE / TEXT_CORRUPT）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code


def normalize_corpus_text(text: str, version: str = CORPUS_NORMALIZER_VERSION) -> str:
    """corpus-norm/2：NFC + 换行统一；大小写/代码/公式/全角形原样保留。"""
    if version != CORPUS_NORMALIZER_VERSION:
        raise ValueError(
            f"SCHEMA_INVALID: unknown corpus normalizer version '{version}' "
            f"(expected '{CORPUS_NORMALIZER_VERSION}')"
        )
    normalized = unicodedata.normalize("NFC", str(text or ""))
    return normalized.replace("\r\n", "\n").replace("\r", "\n")


class CharFallbackTokenizer:
    """字符粗估 tokenizer（无真实模型时的确定性占位，名称明示）。

    口径与 tok-est/1 同公式；CR2 接入 E5 tokenizer 后替换，替换即新
    chunker 身份（旧块不混用）。
    """

    name = "char-fallback/1"

    def count(self, text: str) -> int:
        text = str(text or "")
        if not text:
            return 0
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        return max(1, len(text) // 4 + cjk)


def metadata_hash_for(metadata: dict[str, Any]) -> str:
    """元数据哈希：标题/链接/许可/语言/领域/家族任一变化即新值。"""
    canonical = {key: metadata.get(key) for key in (
        "title", "source_url", "license_code", "language",
        "domains", "source_family_id",
    )}
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def chunk_document(
    normalized: str,
    tokenizer: Any,
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """按 tokenizer 计数的窗口分块，返回 chunk 字典清单。

    - 按空行分段落，贪心装入 target_tokens；块间回退 overlap_tokens
     （贴段落边界，覆盖共享原文）；
    - 单段超 max_tokens：按句拆分，仍超长按字符硬切（token 当量估步长）；
    - 无最短删除、无截断：输出覆盖全部非空字符，每块恒为原文连续切片。
    """
    config = dict(config or {})
    target = max(1, int(config.get("target_tokens", 320) or 320))
    overlap = max(0, int(config.get("overlap_tokens", 32) or 0))
    max_tokens = max(target, int(config.get("max_tokens", 512) or 512))
    if tokenizer is None or not hasattr(tokenizer, "count"):
        raise ValueError("SCHEMA_INVALID: chunk_document 需要 tokenizer.count")
    text = str(normalized or "")
    if not text.strip():
        return []

    paragraphs = _paragraph_spans(text)
    if not paragraphs:
        return []

    # -- 基础 span：段落；超长段预拆分为片（每片 ≤ max_tokens） --
    spans: list[tuple[int, int]] = []
    for span in paragraphs:
        tokens = tokenizer.count(text[span[0]:span[1]])
        if tokens <= max_tokens:
            spans.append(span)
            continue
        spans.extend(_split_long_paragraph(text, span, tokens, tokenizer, max_tokens))
    span_tokens = [tokenizer.count(text[s:e]) for s, e in spans]

    # -- 按 token 装包（单 span 已 ≤ max，故包恒 ≤ max） --
    packs: list[tuple[int, int]] = []  # span 下标左闭右开
    lo = 0
    running = 0
    for hi, tokens in enumerate(span_tokens):
        if running > 0 and running + tokens > target:
            packs.append((lo, hi))
            lo, running = hi, 0
        running += tokens
    if lo < len(spans):
        packs.append((lo, len(spans)))

    # -- 落块：包转字符区间；非首块按 overlap 回退到 span 起点 --
    # 重叠为“尽量接近 requested、贴 span 起点、恒 ≤ max_tokens”：
    # 粗 span 下可能不足额，但共享区恒为原文逐字相同，可回读校验。
    chunks: list[dict[str, Any]] = []
    for index, (plo, phi) in enumerate(packs):
        start = spans[plo][0]
        if index > 0 and overlap > 0:
            prev_lo, _ = packs[index - 1]
            pack_sum = sum(span_tokens[plo:phi])
            acc = 0
            back_to = plo
            for candidate in range(plo - 1, prev_lo - 1, -1):
                if pack_sum + acc + span_tokens[candidate] > max_tokens:
                    break
                acc += span_tokens[candidate]
                back_to = candidate
                if acc >= overlap:
                    break
            start = min(start, spans[back_to][0])
        end = spans[phi - 1][1]
        piece = text[start:end]
        chunks.append({
            "chunk_no": len(chunks),
            "char_start": start,
            "char_end": end,
            "text": piece,
            "token_count": tokenizer.count(piece),
        })
    return chunks


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """按空行切段落（字符区间，含段内单换行，不含两侧空行）。"""
    spans: list[tuple[int, int]] = []
    buf_start: Optional[int] = None
    buf_end = 0
    pos = 0
    for line in text.splitlines(keepends=True):
        line_start = pos
        pos += len(line)
        if line.strip():
            if buf_start is None:
                buf_start = line_start
            buf_end = pos
        else:
            if buf_start is not None:
                spans.append((buf_start, buf_end))
                buf_start = None
    if buf_start is not None:
        spans.append((buf_start, buf_end))
    return spans


def _split_long_paragraph(
    text: str,
    span: tuple[int, int],
    tokens: int,
    tokenizer: Any,
    max_tokens: int,
) -> list[tuple[int, int]]:
    """超长段落：按句拆分，仍超长按字符硬切；返回字符区间清单（覆盖全段）。"""
    start, end = span
    body = text[start:end]
    sentences: list[tuple[int, int]] = []
    cursor = 0
    for match in _SENTENCE_END_RE.finditer(body):
        s, e = match.span()
        if e > cursor:
            sentences.append((start + cursor, start + e))
            cursor = e
    if cursor < len(body):
        sentences.append((start + cursor, end))
    if not sentences:
        sentences = [(start, end)]

    pieces: list[tuple[int, int]] = []
    for s, e in sentences:
        seg_tokens = tokenizer.count(text[s:e])
        if seg_tokens <= max_tokens:
            pieces.append((s, e))
            continue
        # 字符硬切：按 token 当量估步长，保证每片 ≤ max 且无遗漏
        seg_len = max(1, e - s)
        step = max(1, int(seg_len * max_tokens / max(1, seg_tokens)))
        pos = s
        while pos < e:
            pieces.append((pos, min(pos + step, e)))
            pos += step
    return pieces


# ---------------------------------------------------------------------------
# 对象存储闭环
# ---------------------------------------------------------------------------


def resolve_store_root(explicit: Any = None) -> Path:
    """存储根解析：显式参数 > 环境变量 > Settings > 默认相对目录。"""
    if explicit:
        return Path(str(explicit))
    env_root = os.environ.get("DISCIPLINE_TEXT_STORE_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    try:
        from app.core.config import settings

        configured = str(getattr(settings, "DISCIPLINE_TEXT_STORE_ROOT", "") or "")
        if configured.strip():
            return Path(configured)
    except Exception:  # noqa: BLE001 - 无配置环境回退默认目录
        pass
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "media" / "discipline_texts"


def object_key_for(source_kind: str, version_id: str) -> str:
    """确定性对象 key：同内容同版本恒同一 key（幂等复写无害）。"""
    safe_kind = re.sub(r"[^a-z0-9_-]", "_", str(source_kind or "unknown"))
    safe_version = re.sub(r"[^a-z0-9_-]", "_", str(version_id or "unknown"))
    return f"{TEXT_STORE_VERSION}/{safe_kind}/{safe_version}.txt"


_provider_cache: dict[str, Any] = {}


def get_store(root: Any = None):
    """返回命名空间存储 provider（复用对象存储本地实现，按 key 隔离）。"""
    resolved = resolve_store_root(root)
    key = str(resolved)
    provider = _provider_cache.get(key)
    if provider is None:
        from app.services.object_storage import LocalStorageProvider

        resolved.mkdir(parents=True, exist_ok=True)
        provider = LocalStorageProvider(str(resolved))
        _provider_cache[key] = provider
    return provider


def put_normalized_text(
    version_id: str,
    source_kind: str,
    normalized: str,
    *,
    root: Any = None,
) -> str:
    """写入规范化正文并读回验 hash；失败抛 CorpusTextError，不登记。"""
    from app.services.discipline_knowledge.identity import content_hash_for

    key = object_key_for(source_kind, version_id)
    payload = str(normalized or "").encode("utf-8")
    store = get_store(root)
    try:
        store.put(key, payload, mime_type="text/plain; charset=utf-8")
        raw = store.get(key)
    except FileNotFoundError as exc:
        raise CorpusTextError(
            "TEXT_UNAVAILABLE", f"正文写后读回失败：{key}") from exc
    except OSError as exc:
        raise CorpusTextError(
            "TEXT_UNAVAILABLE", f"对象存储不可用：{exc}") from exc
    if hashlib.sha256(raw).hexdigest() != content_hash_for(str(normalized or "")):
        raise CorpusTextError("TEXT_CORRUPT", f"读回 hash 不一致：{key}")
    return key


def read_chunk_text(session, chunk_id: str, *, root: Any = None) -> str:
    """按 (object_key, start, end, content_hash) 回读 chunk 原文并验 hash。"""
    from sqlmodel import select

    from app.models.discipline_knowledge_model import (
        DisciplineChunk,
        DisciplineDocumentVersion,
    )
    from app.services.discipline_knowledge.identity import content_hash_for

    chunk = session.exec(
        select(DisciplineChunk).where(DisciplineChunk.chunk_id == chunk_id)
    ).first()
    if chunk is None:
        raise CorpusTextError("TEXT_UNAVAILABLE", f"chunk 不存在：{chunk_id}")
    version = session.exec(
        select(DisciplineDocumentVersion).where(
            DisciplineDocumentVersion.version_id == chunk.version_id)
    ).first()
    if version is None or not version.object_key:
        raise CorpusTextError(
            "TEXT_UNAVAILABLE", f"chunk 所属版本无对象指针：{chunk_id}")
    try:
        raw = get_store(root).get(version.object_key)
    except FileNotFoundError as exc:
        raise CorpusTextError(
            "TEXT_UNAVAILABLE",
            f"正文对象缺失（不做内存/清单兜底）：{version.object_key}") from exc
    except OSError as exc:
        raise CorpusTextError(
            "TEXT_UNAVAILABLE", f"对象存储不可用：{exc}") from exc
    try:
        normalized = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusTextError(
            "TEXT_CORRUPT", f"正文非 UTF-8：{version.object_key}") from exc
    piece = normalized[chunk.char_start:chunk.char_end]
    if content_hash_for(piece) != chunk.content_hash:
        raise CorpusTextError(
            "TEXT_CORRUPT",
            f"chunk 切片 hash 不一致（存储或偏移已漂移）：{chunk_id}")
    return piece
