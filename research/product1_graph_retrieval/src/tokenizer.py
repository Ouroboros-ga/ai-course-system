"""Frozen, dependency-free mixed-script tokenizer for the R0 BM25 baseline."""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable


TOKENIZER_VERSION = "mixed-script-ngram/1.0"
LATIN_PATTERN = r"[a-z0-9]+(?:[._:/#+-][a-z0-9]+)*"
_TOKEN_RE = re.compile(
    rf"(?P<latin>{LATIN_PATTERN})|(?P<cjk>[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+)"
)


def normalize_search_text(text: str) -> str:
    """Return the search view only; callers must retain the original text."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return unicodedata.normalize("NFKC", text).casefold()


def tokenize(text: str) -> list[str]:
    """Tokenize Latin/code units plus CJK unigrams and adjacent bigrams."""

    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(normalize_search_text(text)):
        latin = match.group("latin")
        if latin:
            tokens.append(latin)
            continue
        sequence = match.group("cjk")
        if sequence:
            tokens.extend(sequence)
            tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return tokens


def unique_query_terms(text: str) -> list[str]:
    """Keep first occurrence order so repeated query terms do not change BM25."""

    seen: set[str] = set()
    return [term for term in tokenize(text) if not (term in seen or seen.add(term))]


def token_count(texts: Iterable[str]) -> int:
    return sum(len(tokenize(text)) for text in texts)
