"""Store administrator-requested endpoint screenshots.

Revision ID: 0016_screenshot_captures
Revises: 0015_wfp_remote_address_fields
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_screenshot_captures"
down_revision = "0015_wfp_remote_address_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "screenshot_captures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("image_size_bytes", sa.Integer(), nullable=True),
        sa.Column("image_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('PENDING', 'READY', 'FAILED', 'EXPIRED')", name="ck_screenshot_captures_status"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["administrators.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, column in (("device_id", "device_id"), ("requested_by", "requested_by"),
                         ("status", "status"), ("created_at", "created_at"), ("expires_at", "expires_at")):
        op.create_index(f"ix_screenshot_captures_{name}", "screenshot_captures", [column])
    op.create_index("ix_screenshot_captures_device_created", "screenshot_captures", ["device_id", "created_at"])


def downgrade():
    op.drop_index("ix_screenshot_captures_device_created", table_name="screenshot_captures")
    for name in ("expires_at", "created_at", "status", "requested_by", "device_id"):
        op.drop_index(f"ix_screenshot_captures_{name}", table_name="screenshot_captures")
    op.drop_table("screenshot_captures")
