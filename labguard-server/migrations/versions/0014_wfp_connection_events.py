"""Persist Windows Filtering Platform connection events and collection state.

Revision ID: 0014_wfp_connection_events
Revises: 0013_peripheral_activity
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_wfp_connection_events"
down_revision = "0013_peripheral_activity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_wfp_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("log_generation", sa.String(36), nullable=False),
        sa.Column("event_record_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_kind", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("protocol_number", sa.Integer(), nullable=False),
        sa.Column("source_ip", sa.String(45), nullable=False),
        sa.Column("source_port", sa.Integer(), nullable=True),
        sa.Column("destination_ip", sa.String(45), nullable=False),
        sa.Column("destination_port", sa.Integer(), nullable=True),
        sa.Column("remote_ip", sa.String(45), nullable=False),
        sa.Column("remote_is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("process_id", sa.BigInteger(), nullable=True),
        sa.Column("process_path", sa.String(1024), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "log_generation", "event_record_id",
                            name="uq_wfp_device_generation_record"),
    )
    op.create_index("ix_device_wfp_events_device_id", "device_wfp_events", ["device_id"])
    op.create_index("ix_device_wfp_events_occurred_at", "device_wfp_events", ["occurred_at"])
    op.create_index("ix_wfp_device_occurred", "device_wfp_events", ["device_id", "occurred_at"])
    op.create_index("ix_wfp_occurred", "device_wfp_events", ["occurred_at"])
    op.create_index("ix_wfp_public_occurred", "device_wfp_events", ["remote_is_public", "occurred_at"])
    op.create_table(
        "device_wfp_states",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("log_generation", sa.String(36), nullable=True),
        sa.Column("cursor_record_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("gap_reason", sa.String(32), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )


def downgrade():
    op.drop_table("device_wfp_states")
    op.drop_index("ix_wfp_public_occurred", table_name="device_wfp_events")
    op.drop_index("ix_wfp_occurred", table_name="device_wfp_events")
    op.drop_index("ix_wfp_device_occurred", table_name="device_wfp_events")
    op.drop_index("ix_device_wfp_events_occurred_at", table_name="device_wfp_events")
    op.drop_index("ix_device_wfp_events_device_id", table_name="device_wfp_events")
    op.drop_table("device_wfp_events")
