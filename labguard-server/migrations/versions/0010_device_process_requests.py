"""Persist authorized process inventory and termination requests.

Revision ID: 0010_device_process_requests
Revises: 0009_rdp_username
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_device_process_requests"
down_revision = "0009_rdp_username"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_process_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("target_pid", sa.Integer(), nullable=True),
        sa.Column("target_created_at_us", sa.BigInteger(), nullable=True),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.Column("process_items", sa.JSON(), nullable=True),
        sa.Column("received_batches", sa.JSON(), nullable=True),
        sa.Column("batch_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("operation IN ('LIST', 'TERMINATE', 'KILL')", name="ck_device_process_requests_operation"),
        sa.CheckConstraint("status IN ('PENDING', 'COMPLETE', 'FAILED', 'EXPIRED')", name="ck_device_process_requests_status"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["administrators.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_process_requests_device_id", "device_process_requests", ["device_id"])
    op.create_index("ix_device_process_requests_requested_by", "device_process_requests", ["requested_by"])
    op.create_index("ix_device_process_requests_status", "device_process_requests", ["status"])
    op.create_index("ix_device_process_requests_created_at", "device_process_requests", ["created_at"])
    op.create_index("ix_device_process_requests_expires_at", "device_process_requests", ["expires_at"])
    op.create_index("ix_device_process_requests_device_status", "device_process_requests", ["device_id", "status"])


def downgrade():
    op.drop_index("ix_device_process_requests_device_status", table_name="device_process_requests")
    op.drop_index("ix_device_process_requests_expires_at", table_name="device_process_requests")
    op.drop_index("ix_device_process_requests_created_at", table_name="device_process_requests")
    op.drop_index("ix_device_process_requests_status", table_name="device_process_requests")
    op.drop_index("ix_device_process_requests_requested_by", table_name="device_process_requests")
    op.drop_index("ix_device_process_requests_device_id", table_name="device_process_requests")
    op.drop_table("device_process_requests")
