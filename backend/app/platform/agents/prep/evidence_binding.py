"""Deterministic local evidence attribution for initial course preparation.

The Prep LLM deliberately never returns evidence identifiers: identifiers are
audit-critical and model-generated IDs are not trustworthy.  This module keeps
that boundary while avoiding the opposite failure mode of assigning the whole
course corpus to every generated node.

All functions operate on already available, in-memory titles/topics/text and
return only existing server-side evidence identifiers.  They never call an
LLM, persist content, or invent references.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_LATIN_WORD = re.compile(r"[a-z0-9_+#.-]{2,}", re.IGNORECASE)


def _value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _descriptor_text(item: Any) -> str:
    """Return a bounded descriptive representation without identifiers."""
    if isinstance(item, str):
        return item
    parts: list[str] = []
    for name in ("title", "topic", "rationale", "claim", "reason", "content", "text"):
        value = _value(item, name)
        if isinstance(value, str) and value.strip():
            parts.append(value[:4_000])
    for name in ("examples", "exercises", "claims"):
        value = _value(item, name, [])
        if isinstance(value, list):
            parts.extend(str(part)[:500] for part in value[:10] if str(part).strip())
    return " ".join(parts)


def _tokens(value: str) -> set[str]:
    """Build stable Chinese character n-grams plus Latin identifier tokens."""
    value = value.casefold()
    han = "".join(char for char in value if "\u4e00" <= char <= "\u9fff")
    result = set(_LATIN_WORD.findall(value))
    if len(han) == 1:
        result.add(han)
    else:
        result.update(han[index:index + 2] for index in range(len(han) - 1))
    return result


def _similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    common = len(left_tokens & right_tokens)
    if not common:
        return 0.0
    # Recall favors evidence that covers the generated topic; precision keeps
    # generic source blocks from outranking a focused block by sheer length.
    return 0.7 * common / len(left_tokens) + 0.3 * common / len(right_tokens)


def _source_refs(source: Any) -> list[str]:
    values = _value(source, "evidence_ids", None)
    if isinstance(values, list):
        return [str(value) for value in values if str(value)]
    evidence_id = _value(source, "evidence_id", "")
    return [str(evidence_id)] if evidence_id else []


def _append_unique(target: list[str], values: Sequence[str], *, limit: int) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)
        if len(target) >= limit:
            return


def bind_evidence_refs(
    outputs: Sequence[Any],
    sources: Sequence[Any],
    *,
    max_source_items: int,
    max_evidence_refs: int,
) -> list[list[str]]:
    """Bind each generated output to a compact, local existing evidence set.

    Matching combines textual relevance with a small ordering prior.  The
    latter makes results stable for broad headings or sparse OCR text, and it
    prevents every heading from selecting the same generic opening block.
    At least one available source is selected for each output so the existing
    strict evidence contract remains satisfied.
    """
    if not outputs or not sources:
        return [[] for _ in outputs]
    source_texts = [_descriptor_text(item) for item in sources]
    output_count = len(outputs)
    source_count = len(sources)
    bound: list[list[str]] = []
    for output_index, output in enumerate(outputs):
        query = _descriptor_text(output)
        expected = (output_index + 0.5) / output_count
        ranked: list[tuple[float, float, int]] = []
        for source_index, source_text in enumerate(source_texts):
            lexical = _similarity(query, source_text)
            source_position = (source_index + 0.5) / source_count
            position = max(0.0, 1.0 - abs(expected - source_position) * 2.0)
            # Text is primary. Position only resolves generic or zero-overlap
            # cases deterministically and cannot by itself select all corpus
            # evidence.
            ranked.append((lexical * 0.85 + position * 0.15, lexical, source_index))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        selected: list[str] = []
        selected_sources = 0
        best_lexical = ranked[0][1] if ranked else 0.0
        for _score, lexical, source_index in ranked:
            if selected_sources >= max(1, max_source_items):
                break
            # After a meaningful direct hit, ignore much weaker generic
            # matches. If there are no direct hits, positional fallback still
            # supplies one bounded source rather than a global union.
            if selected_sources and best_lexical > 0 and lexical < best_lexical * 0.45:
                continue
            before = len(selected)
            _append_unique(selected, _source_refs(sources[source_index]), limit=max(1, max_evidence_refs))
            if len(selected) > before:
                selected_sources += 1
            if len(selected) >= max(1, max_evidence_refs):
                break
        if not selected:
            _append_unique(selected, _source_refs(sources[ranked[0][2]]), limit=max(1, max_evidence_refs))
        bound.append(selected)
    return bound


def bind_outline_evidence_refs(
    candidates: Sequence[Any],
    segments: Sequence[Any],
) -> dict[str, list[str]]:
    """Bind knowledge points locally, then aggregate bounded child evidence.

    A section/chapter is allowed to summarize children, but it never receives a
    course-wide union.  This makes its evidence count proportional to its own
    subtree and keeps teacher review useful.
    """
    direct = bind_evidence_refs(
        candidates,
        segments,
        max_source_items=3,
        max_evidence_refs=8,
    )
    by_id = {
        str(_value(candidate, "candidate_id")): list(refs)
        for candidate, refs in zip(candidates, direct, strict=True)
    }
    children: dict[str, list[str]] = {}
    for candidate in candidates:
        parent = str(_value(candidate, "parent_candidate_id", "") or "")
        child = str(_value(candidate, "candidate_id", ""))
        if parent and child:
            children.setdefault(parent, []).append(child)

    def aggregate(candidate_id: str, visiting: set[str]) -> list[str]:
        if candidate_id in visiting:
            return list(by_id.get(candidate_id, []))
        visiting.add(candidate_id)
        refs = list(by_id.get(candidate_id, []))
        for child_id in children.get(candidate_id, []):
            _append_unique(refs, aggregate(child_id, visiting), limit=24)
        visiting.remove(candidate_id)
        return refs

    result: dict[str, list[str]] = {}
    for candidate in candidates:
        candidate_id = str(_value(candidate, "candidate_id", ""))
        node_type = str(_value(candidate, "node_type", ""))
        limit = 8 if node_type == "knowledge_point" else 12 if node_type == "section" else 24
        refs: list[str] = []
        _append_unique(refs, aggregate(candidate_id, set()), limit=limit)
        result[candidate_id] = refs
    return result


__all__ = ["bind_evidence_refs", "bind_outline_evidence_refs"]
