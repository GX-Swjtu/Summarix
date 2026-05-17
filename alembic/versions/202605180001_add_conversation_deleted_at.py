"""为会话增加软删除时间

Revision ID: 202605180001
Revises: 202605170001
Create Date: 2026-05-18 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202605180001"
down_revision: str | Sequence[str] | None = "202605170001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "deleted_at")