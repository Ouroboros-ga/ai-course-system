"""Prep Agent Provider implementations.

Each Provider wraps an existing application service and adapts it to the
corresponding Port protocol defined in ``prep/<pipeline>/dependencies.py``.

Providers:
    - ``InitialCoursePrepProvider``: wraps ``InitialCoursePrepService.build()``
    - ``IncrementalPrepProvider``: wraps ``CoursePrepAgentService.plan()``
    - ``PptMappingOptimizationProvider``: wraps ``PptMappingOptimizationService``
"""

from __future__ import annotations

__all__: list[str] = []
