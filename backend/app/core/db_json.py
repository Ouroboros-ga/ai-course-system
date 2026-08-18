"""Cross-dialect JSON helpers for the PostgreSQL 16 baseline.

The knowledge node columns (``knowledge_node_ids`` / ``prerequisite_node_ids``)
are declared as ``Column(JSON)``. On PostgreSQL the native ``json`` type does
not support ``LIKE``, so ``column.contains([value])`` compiles to
``json ~~ text`` and raises ``UndefinedFunction``. SQLite stores the same
column as TEXT and works. These helpers compile to a cast-to-text ``LIKE``
that runs on both databases; node ids are course-local integers so the
substring match cannot collide across the bounded id ranges of one course.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast


def json_array_contains(column: Any, value: Any) -> Any:
    """Return a where-clause matching ``value`` inside a JSON array column.

    Use this instead of ``column.contains([value])`` for ``Column(JSON)``
    array fields so the same query runs on PostgreSQL 16 and SQLite.
    """
    return cast(column, String).like(f"%{value}%")


__all__ = ["json_array_contains"]
