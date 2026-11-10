"""Schedule the four-capture evidence burst for exam violations.

Revision ID: 0018_exam_screenshot_bursts
Revises: 0017_exam_management
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_exam_screenshot_bursts"
down_revision = "0017_exam_management"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("screenshot_captures", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("screenshot_captures", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_screenshot_captures_scheduled_at", "screenshot_captures", ["scheduled_at"])


def downgrade():
    op.drop_index("ix_screenshot_captures_scheduled_at", table_name="screenshot_captures")
    op.drop_column("screenshot_captures", "dispatched_at")
    op.drop_column("screenshot_captures", "scheduled_at")
