"""Add scheduled exams, policies, and violation evidence metadata.

Revision ID: 0017_exam_management
Revises: 0016_screenshot_captures
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_exam_management"
down_revision = "0016_screenshot_captures"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("device_ids", sa.JSON(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED')", name="ck_exams_status"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_exams_time_range"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["administrators.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, column in (("room_id", "room_id"), ("starts_at", "starts_at"),
                         ("ends_at", "ends_at"), ("status", "status")):
        op.create_index(f"ix_exams_{name}", "exams", [column])
    op.create_index("ix_exams_schedule", "exams", ["status", "starts_at", "ends_at"])
    op.create_table(
        "exam_violations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id", "event_key", name="uq_exam_violation_event"),
    )
    for name, column in (("exam_id", "exam_id"), ("device_id", "device_id"),
                         ("kind", "kind"), ("occurred_at", "occurred_at")):
        op.create_index(f"ix_exam_violations_{name}", "exam_violations", [column])
    op.create_index("ix_exam_violations_exam_time", "exam_violations", ["exam_id", "occurred_at"])


def downgrade():
    op.drop_index("ix_exam_violations_exam_time", table_name="exam_violations")
    for name in ("occurred_at", "kind", "device_id", "exam_id"):
        op.drop_index(f"ix_exam_violations_{name}", table_name="exam_violations")
    op.drop_table("exam_violations")
    op.drop_index("ix_exams_schedule", table_name="exams")
    for name in ("status", "ends_at", "starts_at", "room_id"):
        op.drop_index(f"ix_exams_{name}", table_name="exams")
    op.drop_table("exams")
