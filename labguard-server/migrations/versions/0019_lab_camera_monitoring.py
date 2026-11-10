"""Add room cameras and object detection events."""
from alembic import op
import sqlalchemy as sa


revision = "0019_lab_camera_monitoring"
down_revision = "0018_exam_screenshot_bursts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lab_cameras",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("stream_uri_encrypted", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("last_frame_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lab_cameras_room_id", "lab_cameras", ["room_id"])
    op.create_index("ix_lab_cameras_enabled", "lab_cameras", ["enabled"])
    op.create_index("ix_lab_cameras_room_enabled", "lab_cameras", ["room_id", "enabled"])
    op.create_table(
        "lab_camera_detections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["lab_cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lab_camera_detections_camera_id", "lab_camera_detections", ["camera_id"])
    op.create_index("ix_lab_camera_detections_room_id", "lab_camera_detections", ["room_id"])
    op.create_index("ix_lab_camera_detections_label", "lab_camera_detections", ["label"])
    op.create_index("ix_lab_camera_detections_occurred_at", "lab_camera_detections", ["occurred_at"])
    op.create_index("ix_lab_camera_detections_room_time", "lab_camera_detections", ["room_id", "occurred_at"])
    op.create_index("ix_lab_camera_detections_camera_time", "lab_camera_detections", ["camera_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("lab_camera_detections")
    op.drop_table("lab_cameras")
