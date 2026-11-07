"""Store all sources contributing to a reconciled inventory installation.

Revision ID: 0007_inventory_discovery_sources
Revises: 0006_catalog_review_status
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_inventory_discovery_sources"
down_revision = "0006_catalog_review_status"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("software_inventory_items") as batch:
        batch.add_column(sa.Column("discovery_sources", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("software_inventory_items") as batch:
        batch.drop_column("discovery_sources")
