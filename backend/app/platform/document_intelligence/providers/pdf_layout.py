"""Box-aware layout analysis for pdfplumber pages.

Slide decks converted through LibreOffice keep their text frames as
geometry/font clusters.  Reading them line-by-line interleaves parallel
boxes (sidebar annotations, side-by-side code columns) and splits wrapped
sentences into visual-line fragments, which surfaces in evidence as
semantically truncated text and orphaned formula residue.

This module reconstructs the text boxes first (union-find over segments:
vertical adjacency + edge alignment + kind/font/size compatibility), then
emits one block per box paragraph, code region, or promoted slide title.
Output dicts are the text_blocks schema consumed by
``pdf_plumber.map_pdf_plumber_output_to_ir`` with an added
``block_type`` key ("heading" | "paragraph" | "code").
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PUA_RE = re.compile(r"[\ue000-\uf8ff]")
_SYMBOL_OPS_RE = re.compile(r"[\s=+\-*/^().,%]")
_DIGIT_RE = re.compile(r"\d")
_CJK_TERMINALS = "。！？；?!;"

_CODE_HINT = re.compile(
    r"(#include|std::|cout|cin|endl|void\s+\w+\s*\(|class\s+\w+|~\w+\s*\(|"
    r"int\s+\w+\s*[;=(]|double\s+\w+\s*[;=(]|float\s+\w+\s*[;=(]|char\s+\w+\s*[;=(]|"
    r"return\s|for\s*\(|while\s*\(|if\s*\(|"
    r"^\s*(public|private|protected)\s*:|^\s*<<|;\s*$|\{\s*$|\}\s*$|//|/\*)"
)
_MONO_HINT = re.compile(r"(consolas|courier|mono|cascadia|jetbrains)", re.IGNORECASE)
_COMMENT_PREFIX = re.compile(r"^\s*(//|#|/\*|\*)")
_ANNOTATION_PREFIX = re.compile(r"^\s*(输入|输出|结果|返回|示例|注[:：]|说明[:：]|例如)")
_BULLET_PREFIX = re.compile(r"^[•·▪○●\d①-⑩（(【]")
_INSTITUTION_TAIL = re.compile(r"(大学|学院|学校|研究院|研究所)[\s\u3000]+[\u4e00-\u9fa5]{2,4}$")
_FURNITURE_LINE = re.compile(
    r"^(?:\d{1,4}|第\s*\d+\s*页|[-—–~\s]*\d+[-—–~\s]*|page\s*\d+)$",
    re.IGNORECASE,
)
_FORMULA_HINT = re.compile(
    r"[=<>≤≥±×÷√^∑∫\\]|[A-Za-z0-9]\s*[+\-*/]\s*[A-Za-z0-9(]"
)

_TEXTISH = ("text", "annotation", "formula", "symbol")
_CODEISH = ("code", "comment")


def _clean(text: str) -> str:
    return _PUA_RE.sub("", text.replace("\u3000", " ")).strip()


def _cjk_join(words: List[Dict[str, Any]]) -> str:
    out = ""
    for word in words:
        token = word.get("text", "")
        if not token:
            continue
        if out and _CJK_RE.search(out[-1]) and _CJK_RE.search(token[0]):
            out += token
        elif out:
            out += " " + token
        else:
            out = token
    return out


def _join_text(prev: str, nxt: str, sep: str | None = None) -> str:
    if not prev:
        return nxt
    if sep is None:
        sep = "" if (_CJK_RE.search(prev[-1]) or _CJK_RE.search(nxt[0])) else " "
    return prev + sep + nxt


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_CJK_RE.findall(text)) / len(text)


def _ends_terminal(text: str) -> bool:
    return bool(text) and text.rstrip()[-1] in _CJK_TERMINALS + ".;:)]\"'"


def _is_formula_fragment(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 60 or _CJK_RE.search(stripped):
        return False
    if re.fullmatch(r"[\d\s.,%]+", stripped):
        return False
    return bool(_FORMULA_HINT.search(stripped))


def _is_symbol_residue(text: str) -> bool:
    """Diagram labels (𝑘, 𝑄) and split fraction tails (=, 0 =, = 12.29).

    Keeps anything with two or more meaningful symbols: real equations like
    ``𝑄 = 𝑄 + 𝑊(𝑄)`` or ``COP=Q/W`` stay, orphan glyphs drop.
    """
    stripped = text.strip()
    if not stripped or _CJK_RE.search(stripped):
        return False
    meaningful = _SYMBOL_OPS_RE.sub("", stripped)
    meaningful = _DIGIT_RE.sub("", meaningful)
    if len(meaningful) >= 2:
        return False
    if meaningful:
        return len(stripped) <= 8
    return len(stripped) <= 12


def _line_kind(text: str, fonts: str) -> str:
    if _MONO_HINT.search(fonts):
        return "code"
    if _COMMENT_PREFIX.match(text):
        return "comment"
    if _CODE_HINT.search(text):
        return "code"
    if _ANNOTATION_PREFIX.match(text):
        return "annotation"
    if not _CJK_RE.search(text) and len(text) <= 60 and _FORMULA_HINT.search(text):
        return "formula"
    return "text"


def _group_lines_tight(words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    ordered = sorted(words, key=lambda w: (round(w.get("top", 0) * 2) / 2, float(w.get("x0", 0))))
    lines: List[List[Dict[str, Any]]] = []
    for word in ordered:
        top, bottom = float(word.get("top", 0)), float(word.get("bottom", 0))
        size = max(float(word.get("size", 10) or 10), 1.0)
        target = None
        for line in reversed(lines):
            first = line[0]
            line_top, line_bottom = float(first.get("top", 0)), float(first.get("bottom", 0))
            overlap = max(0.0, min(bottom, line_bottom) - max(top, line_top))
            min_height = max(min(bottom - top, line_bottom - line_top), 1.0)
            if overlap / min_height >= 0.60 and abs(top - line_top) <= max(size * 0.30, 2.0):
                target = line
                break
        if target is None:
            lines.append([word])
        else:
            target.append(word)
    for line in lines:
        line.sort(key=lambda w: float(w.get("x0", 0)))
    return lines


def _split_by_gap(line: List[Dict[str, Any]], page_width: float) -> List[List[Dict[str, Any]]]:
    if not line:
        return []
    segments, seg = [], [line[0]]
    for prev, cur in zip(line, line[1:]):
        gap = float(cur.get("x0", 0)) - float(prev.get("x1", 0))
        size = max(float(cur.get("size", 10) or 10), 1.0)
        # CJK runs tolerate wide letter-spacing (PPT titles use ~1.0x font
        # size gaps between words); only true column breaks stay split.
        both_cjk = (
            _CJK_RE.search(str(prev.get("text", ""))[-1:])
            and _CJK_RE.search(str(cur.get("text", ""))[:1])
        )
        threshold = max(size * 1.8, 16.0) if both_cjk else max(size * 0.8, 12.0)
        if gap > threshold:
            segments.append(seg)
            seg = [cur]
        else:
            seg.append(cur)
    segments.append(seg)
    return segments


def _page_segments(page: Any) -> List[Dict[str, Any]]:
    try:
        words = page.extract_words(
            use_text_flow=False,
            keep_blank_chars=False,
            extra_attrs=["size", "fontname"],
        )
    except Exception:
        words = []
    segs: List[Dict[str, Any]] = []
    for line in _group_lines_tight(words):
        for seg in _split_by_gap(line, float(page.width)):
            text = _clean(_cjk_join(seg))
            if not text:
                continue
            fonts = " ".join(sorted({str(w.get("fontname", "")) for w in seg}))
            segs.append({
                "text": text,
                "x0": float(seg[0].get("x0", 0)),
                "x1": max(float(w.get("x1", 0)) for w in seg),
                "top": float(seg[0].get("top", 0)),
                "bottom": max(float(w.get("bottom", 0)) for w in seg),
                "size": sum(float(w.get("size", 12)) for w in seg) / len(seg),
                "fonts": fonts,
                "kind": _line_kind(text, fonts),
            })
    return segs


def _segs_mergeable(va: Dict[str, Any], vb: Dict[str, Any]) -> bool:
    ka, kb = va["kind"], vb["kind"]
    mixed = (ka in _TEXTISH and kb in _CODEISH) or (ka in _CODEISH and kb in _TEXTISH)
    if mixed:
        tail = va if ka in _TEXTISH else vb
        other = vb if ka in _TEXTISH else va
        size_ratio = max(tail["size"], other["size"]) / max(min(tail["size"], other["size"]), 0.1)
        return len(tail["text"]) <= 10 and _cjk_ratio(tail["text"]) >= 0.6 and size_ratio <= 1.15
    return True


def _fonts_compatible(a_fonts: str, b_fonts: str) -> bool:
    fa, fb = set(a_fonts.split()), set(b_fonts.split())
    if not fa or not fb:
        return True
    return bool(fa & fb)


def _cluster_boxes(segs: List[Dict[str, Any]], page_width: float) -> List[List[Dict[str, Any]]]:
    parent = list(range(len(segs)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    order = sorted(range(len(segs)), key=lambda i: (segs[i]["top"], segs[i]["x0"]))
    align_tol = page_width * 0.06
    for pos, ai in enumerate(order):
        va = segs[ai]
        for bi in order[pos + 1: pos + 9]:
            vb = segs[bi]
            if vb["top"] - va["top"] > va["size"] * 4.0:
                break
            v_gap = vb["top"] - va["bottom"]
            if v_gap < -va["size"] * 0.3 or v_gap > 2.2 * max(va["size"], vb["size"]):
                continue
            if not _segs_mergeable(va, vb):
                continue
            if not _fonts_compatible(va["fonts"], vb["fonts"]):
                continue
            x_overlap = min(va["x1"], vb["x1"]) - max(va["x0"], vb["x0"])
            if x_overlap <= 0:
                gap_x = max(va["x0"], vb["x0"]) - min(va["x1"], vb["x1"])
                narrow = (
                    va["kind"] in _CODEISH
                    and vb["kind"] in _CODEISH
                    and min(va["x1"] - va["x0"], vb["x1"] - vb["x0"]) < max(va["size"], vb["size"]) * 3
                    and gap_x < page_width * 0.2
                )
                if not narrow:
                    continue
            else:
                narrow = False
            same_size = max(va["size"], vb["size"]) / max(min(va["size"], vb["size"]), 0.1) <= 1.3
            aligned = (
                (abs(va["x0"] - vb["x0"]) <= align_tol or abs(va["x1"] - vb["x1"]) <= align_tol)
                and same_size
            ) or narrow
            if not aligned:
                continue
            ra, rb = find(ai), find(bi)
            if ra != rb:
                parent[rb] = ra

    boxes: Dict[int, List[Dict[str, Any]]] = {}
    for i, seg in enumerate(segs):
        boxes.setdefault(find(i), []).append(seg)
    box_list = [sorted(b, key=lambda s: (s["top"], s["x0"])) for b in boxes.values()]
    box_list.sort(key=lambda b: (min(s["top"] for s in b), min(s["x0"] for s in b)))
    return box_list


def _is_noise_box(box: List[Dict[str, Any]], page_height: float) -> bool:
    first = box[0]
    if first["top"] < page_height * 0.055 and len(box) <= 2:
        return True
    text = box[0]["text"]
    if _FURNITURE_LINE.match(text):
        return True
    if (
        len(text) <= 60
        and not any(ch in text for ch in _CJK_TERMINALS)
        and _INSTITUTION_TAIL.search(text)
    ):
        return True
    return False


def _box_to_blocks(
    box: List[Dict[str, Any]], page_width: float,
) -> List[Dict[str, Any]]:
    kinds = Counter(s["kind"] for s in box)
    box_kind = "code" if kinds.get("code", 0) + kinds.get("comment", 0) > len(box) / 2 else "text"

    if box_kind == "code":
        lines: List[str] = []
        for seg in box:
            if (
                lines
                and seg["kind"] not in _CODEISH
                and len(seg["text"]) <= 10
                and _cjk_ratio(seg["text"]) >= 0.6
            ):
                lines[-1] = _join_text(lines[-1], seg["text"], "")
            else:
                lines.append(seg["text"])
        return [{
            "kind": "code",
            "text": "\n".join(lines),
            "top": box[0]["top"], "bottom": box[-1]["bottom"],
            "x0": min(s["x0"] for s in box), "x1": max(s["x1"] for s in box),
            "size": box[0]["size"],
        }]

    blocks: List[Dict[str, Any]] = []
    i = 0
    while i < len(box):
        if box[i]["kind"] in _CODEISH:
            j = i
            while j < len(box) and box[j]["kind"] in _CODEISH:
                j += 1
            blocks.append({
                "kind": "code",
                "text": "\n".join(box[k]["text"] for k in range(i, j)),
                "top": box[i]["top"], "bottom": box[j - 1]["bottom"],
                "x0": min(box[k]["x0"] for k in range(i, j)),
                "x1": max(box[k]["x1"] for k in range(i, j)),
                "size": box[i]["size"],
            })
            i = j
            continue

        para = box[i]["text"]
        para_top, para_bottom = box[i]["top"], box[i]["bottom"]
        para_len = 1
        j = i + 1
        while j < len(box):
            prev_seg, nxt_seg = box[j - 1], box[j]
            pitch = nxt_seg["top"] - prev_seg["top"]
            if _BULLET_PREFIX.match(nxt_seg["text"]) or nxt_seg["kind"] in _CODEISH:
                break
            if pitch > 1.7 * max(nxt_seg["size"], prev_seg["size"]):
                break
            if _ends_terminal(para) and pitch > 1.25 * nxt_seg["size"]:
                break
            if para_len == 1 and not _ends_terminal(para) and len(para) <= 8 and _CJK_RE.search(para):
                para = para + "\n" + nxt_seg["text"]
            else:
                para = _join_text(para, nxt_seg["text"])
            para_bottom = nxt_seg["bottom"]
            para_len += 1
            j += 1
        blocks.append({
            "kind": "paragraph",
            "text": para,
            "top": para_top, "bottom": para_bottom,
            "x0": box[i]["x0"], "x1": box[i]["x1"],
            "size": box[i]["size"],
        })
        i = j
    return blocks


def _promote_slide_title(
    blocks: List[Dict[str, Any]], page_height: float, body_mode: float,
) -> List[Dict[str, Any]]:
    for blk in blocks:
        if (
            blk["kind"] == "paragraph"
            and blk["top"] < page_height * 0.25
            and len(blk["text"]) <= 40
            and "\n" not in blk["text"]
            and _CJK_RE.search(blk["text"])
            and blk.get("size", body_mode) >= body_mode * 1.05
        ):
            blk["kind"] = "heading"
            break
    return blocks


def _absorb_fragments(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not any(
        blk["kind"] == "paragraph" and _is_formula_fragment(blk["text"]) for blk in blocks
    ):
        return blocks

    def x_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> float:
        return min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])

    result: List[Dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        if not (block["kind"] == "paragraph" and _is_formula_fragment(block["text"])):
            result.append(block)
            continue
        prev = result[-1] if result else None
        nxt = blocks[idx + 1] if idx + 1 < len(blocks) else None
        if (
            prev
            and prev["kind"] in ("paragraph", "heading")
            and -8 <= block["top"] - prev["bottom"] < 40
            and x_overlap(prev, block) > 0
        ):
            prev["text"] = _join_text(prev["text"], block["text"])
            prev["bottom"] = block["bottom"]
            prev["x1"] = max(prev["x1"], block["x1"])
            continue
        if (
            nxt
            and nxt["kind"] == "code"
            and -8 <= nxt["top"] - block["bottom"] < 40
            and x_overlap(nxt, block) > 0
        ):
            nxt["text"] = block["text"] + "\n" + nxt["text"]
            nxt["top"] = block["top"]
            continue
        result.append(block)
    return result


def extract_page_blocks(page: Any) -> List[Dict[str, Any]]:
    """Extract box-aware text blocks from one pdfplumber page.

    Returns text_blocks dicts compatible with
    ``map_pdf_plumber_output_to_ir``: normalized bbox, text, confidence,
    is_heading, heading_level, font_size, plus ``block_type``.
    """
    width = float(page.width) if page.width else 1.0
    height = float(page.height) if page.height else 1.0

    segs = _page_segments(page)
    if not segs:
        return []
    sizes = Counter(round(s["size"]) for s in segs)
    body_mode = float(sizes.most_common(1)[0][0]) if sizes else 12.0

    blocks: List[Dict[str, Any]] = []
    for box in _cluster_boxes(segs, width):
        if _is_noise_box(box, height):
            continue
        blocks.extend(_box_to_blocks(box, width))

    blocks = _promote_slide_title(blocks, height, body_mode)
    blocks = _absorb_fragments(blocks)
    blocks = [
        b for b in blocks
        if b["kind"] == "heading" or not _is_symbol_residue(b["text"])
    ]

    out: List[Dict[str, Any]] = []
    for blk in blocks:
        x0 = max(0.0, min(1.0, blk["x0"] / max(width, 1)))
        y0 = max(0.0, min(1.0, blk["top"] / max(height, 1)))
        x1 = max(0.0, min(1.0, blk["x1"] / max(width, 1)))
        y1 = max(0.0, min(1.0, blk["bottom"] / max(height, 1)))
        if x1 < x0:
            x1 = x0
        if y1 < y0:
            y1 = y0
        is_heading = blk["kind"] == "heading"
        out.append({
            "bbox": [round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6)],
            "text": blk["text"],
            "confidence": 1.0,
            "is_heading": is_heading,
            "heading_level": 1 if is_heading else None,
            "font_size": blk.get("size"),
            "block_type": blk["kind"],
        })
    return out
