"""Compatibility shim: cognition port now lives in providers/cognition/cognition."""

from __future__ import annotations

from ..providers.cognition.cognition import (
    CallableCognitionPort,
    make_session_scoped_cognition_port,
)
