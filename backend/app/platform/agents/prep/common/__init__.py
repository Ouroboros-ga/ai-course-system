"""Common state and dependency types shared across Prep Agent pipelines.

This subpackage holds the cross-cutting types used by all three Prep
pipelines (Initial, Incremental, PPT mapping): the shared
``PrepCommonState`` schema and the ``CommonPrepDependencies`` injection
container. Agent-specific state and per-pipeline composition live in the
parent ``prep`` package.
"""

from __future__ import annotations

__all__: list[str] = []
