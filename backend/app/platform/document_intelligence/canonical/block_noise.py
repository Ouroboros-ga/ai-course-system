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
_ROMAN_PAGE_MARKER = re.compile(r"^[IVXLCDM]+$")
_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff]")
_DECORATIVE_PREFIX = re.compile(r"^[┃│┆┇┊┋|｜]+")
_PROMOTION_HINT = re.compile(r"训练营|刷题|海量图解|公众号|扫码|关注|购买|配套资料|精品课程")
_BARE_FIGURE_LABEL = re.compile(
    r"^(?:图|表)\s*[一二三四五六七八九十百\d]+(?:\s*[-－—.]\s*\d+)*(?:\s*[A-Za-z])?$"
)
_CJK = re.compile(r"[\u3400-\u9fff]")
_SYMBOL_OPERATORS = re.compile(r"[\s=+\-*/^(){}\[\],.:;<>≤≥≈≠%°|｜]+")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


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


def _block_type_of(block: Any) -> str:
    value = getattr(block, "block_type", "")
    return str(getattr(value, "value", value) or "").lower()


def _is_private_use_fragment(text: str) -> bool:
    compact = text.strip()
    if not compact or not 0xE000 <= ord(compact[0]) <= 0xF8FF:
        return False
    readable = " ".join(_PRIVATE_USE.sub("", compact).split())
    if not readable:
        return True
    if _CJK.search(readable):
        # Private-use glyphs are often bullets.  A real Chinese phrase after
        # the bullet remains useful teaching content and must survive.
        return False
    meaningful = _DIGITS.sub("", _SYMBOL_OPERATORS.sub("", readable))
    return len(meaningful) <= 1


def _is_decorative_promotion(text: str) -> bool:
    compact = text.strip()
    return bool(_DECORATIVE_PREFIX.match(compact) and _PROMOTION_HINT.search(compact))


def _is_symbol_residue(text: str) -> bool:
    """Reject context-free glyph/number residue but retain real expressions.

    Two or more non-numeric operands are enough to retain a short formula,
    for example ``Q=Q+W(Q)`` or ``COP=Q/W``.  A lone glyph, ``P3``, ``=`` or
    ``= 12.29`` cannot independently support a teaching claim.
    """
    compact = text.strip()
    if not compact or len(compact) > 60 or _CJK.search(compact):
        return False
    meaningful = _DIGITS.sub("", _SYMBOL_OPERATORS.sub("", compact))
    if len(meaningful) >= 2:
        return False
    return len(compact) <= 12


def classify_noise_blocks(blocks: Iterable[Any]) -> dict[str, str]:
    """Classify query-ineligible blocks with stable, auditable reason codes.

    Canonical blocks are never deleted.  The returned mapping controls only
    evidence, retrieval, graph and review projections.  Rules intentionally
    require high-confidence structural signals; longer teaching prose and
    complete code/formulas remain eligible.
    """
    materialized = list(blocks)
    by_hash: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"pages": set(), "block_ids": [], "text": ""}
    )
    excluded: dict[str, str] = {}
    for block in materialized:
        text = _text_of(block)
        block_id = getattr(block, "block_id", None)
        if not text or not block_id:
            continue
        if is_furniture_line(text):
            excluded[block_id] = "furniture_line"
        elif is_cover_signature_line(text):
            excluded[block_id] = "cover_signature"
        elif _ROMAN_PAGE_MARKER.fullmatch(text):
            excluded[block_id] = "roman_page_marker"
        elif _is_private_use_fragment(text):
            excluded[block_id] = "private_use_fragment"
        elif _is_decorative_promotion(text):
            excluded[block_id] = "decorative_promotion"
        elif _BARE_FIGURE_LABEL.fullmatch(text):
            excluded[block_id] = "bare_figure_label"
        elif _block_type_of(block) != "code" and _is_symbol_residue(text):
            excluded[block_id] = "symbol_residue"
        else:
            entry = by_hash[sha256(text.encode("utf-8")).hexdigest()]
            entry["pages"].add(_page_of(block))
            entry["block_ids"].append(block_id)
            entry["text"] = text
    for entry in by_hash.values():
        if len(entry["pages"]) >= REPEAT_MIN_PAGES and len(entry["text"]) <= REPEAT_MAX_CHARS:
            for block_id in entry["block_ids"]:
                excluded[block_id] = "repeated_furniture"
    return excluded


def detect_noise_block_ids(blocks: Iterable[Any]) -> set[str]:
    """Return block_ids that are boilerplate and must not become evidence.

    Accepts both canonical DocumentIR blocks and persisted DocumentBlock
    rows: only ``block_id`` / ``text`` / ``page_or_slide`` are read.
    """
    return set(classify_noise_blocks(blocks))


def filter_noise_blocks(blocks: list[Any]) -> list[Any]:
    """Convenience wrapper returning only non-noise blocks, order preserved."""
    noise = detect_noise_block_ids(blocks)
    return [block for block in blocks if getattr(block, "block_id", None) not in noise]
