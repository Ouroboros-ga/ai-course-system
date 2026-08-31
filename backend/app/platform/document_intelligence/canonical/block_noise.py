"""Deterministic boilerplate detection for parsed document blocks.

Teaching decks repeat slide-master furniture (running headers/footers,
watermarks, cover signatures) on every page.  Each such text block otherwise
becomes an EvidenceSpan + RetrievalChunk candidate and leaks into node
sources, the prep-agent evidence pane and retrieval, which reads as nonsense
to teachers.  These rules are deterministic and LLM-free: the same blocks
always yield the same noise set, so filtering stays auditable and testable.

The canonical DocumentBlock store keeps every block; only query-facing
projections (anchors/spans/chunks) and draft builders skip noise blocks.
"""
from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256
from typing import Any, Iterable

# Same text on >= 3 distinct pages and short enough to be slide furniture.
REPEAT_MIN_PAGES = 3
REPEAT_MAX_CHARS = 100

# Cover signature lines: institution + trailing personal name, no sentence
# punctuation ("C++ 程序设计 第五章 … 沈阳航空工业学院 李照奎").
COVER_LINE_MAX_CHARS = 60

_INSTITUTION_NAME_TAIL = re.compile(
    r"(大学|学院|学校|研究院|研究所|出版社)[\s\u3000]+[\u4e00-\u9fa5]{2,4}$"
)
_FURNITURE_LINE = re.compile(
    r"^(?:"
    r"\d{1,4}"
    r"|第\s*\d+\s*页"
    r"|[-—–~\s]*\d+[-—–~\s]*"
    r"|page\s*\d+"
    r"|\d{4}[-/.年]\s*\d{1,2}[-/.月]\s*\d{1,2}日?"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|https?://\S+"
    r")$",
    re.IGNORECASE,
)
_SENTENCE_PUNCTUATION = "。；？！;?!"


def _text_of(block: Any) -> str:
    return (getattr(block, "text", None) or "").strip()


def _page_of(block: Any) -> int:
    return int(
        getattr(block, "page_or_slide", None)
        or getattr(block, "page_number", None)
        or 0
    )


def is_furniture_line(text: str) -> bool:
    """Pure page numbers, dates, emails, URLs — never teaching content."""
    compact = text.strip()
    return bool(compact) and bool(_FURNITURE_LINE.match(compact))


def is_cover_signature_line(text: str) -> bool:
    """Institution + trailing author name without sentence punctuation."""
    compact = text.strip()
    if not compact or len(compact) > COVER_LINE_MAX_CHARS:
        return False
    if any(ch in compact for ch in _SENTENCE_PUNCTUATION):
        return False
    return bool(_INSTITUTION_NAME_TAIL.search(compact))


def detect_noise_block_ids(blocks: Iterable[Any]) -> set[str]:
    """Return block_ids that are boilerplate and must not become evidence.

    Accepts both canonical DocumentIR blocks and persisted DocumentBlock
    rows: only ``block_id`` / ``text`` / ``page_or_slide`` are read.
    """
    by_hash: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"pages": set(), "block_ids": [], "text": ""}
    )
    noise: set[str] = set()
    for block in blocks:
        text = _text_of(block)
        block_id = getattr(block, "block_id", None)
        if not text or not block_id:
            continue
        if is_furniture_line(text) or is_cover_signature_line(text):
            noise.add(block_id)
            continue
        entry = by_hash[sha256(text.encode("utf-8")).hexdigest()]
        entry["pages"].add(_page_of(block))
        entry["block_ids"].append(block_id)
        entry["text"] = text
    for entry in by_hash.values():
        if len(entry["pages"]) >= REPEAT_MIN_PAGES and len(entry["text"]) <= REPEAT_MAX_CHARS:
            noise.update(entry["block_ids"])
    return noise


def filter_noise_blocks(blocks: list[Any]) -> list[Any]:
    """Convenience wrapper returning only non-noise blocks, order preserved."""
    noise = detect_noise_block_ids(blocks)
    return [block for block in blocks if getattr(block, "block_id", None) not in noise]
