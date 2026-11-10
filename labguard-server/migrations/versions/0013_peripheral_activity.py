"""Track endpoint peripheral presence and connection history.

Revision ID: 0013_peripheral_activity
Revises: 0012_network_connections
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_peripheral_activity"
down_revision = "0012_network_connections"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_peripheral_snapshots",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_index("ix_device_peripheral_snapshots_received_at", "device_peripheral_snapshots", ["received_at"])
    op.create_table(
        "device_peripherals",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("device_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("is_storage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "device_key"),
    )
    op.create_index("ix_device_peripherals_connected", "device_peripherals", ["device_id", "connected"])
    op.create_index("ix_device_peripherals_connected_flag", "device_peripherals", ["connected"])
    op.create_index("ix_device_peripherals_changed_at", "device_peripherals", ["changed_at"])
    op.create_table(
        "device_peripheral_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("device_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("is_storage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_peripheral_events_device_id", "device_peripheral_events", ["device_id"])
    op.create_index("ix_device_peripheral_events_occurred_at", "device_peripheral_events", ["occurred_at"])
    op.create_index("ix_peripheral_events_device_time", "device_peripheral_events", ["device_id", "occurred_at"])


def downgrade():
    op.drop_index("ix_peripheral_events_device_time", table_name="device_peripheral_events")
    op.drop_index("ix_device_peripheral_events_occurred_at", table_name="device_peripheral_events")
    op.drop_index("ix_device_peripheral_events_device_id", table_name="device_peripheral_events")
    op.drop_table("device_peripheral_events")
    op.drop_index("ix_device_peripherals_changed_at", table_name="device_peripherals")
    op.drop_index("ix_device_peripherals_connected_flag", table_name="device_peripherals")
    op.drop_index("ix_device_peripherals_connected", table_name="device_peripherals")
    op.drop_table("device_peripherals")
    op.drop_index("ix_device_peripheral_snapshots_received_at", table_name="device_peripheral_snapshots")
    op.drop_table("device_peripheral_snapshots")
