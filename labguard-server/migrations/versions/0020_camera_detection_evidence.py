"""Add retained image evidence to camera detections."""
from alembic import op
import sqlalchemy as sa


revision = "0020_camera_detection_evidence"
down_revision = "0019_lab_camera_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_camera_detections", sa.Column("image_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("lab_camera_detections", "image_path")
