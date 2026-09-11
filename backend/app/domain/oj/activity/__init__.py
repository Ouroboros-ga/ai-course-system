"""OJ Activity 域的公共出口。

与 `domain/oj/problems` / `domain/oj/intelligence` 同一约定：
本包**只**导出纯领域规则，不 import `app.models` / `app.services`、
不接收 session。持久化与「何时校验」在
`app/services/experiment_activity_service.py`。
"""
from app.domain.oj.activity.policies import (
    ACTIVITY_STATUSES,
    ACTIVITY_TYPES,
    DEFAULT_ACTIVITY_TYPE,
    MAX_PROBLEMS_PER_ACTIVITY,
    RANKING_MODES,
    SCORING_MODES,
    SCOPE_TYPES,
    SUPPORTED_ACTIVITY_TYPES,
    ActivityStatus,
    ActivityType,
    assert_immutable_after_publish,
    assert_pinned_versions,
    assert_supported_type,
    assert_unique_ordinals,
    compute_homework_score,
    is_submission_open,
    normalize_activity_status,
    normalize_activity_type,
    normalize_ordinal,
    normalize_ranking_mode,
    normalize_scoring_mode,
    normalize_scope_type,
    validate_scope_payload,
    validate_time_window,
)

__all__ = [
    "ACTIVITY_STATUSES",
    "ACTIVITY_TYPES",
    "DEFAULT_ACTIVITY_TYPE",
    "MAX_PROBLEMS_PER_ACTIVITY",
    "RANKING_MODES",
    "SCORING_MODES",
    "SCOPE_TYPES",
    "SUPPORTED_ACTIVITY_TYPES",
    "ActivityStatus",
    "ActivityType",
    "assert_immutable_after_publish",
    "assert_pinned_versions",
    "assert_supported_type",
    "assert_unique_ordinals",
    "compute_homework_score",
    "is_submission_open",
    "normalize_activity_status",
    "normalize_activity_type",
    "normalize_ordinal",
    "normalize_ranking_mode",
    "normalize_scoring_mode",
    "normalize_scope_type",
    "validate_scope_payload",
    "validate_time_window",
]
