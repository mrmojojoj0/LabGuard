"""Initial server foundation schema.

Revision ID: 0001_initial
"""
from alembic import op

from sqlalchemy import MetaData
from labguard_server.db import Base
from labguard_server import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Freeze the original Phase 1 schema. Later revisions add models/columns;
    # do not let today's ORM metadata leak those changes into this revision.
    initial = MetaData()
    names = ("administrators", "admin_sessions", "enrollment_codes", "devices", "rooms",
             "device_positions", "audit_events")
    for name in names:
        cloned = Base.metadata.tables[name].to_metadata(initial)
        if name == "devices":
            for index in list(cloned.indexes):
                if any(column.name == "last_seen_at" for column in index.columns):
                    cloned.indexes.remove(index)
            cloned._columns.remove(cloned.c.last_seen_at)
    initial.create_all(bind=op.get_bind())


def downgrade():
    for name in ("audit_events", "device_positions", "rooms", "devices", "enrollment_codes", "admin_sessions", "administrators"):
        op.drop_table(name)
