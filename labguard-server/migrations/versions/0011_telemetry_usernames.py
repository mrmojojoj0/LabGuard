"""Persist endpoint-reported console and agent account names.

Revision ID: 0011_telemetry_usernames
Revises: 0010_device_process_requests
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_telemetry_usernames"
down_revision = "0010_device_process_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("device_telemetry_latest", sa.Column("username", sa.String(length=256), nullable=True))
    op.add_column("device_telemetry_latest", sa.Column("agent_account", sa.String(length=256), nullable=True))


def downgrade():
    op.drop_column("device_telemetry_latest", "agent_account")
    op.drop_column("device_telemetry_latest", "username")
