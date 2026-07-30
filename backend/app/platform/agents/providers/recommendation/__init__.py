"""Recommendation-domain providers: next-action recommendation port."""

from .recommendation import (
    CallableRecommendationPort,
    make_session_scoped_recommendation_port,
)

__all__ = [
    "CallableRecommendationPort",
    "make_session_scoped_recommendation_port",
]
