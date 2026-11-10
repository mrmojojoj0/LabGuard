"""Add indexed remote-address fields used by WFP event ingestion and filtering.

Revision ID: 0015_wfp_remote_address_fields
Revises: 0014_wfp_connection_events
"""
from ipaddress import ip_address

from alembic import op
import sqlalchemy as sa


revision = "0015_wfp_remote_address_fields"
down_revision = "0014_wfp_connection_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("device_wfp_events", sa.Column("remote_ip", sa.String(45), nullable=True))
    op.add_column("device_wfp_events", sa.Column("remote_is_public", sa.Boolean(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, direction, source_ip, destination_ip FROM device_wfp_events"
    ))
    update = sa.text(
        "UPDATE device_wfp_events SET remote_ip = :remote_ip, "
        "remote_is_public = :remote_is_public WHERE id = :row_id"
    )
    while True:
        page = rows.fetchmany(1000)
        if not page:
            break
        values = []
        for row in page:
            remote_ip = row.source_ip if row.direction == "INCOMING" else row.destination_ip
            try:
                is_public = ip_address(remote_ip).is_global
            except ValueError:
                is_public = False
            values.append({"row_id": row.id, "remote_ip": remote_ip,
                           "remote_is_public": is_public})
        bind.execute(update, values)

    with op.batch_alter_table("device_wfp_events") as batch:
        batch.alter_column("remote_ip", existing_type=sa.String(45), nullable=False)
        batch.alter_column("remote_is_public", existing_type=sa.Boolean(), nullable=False,
                           server_default=sa.false())

    op.create_index("ix_wfp_public_occurred", "device_wfp_events",
                    ["remote_is_public", "occurred_at"])


def downgrade():
    op.drop_index("ix_wfp_public_occurred", table_name="device_wfp_events")
    with op.batch_alter_table("device_wfp_events") as batch:
        batch.drop_column("remote_is_public")
        batch.drop_column("remote_ip")
