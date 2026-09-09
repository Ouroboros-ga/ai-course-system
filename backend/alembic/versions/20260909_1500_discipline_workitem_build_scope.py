"""CR2 工作项幂等键改 build 级：跨批次各自拥有工作项，向量经缓存复用。

Revision ID: dk20260909v2
Revises: dk20260909v1
Create Date: 2026-09-08
Batch: dk20260909v2

背景（计划 §2.2-7）：旧唯一键 ``(stage, fingerprint)`` 全局唯一，
新批次规划增量时可能命中旧批次拥有的工作项，导致新批次没有自己的
工作项。改为 ``(build_id, stage, fingerprint)`` 后，每批次拥有自己的
工作身份；跨批次复用走 ``discipline_corpus_vectors`` 的
``unique(model_fingerprint, input_hash)`` 缓存，不走工作项复用。

方向说明：本次是约束放宽（旧库满足旧约束则必然满足新约束），upgrade
无数据风险；downgrade（收紧）若已存在跨 build 同键会失败，届时需先
清理，此为预期行为。
"""

from __future__ import annotations

from alembic import op

revision = "dk20260909v2"
down_revision = "dk20260909v1"
branch_labels = None
depends_on = None

BATCH_ID = "dk20260909v2"


def upgrade() -> None:
    # SQLite 不支持原生 ALTER 约束，走 batch 模式（PG 下同样兼容）。
    with op.batch_alter_table("discipline_work_items") as batch:
        batch.drop_constraint(
            "uq_discipline_work_stage_fp", type_="unique")
        batch.create_unique_constraint(
            "uq_discipline_work_build_stage_fp",
            ["build_id", "stage", "fingerprint"])


def downgrade() -> None:
    with op.batch_alter_table("discipline_work_items") as batch:
        batch.drop_constraint(
            "uq_discipline_work_build_stage_fp", type_="unique")
        batch.create_unique_constraint(
            "uq_discipline_work_stage_fp", ["stage", "fingerprint"])
