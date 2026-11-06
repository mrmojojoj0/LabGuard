"""Track explicit review decisions for software catalog packages.

Revision ID: 0006_catalog_review_status
Revises: 0005_software_jobs
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_catalog_review_status"
down_revision = "0005_software_jobs"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("software_catalog_packages") as batch:
        batch.add_column(sa.Column(
            "approval_status", sa.String(16), nullable=False, server_default="PENDING"))
    op.create_index("ix_software_catalog_packages_approval_status",
                    "software_catalog_packages", ["approval_status"])
    packages = sa.table("software_catalog_packages",
        sa.column("approved", sa.Boolean()), sa.column("approval_status", sa.String(16)))
    op.execute(packages.update().where(packages.c.approved.is_(True)).values(approval_status="APPROVED"))


def downgrade():
    op.drop_index("ix_software_catalog_packages_approval_status", table_name="software_catalog_packages")
    with op.batch_alter_table("software_catalog_packages") as batch:
        batch.drop_column("approval_status")
