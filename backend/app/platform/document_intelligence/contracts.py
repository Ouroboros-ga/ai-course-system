"""Shared contract types for Document Intelligence V2.

This module defines the Geometry types (BoundingBox, Polygon, CoordinateSpace),
ReadingOrder, and SchemaVersion used across all DocumentIR components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

_SCHEMA_VERSION_PATTERN = re.compile(
    r"^document-ir/(\d+)\.(\d+)$"
)


@dataclass(frozen=True)
class SchemaVersion:
    """Parsed schema version following the Product 1 major.minor convention.

    Format: ``document-ir/major.minor``.

    Contracts do not use a patch component: implementation-only fixes that
    do not change contract semantics do not bump the contract version, and
    any semantic change is either minor (additive) or major (breaking).

    Unknown major versions must be rejected (fail-closed) at deserialization.
    """

    major: int
    minor: int

    @classmethod
    def parse(cls, raw: str) -> "SchemaVersion":
        """Parse a ``document-ir/`` version string.

        Raises ``ValueError`` for malformed input. Unknown major versions
        are parsed here but rejected (fail-closed) at deserialization.
        """
        m = _SCHEMA_VERSION_PATTERN.match(raw)
        if not m:
            raise ValueError(
                f"Invalid schema version format: {raw!r}. "
                f"Expected 'document-ir/major.minor'"
            )
        return cls(
            major=int(m.group(1)),
            minor=int(m.group(2)),
        )

    def serialize(self) -> str:
        return f"document-ir/{self.major}.{self.minor}"

    def is_compatible_with(self, consumer_supports_up_to_major: int) -> bool:
        """Return True if the consumer's supported major >= self.major."""
        return consumer_supports_up_to_major >= self.major

    def __str__(self) -> str:
        return self.serialize()


# Known current version
CURRENT_SCHEMA_VERSION = SchemaVersion(major=1, minor=0)


# ---------------------------------------------------------------------------
# Coordinate space
# ---------------------------------------------------------------------------


class CoordinateSpace(str, Enum):
    """Coordinate system for geometry values."""

    NORMALIZED = "normalized"          # 0..1 relative to page/slide dimensions
    INCH = "inch"                      # physical inches
    MILLIMETER = "millimeter"          # physical mm
    POINT = "point"                    # typographic points (1/72 inch)
    PIXEL = "pixel"                    # raster pixels (requires page dpi metadata)
    EMU = "emu"                        # English Metric Units (PPTX native)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box in a named coordinate space.

    All values must be finite (not NaN, not infinity).
    ``x0 <= x1`` and ``y0 <= y1`` are enforced on construction.
    """

    x0: float
    y0: float
    x1: float
    y1: float
    coordinate_space: CoordinateSpace = CoordinateSpace.NORMALIZED

    def __post_init__(self) -> None:
        _validate_finite(self.x0, "x0")
        _validate_finite(self.y0, "y0")
        _validate_finite(self.x1, "x1")
        _validate_finite(self.y1, "y1")
        if self.x0 > self.x1:
            raise ValueError(
                f"BoundingBox x0 ({self.x0}) > x1 ({self.x1})"
            )
        if self.y0 > self.y1:
            raise ValueError(
                f"BoundingBox y0 ({self.y0}) > y1 ({self.y1})"
            )
        # Normalized values must be in [0, 1]
        if self.coordinate_space == CoordinateSpace.NORMALIZED:
            for name, val in [("x0", self.x0), ("y0", self.y0),
                              ("x1", self.x1), ("y1", self.y1)]:
                if not (0.0 <= val <= 1.0):
                    raise ValueError(
                        f"Normalized coordinate {name}={val} out of range [0,1]"
                    )

    def width(self) -> float:
        return self.x1 - self.x0

    def height(self) -> float:
        return self.y1 - self.y0

    def to_dict(self) -> dict:
        return {
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
            "coordinate_space": self.coordinate_space.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BoundingBox":
        cs = CoordinateSpace(d.get("coordinate_space", "normalized"))
        return cls(
            x0=d["x0"], y0=d["y0"], x1=d["x1"], y1=d["y1"],
            coordinate_space=cs,
        )


@dataclass(frozen=True)
class Polygon:
    """Ordered list of (x, y) vertices forming a polygon.

    All values must be finite.  At least 3 vertices are required.
    Bounds validation for normalized coordinates applies to every vertex.
    """

    points: Tuple[Tuple[float, float], ...] = field(default_factory=tuple)
    coordinate_space: CoordinateSpace = CoordinateSpace.NORMALIZED

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError(
                f"Polygon requires at least 3 vertices, got {len(self.points)}"
            )
        for i, (x, y) in enumerate(self.points):
            _validate_finite(x, f"points[{i}].x")
            _validate_finite(y, f"points[{i}].y")
            if self.coordinate_space == CoordinateSpace.NORMALIZED:
                if not (0.0 <= x <= 1.0):
                    raise ValueError(
                        f"Normalized vertex {i} x={x} out of range [0,1]"
                    )
                if not (0.0 <= y <= 1.0):
                    raise ValueError(
                        f"Normalized vertex {i} y={y} out of range [0,1]"
                    )

    def to_dict(self) -> dict:
        return {
            "points": list(self.points),
            "coordinate_space": self.coordinate_space.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Polygon":
        cs = CoordinateSpace(d.get("coordinate_space", "normalized"))
        pts = tuple(tuple(p) for p in d["points"])
        return cls(points=pts, coordinate_space=cs)  # type: ignore[arg-type]

    def bounding_box(self) -> BoundingBox:
        """Compute the axis-aligned bounding box of this polygon."""
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return BoundingBox(
            x0=min(xs), y0=min(ys),
            x1=max(xs), y1=max(ys),
            coordinate_space=self.coordinate_space,
        )


# ---------------------------------------------------------------------------
# ReadingOrder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadingOrder:
    """Per-unit reading order as an ordered list of stable block IDs."""

    block_ids: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> list:
        return list(self.block_ids)

    @classmethod
    def from_dict(cls, items: list) -> "ReadingOrder":
        return cls(block_ids=tuple(str(i) for i in items))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_finite(val: float, name: str) -> None:
    import math
    if math.isnan(val):
        raise ValueError(f"{name} is NaN")
    if math.isinf(val):
        raise ValueError(f"{name} is infinite ({val})")
