"""Add missing safety audit labels to the shared auditeventtype enum.

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-14 18:00:00

The historical baseline (0001) declared two distinct Python ``AuditEventType``
enums — course lifecycle (``course_lifecycle_model``) and safety
(``safety_policy_model``) — but both map to the same PostgreSQL enum type name
``auditeventtype``.  PostgreSQL created the type once with the lifecycle
labels, so every ``safety_audit_logs`` insert fails with
``InvalidTextRepresentation: invalid input value for enum auditeventtype``
(e.g. the sandbox-policy PUT that writes ``POLICY_CHANGE``).

This revision appends the missing safety labels to the shared type, following
the bounded-commit pattern of 0051 so the new labels are usable by later
transactions.
"""
from __future__ import annotations

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

SAFETY_AUDIT_LABELS = [
    "POLICY_CHANGE",
    "HIT",
    "PASS",
    "BLOCK",
    "CONFIRM",
    "SANDBOX_RUN",
    "SANDBOX_BLOCK",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # PostgreSQL rejects any use of a label until the transaction that added it
    # commits, so append each label in its own bounded commit.
    with op.get_context().autocommit_block():
        for label in SAFETY_AUDIT_LABELS:
            op.execute(
                f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{label}'"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        raise RuntimeError(
            "0059 appends PostgreSQL enum labels and cannot be safely "
            "downgraded; restore the prior database environment before "
            "resuming traffic instead"
        )
