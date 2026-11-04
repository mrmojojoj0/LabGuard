"""Authenticated system telemetry latest snapshot and retained samples.

Revision ID: 0003_system_telemetry
Revises: 0002_device_auth_status
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_system_telemetry"
down_revision = "0002_device_auth_status"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_telemetry_latest",
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processor_name", sa.String(256)),
        sa.Column("logical_processors", sa.Integer(), nullable=False),
        sa.Column("physical_cores", sa.Integer()),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_available_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_percent", sa.Float(), nullable=False),
        sa.Column("storage_partitions", sa.JSON(), nullable=False),
        sa.Column("windows_edition", sa.String(128)),
        sa.Column("os_version", sa.String(128)),
        sa.Column("build_number", sa.String(64)),
        sa.Column("architecture", sa.String(64), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("boot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uptime_seconds", sa.Float(), nullable=False),
        sa.Column("network_interfaces", sa.JSON(), nullable=False),
    )
    op.create_index("ix_device_telemetry_latest_received_at", "device_telemetry_latest", ["received_at"])
    op.create_table(
        "telemetry_samples",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_percent", sa.Float(), nullable=False),
        sa.Column("disk_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_percent", sa.Float()),
    )
    op.create_index("ix_telemetry_samples_device_id", "telemetry_samples", ["device_id"])
    op.create_index("ix_telemetry_device_received", "telemetry_samples", ["device_id", "received_at"])


def downgrade():
    op.drop_index("ix_telemetry_device_received", table_name="telemetry_samples")
    op.drop_index("ix_telemetry_samples_device_id", table_name="telemetry_samples")
    op.drop_table("telemetry_samples")
    op.drop_index("ix_device_telemetry_latest_received_at", table_name="device_telemetry_latest")
    op.drop_table("device_telemetry_latest")
