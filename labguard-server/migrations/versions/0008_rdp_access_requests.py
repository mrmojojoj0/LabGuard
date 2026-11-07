"""Persist audited RDP preparation requests.

Revision ID: 0008_rdp_access_requests
Revises: 0007_inventory_discovery_sources
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_rdp_access_requests"
down_revision = "0007_inventory_discovery_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rdp_access_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'READY', 'FAILED', 'EXPIRED')", name="ck_rdp_access_requests_status"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["administrators.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rdp_access_requests_device_id", "rdp_access_requests", ["device_id"])
    op.create_index("ix_rdp_access_requests_requested_by", "rdp_access_requests", ["requested_by"])
    op.create_index("ix_rdp_access_requests_status", "rdp_access_requests", ["status"])
    op.create_index("ix_rdp_access_requests_created_at", "rdp_access_requests", ["created_at"])
    op.create_index("ix_rdp_access_requests_expires_at", "rdp_access_requests", ["expires_at"])
    op.create_index("ix_rdp_access_requests_access_expires_at", "rdp_access_requests", ["access_expires_at"])
    op.create_index("ix_rdp_access_requests_device_status", "rdp_access_requests", ["device_id", "status"])


def downgrade():
    op.drop_index("ix_rdp_access_requests_device_status", table_name="rdp_access_requests")
    op.drop_index("ix_rdp_access_requests_expires_at", table_name="rdp_access_requests")
    op.drop_index("ix_rdp_access_requests_access_expires_at", table_name="rdp_access_requests")
    op.drop_index("ix_rdp_access_requests_created_at", table_name="rdp_access_requests")
    op.drop_index("ix_rdp_access_requests_status", table_name="rdp_access_requests")
    op.drop_index("ix_rdp_access_requests_requested_by", table_name="rdp_access_requests")
    op.drop_index("ix_rdp_access_requests_device_id", table_name="rdp_access_requests")
    op.drop_table("rdp_access_requests")
