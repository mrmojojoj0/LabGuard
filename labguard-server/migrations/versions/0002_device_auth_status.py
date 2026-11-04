"""Device proof-of-possession tickets and persisted heartbeat status.

Revision ID: 0002_device_auth_status
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

from labguard_server.db import Base
from labguard_server import models  # noqa: F401

revision = "0002_device_auth_status"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("devices", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_devices_last_seen_at", "devices", ["last_seen_at"])
    # Create only the new tables; existing tables are migrated explicitly above.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in ("device_tickets", "device_auth_challenges", "device_status_events", "device_status", "device_credentials"):
        op.drop_table(table)
    op.drop_index("ix_devices_last_seen_at", table_name="devices")
    op.drop_column("devices", "last_seen_at")
