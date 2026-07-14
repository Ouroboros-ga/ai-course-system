"""Tests for Geometry types: BoundingBox, Polygon, CoordinateSpace, ReadingOrder."""

import math

import pytest

from app.platform.document_intelligence.contracts import (
    BoundingBox,
    CoordinateSpace,
    CURRENT_SCHEMA_VERSION,
    Polygon,
    ReadingOrder,
    SchemaVersion,
)


# ---------------------------------------------------------------------------
# SchemaVersion
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_parse_valid(self) -> None:
        sv = SchemaVersion.parse("document-ir/1.2.3")
        assert sv.major == 1
        assert sv.minor == 2
        assert sv.patch == 3

    def test_serialize_round_trip(self) -> None:
        assert SchemaVersion.parse("document-ir/1.0.0").serialize() == "document-ir/1.0.0"

    def test_unknown_major_parsed_but_incompatible(self) -> None:
        """SchemaVersion parses any major; fail-closed happens at deserialization."""
        sv = SchemaVersion.parse("document-ir/99.0.0")
        assert sv.major == 99
        assert not sv.is_compatible_with(1)

    def test_malformed_rejected(self) -> None:
        for bad in ["", "doc/1.0", "document-ir/abc", "document-ir/1.x.0"]:
            with pytest.raises(ValueError):
                SchemaVersion.parse(bad)

    def test_is_compatible(self) -> None:
        sv = SchemaVersion.parse("document-ir/1.0.0")
        assert sv.is_compatible_with(1)
        assert sv.is_compatible_with(2)
        assert not sv.is_compatible_with(0)

    def test_current_version(self) -> None:
        assert CURRENT_SCHEMA_VERSION.major == 1
        assert CURRENT_SCHEMA_VERSION.serialize() == "document-ir/1.0.0"

    def test_str(self) -> None:
        assert str(CURRENT_SCHEMA_VERSION) == "document-ir/1.0.0"


# ---------------------------------------------------------------------------
# BoundingBox
# ---------------------------------------------------------------------------


class TestBoundingBox:
    def test_valid_normalized(self) -> None:
        bbox = BoundingBox(0.1, 0.2, 0.8, 0.9)
        assert bbox.x0 == 0.1
        assert bbox.y0 == 0.2
        assert bbox.x1 == 0.8
        assert bbox.y1 == 0.9
        assert bbox.width() == pytest.approx(0.7)
        assert bbox.height() == pytest.approx(0.7)

    def test_zero_size_allowed(self) -> None:
        bbox = BoundingBox(0.5, 0.5, 0.5, 0.5)
        assert bbox.width() == 0.0
        assert bbox.height() == 0.0

    def test_x0_greater_than_x1_raises(self) -> None:
        with pytest.raises(ValueError, match="x0.*>.*x1"):
            BoundingBox(0.8, 0.2, 0.1, 0.9)

    def test_y0_greater_than_y1_raises(self) -> None:
        with pytest.raises(ValueError, match="y0.*>.*y1"):
            BoundingBox(0.1, 0.9, 0.8, 0.2)

    def test_normalized_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            BoundingBox(-0.1, 0.0, 0.5, 0.5)
        with pytest.raises(ValueError, match="out of range"):
            BoundingBox(0.0, 0.0, 1.5, 0.5)
        with pytest.raises(ValueError, match="out of range"):
            BoundingBox(0.0, -0.1, 0.5, 0.5)
        with pytest.raises(ValueError, match="out of range"):
            BoundingBox(0.0, 0.0, 0.5, 1.5)

    def test_non_normalized_allows_any_range(self) -> None:
        bbox = BoundingBox(0, 0, 1920, 1080, coordinate_space=CoordinateSpace.PIXEL)
        assert bbox.width() == 1920
        assert bbox.height() == 1080

    def test_nan_raises(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            BoundingBox(math.nan, 0.0, 1.0, 1.0)

    def test_inf_raises(self) -> None:
        with pytest.raises(ValueError, match="infinite"):
            BoundingBox(0.0, 0.0, float("inf"), 1.0)

    def test_to_dict_round_trip(self) -> None:
        bbox = BoundingBox(0.1, 0.2, 0.8, 0.9)
        d = bbox.to_dict()
        restored = BoundingBox.from_dict(d)
        assert restored == bbox

    def test_from_dict_default_coordinate_space(self) -> None:
        d = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
        bbox = BoundingBox.from_dict(d)
        assert bbox.coordinate_space == CoordinateSpace.NORMALIZED

    def test_explicit_coordinate_space(self) -> None:
        bbox = BoundingBox(0, 0, 100, 200, coordinate_space=CoordinateSpace.MILLIMETER)
        d = bbox.to_dict()
        assert d["coordinate_space"] == "millimeter"
        restored = BoundingBox.from_dict(d)
        assert restored.coordinate_space == CoordinateSpace.MILLIMETER


# ---------------------------------------------------------------------------
# Polygon
# ---------------------------------------------------------------------------


class TestPolygon:
    def test_valid_triangle(self) -> None:
        poly = Polygon(
            points=((0.1, 0.1), (0.5, 0.1), (0.3, 0.5)),
        )
        assert len(poly.points) == 3

    def test_fewer_than_3_points_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            Polygon(points=((0.1, 0.1), (0.5, 0.5)))

    def test_normalized_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            Polygon(points=((-0.1, 0.0), (0.5, 0.0), (0.3, 0.5)))

    def test_non_normalized_allows_any(self) -> None:
        poly = Polygon(
            points=((100, 200), (300, 200), (250, 400)),
            coordinate_space=CoordinateSpace.PIXEL,
        )
        assert len(poly.points) == 3

    def test_bounding_box(self) -> None:
        poly = Polygon(
            points=((0.1, 0.2), (0.8, 0.2), (0.8, 0.9), (0.1, 0.9)),
        )
        bbox = poly.bounding_box()
        assert bbox.x0 == pytest.approx(0.1)
        assert bbox.y0 == pytest.approx(0.2)
        assert bbox.x1 == pytest.approx(0.8)
        assert bbox.y1 == pytest.approx(0.9)

    def test_to_dict_round_trip(self) -> None:
        poly = Polygon(
            points=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
        )
        d = poly.to_dict()
        restored = Polygon.from_dict(d)
        assert restored == poly

    def test_nan_vertex_raises(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            Polygon(points=((0.0, 0.0), (math.nan, 0.5), (1.0, 1.0)))


# ---------------------------------------------------------------------------
# ReadingOrder
# ---------------------------------------------------------------------------


class TestReadingOrder:
    def test_empty(self) -> None:
        ro = ReadingOrder()
        assert ro.block_ids == ()
        assert ro.to_dict() == []

    def test_with_ids(self) -> None:
        ro = ReadingOrder(block_ids=("blk_a", "blk_b", "blk_c"))
        assert ro.to_dict() == ["blk_a", "blk_b", "blk_c"]

    def test_round_trip(self) -> None:
        ro = ReadingOrder(block_ids=("x", "y", "z"))
        restored = ReadingOrder.from_dict(ro.to_dict())
        assert restored == ro
