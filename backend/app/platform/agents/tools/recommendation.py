"""Compatibility shim: recommendation port now lives in providers/recommendation/recommendation."""

from __future__ import annotations

from ..providers.recommendation.recommendation import (
    CallableRecommendationPort,
    make_session_scoped_recommendation_port,
)
