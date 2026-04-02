"""add edit requests

Revision ID: 9c0f8b0f0f4d
Revises: f56fe2bf5f2a
Create Date: 2026-03-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c0f8b0f0f4d"
down_revision: str | Sequence[str] | None = "f56fe2bf5f2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edit_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_generation_id", sa.String(length=255), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("quality", sa.String(length=64), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=64), nullable=False),
        sa.Column("background", sa.String(length=64), nullable=False),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("credit_cost", sa.Integer(), nullable=True),
        sa.Column("svg_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_edit_requests_account_id"),
        "edit_requests",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_edit_requests_external_generation_id"),
        "edit_requests",
        ["external_generation_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_edit_requests_source_mode"),
        "edit_requests",
        ["source_mode"],
        unique=False,
    )
    op.create_index(
        op.f("ix_edit_requests_status"),
        "edit_requests",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_edit_requests_status"), table_name="edit_requests")
    op.drop_index(op.f("ix_edit_requests_source_mode"), table_name="edit_requests")
    op.drop_index(op.f("ix_edit_requests_external_generation_id"), table_name="edit_requests")
    op.drop_index(op.f("ix_edit_requests_account_id"), table_name="edit_requests")
    op.drop_table("edit_requests")
