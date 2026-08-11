"""Regression for PostgreSQL's SQLAlchemy enum-name storage contract."""
from __future__ import annotations

import unittest

from sqlalchemy import Column, MetaData, Table
from sqlalchemy import Enum as SAEnum

from app.scripts import sqlite_to_postgres as transfer


class PostgresEnumTransferRegressionTests(unittest.TestCase):
    def test_legacy_enum_members_stay_compatible_with_orm_reads(self) -> None:
        """A transfer must keep the enum member names that SQLAlchemy reads."""
        metadata = MetaData()
        assets = Table(
            "evidence_render_assets",
            metadata,
            Column(
                "asset_type",
                SAEnum(
                    "PAGE_IMAGE", "PPT_SLIDE_IMAGE", "REGION_IMAGE", "THUMBNAIL",
                    "page_image", "ppt_slide_image", "region_image", "thumbnail",
                    name="renderassettype",
                ),
            ),
        )
        versions = Table(
            "source_material_versions",
            metadata,
            Column(
                "parse_status",
                SAEnum(
                    "UPLOADED", "PARSING", "PARSED", "NEEDS_REVIEW", "FAILED", "SUPERSEDED",
                    "uploaded", "parsing", "parsed", "needs_review", "failed", "superseded",
                    name="materialstatus",
                ),
            ),
        )
        materials = Table(
            "source_materials",
            metadata,
            Column(
                "status",
                SAEnum(
                    "UPLOADED", "PARSING", "PARSED", "NEEDS_REVIEW", "FAILED", "SUPERSEDED",
                    "uploaded", "parsing", "parsed", "needs_review", "failed", "superseded",
                    name="materialstatus",
                ),
            ),
        )

        self.assertEqual("PPT_SLIDE_IMAGE", transfer._coerce_value("PPT_SLIDE_IMAGE", assets.c.asset_type))
        self.assertEqual("NEEDS_REVIEW", transfer._coerce_value("NEEDS_REVIEW", versions.c.parse_status))
        self.assertEqual("PARSING", transfer._coerce_value("PARSING", materials.c.status))
