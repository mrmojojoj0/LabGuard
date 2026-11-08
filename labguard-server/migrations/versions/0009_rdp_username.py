"""Store the endpoint-reported RDP account name.

Revision ID: 0009_rdp_username
Revises: 0008_rdp_access_requests
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_rdp_username"
down_revision = "0008_rdp_access_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rdp_access_requests", sa.Column("rdp_username", sa.String(length=256), nullable=True))


def downgrade():
    op.drop_column("rdp_access_requests", "rdp_username")
