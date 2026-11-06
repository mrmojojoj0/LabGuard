"""Approved package catalog and typed individual software jobs.

Revision ID: 0005_software_jobs
Revises: 0004_software_inventory
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_software_jobs"
down_revision = "0004_software_inventory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "software_catalog_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("package_id", sa.String(256), nullable=False),
        sa.Column("package_manager", sa.String(16), nullable=False),
        sa.Column("publisher", sa.String(256)),
        sa.Column("description", sa.String(1000)),
        sa.Column("version_policy", sa.String(16), nullable=False),
        sa.Column("approved_version", sa.String(128)),
        sa.Column("supported_scopes", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("administrators.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("package_manager", "package_id", name="uq_software_catalog_manager_id"),
    )
    op.create_index("ix_software_catalog_packages_package_manager", "software_catalog_packages", ["package_manager"])
    op.create_index("ix_software_catalog_packages_approved", "software_catalog_packages", ["approved"])

    op.create_table(
        "software_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("catalog_package_id", sa.Uuid(), sa.ForeignKey("software_catalog_packages.id", ondelete="SET NULL")),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("administrators.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("package_id", sa.String(256), nullable=False),
        sa.Column("package_manager", sa.String(16), nullable=False),
        sa.Column("requested_version", sa.String(128)),
        sa.Column("installation_scope", sa.String(16), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("progress_message", sa.String(256)),
        sa.Column("result_code", sa.String(64)),
        sa.Column("result_summary", sa.String(1000)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for column in ("device_id", "catalog_package_id", "status"):
        op.create_index(f"ix_software_jobs_{column}", "software_jobs", [column])
    op.create_index("ix_software_jobs_device_status_created", "software_jobs", ["device_id", "status", "created_at"])
    op.create_index("ix_software_jobs_status_expires", "software_jobs", ["status", "expires_at"])
    with op.batch_alter_table("software_inventory_collections") as batch:
        batch.add_column(sa.Column("job_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_software_inventory_collections_job_id_software_jobs",
            "software_jobs", ["job_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_software_inventory_collections_job_id", "software_inventory_collections", ["job_id"])


def downgrade():
    op.drop_index("ix_software_inventory_collections_job_id", table_name="software_inventory_collections")
    with op.batch_alter_table("software_inventory_collections") as batch:
        batch.drop_constraint("fk_software_inventory_collections_job_id_software_jobs", type_="foreignkey")
        batch.drop_column("job_id")
    op.drop_index("ix_software_jobs_status_expires", table_name="software_jobs")
    op.drop_index("ix_software_jobs_device_status_created", table_name="software_jobs")
    for column in ("status", "catalog_package_id", "device_id"):
        op.drop_index(f"ix_software_jobs_{column}", table_name="software_jobs")
    op.drop_table("software_jobs")
    op.drop_index("ix_software_catalog_packages_approved", table_name="software_catalog_packages")
    op.drop_index("ix_software_catalog_packages_package_manager", table_name="software_catalog_packages")
    op.drop_table("software_catalog_packages")
