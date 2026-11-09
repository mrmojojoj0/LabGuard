"""Store bounded active network connection snapshots.

Revision ID: 0012_network_connections
Revises: 0011_telemetry_usernames
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_network_connections"
down_revision = "0011_telemetry_usernames"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("device_telemetry_latest", sa.Column("network_connections", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("device_telemetry_latest", "network_connections")
