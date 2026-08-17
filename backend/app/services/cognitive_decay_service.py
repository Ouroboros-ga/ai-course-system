"""证据时间衰减（读取投影，不落库）。

M2（2026-08-17）：六维认知状态的证据随时间遗忘建模。衰减只作用于
读取侧投影，绝不修改 ``CognitiveState`` 行（``is_latest`` 历史保留原值），
避免污染历史审计数据。

衰减规则：``decay = 2 ** (-elapsed_days / half_life_days)``

- ``elapsed_days`` 基于 ``computed_at`` 与当前时刻的差值（浮点天数）；
- 无状态（state 为 None）或无 ``computed_at`` 时 factor = 1.0（不衰减）；
- 作用于 ``evidence_confidence`` 与 ``mastery_score`` 的投影值；
- 由调用方在因子 < 1.0 时向序列化 reason_codes 追加 ``evidence_decayed``。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

# 明显衰减阈值：factor <= 0.99（约 5 小时以上半衰期衰减）才在序列化
# reason_codes 追加 evidence_decayed。避免毫秒级 elapsed 造成的浮点噪声
# 让刚计算的状态也带上"已衰减"标记。
DECAY_MARK_THRESHOLD = 0.99


def decay_factor_for(
    computed_at: datetime | None,
    *,
    now: datetime | None = None,
    half_life_days: float | None = None,
) -> float:
    """Return the multiplicative decay factor for evidence age.

    ``half_life_days`` defaults to ``settings.COGNITIVE_HALF_LIFE_DAYS``.
    Naive datetimes are treated as UTC (historical rows may be naive).
    """
    if computed_at is None:
        return 1.0
    half_life = (
        half_life_days
        if half_life_days is not None
        else float(settings.COGNITIVE_HALF_LIFE_DAYS)
    )
    if half_life <= 0:
        return 1.0
    current = now if now is not None else datetime.now(UTC)
    computed = computed_at
    if computed.tzinfo is None:
        computed = computed.replace(tzinfo=UTC)
    elapsed_days = max(0.0, (current - computed).total_seconds() / 86_400.0)
    return 2.0 ** (-elapsed_days / half_life)


def decayed_confidence(
    evidence_confidence: float | None,
    *,
    computed_at: datetime | None = None,
    now: datetime | None = None,
    half_life_days: float | None = None,
) -> float | None:
    """Confidence decayed projection; None stays None."""
    if evidence_confidence is None:
        return None
    return float(evidence_confidence) * decay_factor_for(
        computed_at, now=now, half_life_days=half_life_days,
    )


def decayed_mastery_score(
    mastery_score: float | None,
    *,
    computed_at: datetime | None = None,
    now: datetime | None = None,
    half_life_days: float | None = None,
) -> float | None:
    """Mastery decayed projection; None stays None."""
    if mastery_score is None:
        return None
    return float(mastery_score) * decay_factor_for(
        computed_at, now=now, half_life_days=half_life_days,
    )


def project_time_decay(
    state: Any,
    *,
    now: datetime | None = None,
    half_life_days: float | None = None,
) -> tuple[float | None, float | None, float]:
    """Return ``(decayed_confidence, decayed_mastery_score, factor)`` for a state.

    Read-only projection: the stored row is never mutated. ``factor < 1.0``
    means decay applied; callers should append reason code ``evidence_decayed``
    to their serialized reason_codes.
    """
    computed_at = getattr(state, "computed_at", None)
    factor = decay_factor_for(computed_at, now=now, half_life_days=half_life_days)
    confidence = getattr(state, "evidence_confidence", None)
    mastery = getattr(state, "mastery_score", None)
    return (
        confidence * factor if confidence is not None else None,
        mastery * factor if mastery is not None else None,
        factor,
    )
