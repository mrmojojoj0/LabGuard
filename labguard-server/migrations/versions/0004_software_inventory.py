"""Authenticated, versioned Windows software inventory.

Revision ID: 0004_software_inventory
Revises: 0003_system_telemetry
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_software_inventory"
down_revision = "0003_system_telemetry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "software_inventory_collections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.Uuid()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expected_batches", sa.Integer(), nullable=False),
        sa.Column("received_batches", sa.Integer(), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("inventory_digest", sa.String(64), nullable=False),
    )
    op.create_index("ix_software_inventory_collections_device_id", "software_inventory_collections", ["device_id"])
    op.create_index("ix_software_inventory_collections_request_id", "software_inventory_collections", ["request_id"])
    op.create_index("ix_software_inventory_collections_status", "software_inventory_collections", ["status"])
    op.create_index("ix_software_collection_device_started", "software_inventory_collections", ["device_id", "started_at"])
    op.create_index("ix_software_collection_device_received", "software_inventory_collections", ["device_id", "received_at"])

    op.create_table(
        "software_inventory_batch_receipts",
        sa.Column("collection_id", sa.Uuid(), sa.ForeignKey("software_inventory_collections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("batch_index", sa.Integer(), primary_key=True),
        sa.Column("item_count", sa.Integer(), nullable=False),
    )

    op.create_table(
        "software_inventory_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_key", sa.String(64), nullable=False),
        sa.Column("product_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("version", sa.String(128)),
        sa.Column("publisher", sa.String(256)),
        sa.Column("architecture", sa.String(32), nullable=False),
        sa.Column("install_date", sa.String(10)),
        sa.Column("install_location", sa.String(1024)),
        sa.Column("package_id", sa.String(256)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("installation_scope", sa.String(16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_present", sa.Boolean(), nullable=False),
        sa.Column("missing_since", sa.DateTime(timezone=True)),
        sa.Column("last_collection_id", sa.Uuid(), sa.ForeignKey("software_inventory_collections.id", ondelete="SET NULL")),
        sa.UniqueConstraint("device_id", "entry_key", name="uq_software_inventory_device_entry"),
    )
    for column in ("device_id", "product_key", "name", "publisher", "package_id", "source", "installation_scope",
                   "last_seen_at", "is_present", "last_collection_id"):
        op.create_index(f"ix_software_inventory_items_{column}", "software_inventory_items", [column])
    op.create_index("ix_software_inventory_product_present", "software_inventory_items", ["product_key", "is_present"])
    op.create_index("ix_software_inventory_device_present", "software_inventory_items", ["device_id", "is_present"])


def downgrade():
    op.drop_index("ix_software_inventory_device_present", table_name="software_inventory_items")
    op.drop_index("ix_software_inventory_product_present", table_name="software_inventory_items")
    for column in ("last_collection_id", "is_present", "last_seen_at", "installation_scope", "source", "package_id",
                   "publisher", "name", "product_key", "device_id"):
        op.drop_index(f"ix_software_inventory_items_{column}", table_name="software_inventory_items")
    op.drop_table("software_inventory_items")
    op.drop_table("software_inventory_batch_receipts")
    op.drop_index("ix_software_collection_device_started", table_name="software_inventory_collections")
    op.drop_index("ix_software_collection_device_received", table_name="software_inventory_collections")
    op.drop_index("ix_software_inventory_collections_status", table_name="software_inventory_collections")
    op.drop_index("ix_software_inventory_collections_request_id", table_name="software_inventory_collections")
    op.drop_index("ix_software_inventory_collections_device_id", table_name="software_inventory_collections")
    op.drop_table("software_inventory_collections")
