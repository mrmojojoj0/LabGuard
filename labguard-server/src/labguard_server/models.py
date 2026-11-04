from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labguard_server.db import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Administrator(Base):
    __tablename__ = "administrators"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="VIEWER")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    administrator_id: Mapped[UUID] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("administrators.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    assigned_name: Mapped[str | None] = mapped_column(String(100), unique=True)
    hostname: Mapped[str] = mapped_column(String(255))
    public_key: Mapped[str] = mapped_column(Text)
    enrollment_state: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class DeviceCredential(Base):
    __tablename__ = "device_credentials"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceStatus(Base):
    __tablename__ = "device_status"
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    agent_state: Mapped[str] = mapped_column(String(20), default="NEVER_CONNECTED", index=True)
    network_state: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)


class DeviceStatusEvent(Base):
    __tablename__ = "device_status_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    previous_state: Mapped[str] = mapped_column(String(20))
    new_state: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(String(50))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class DeviceTelemetryLatest(Base):
    __tablename__ = "device_telemetry_latest"
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processor_name: Mapped[str | None] = mapped_column(String(256))
    logical_processors: Mapped[int] = mapped_column(Integer)
    physical_cores: Mapped[int | None] = mapped_column(Integer)
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_used_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_available_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_percent: Mapped[float] = mapped_column(Float)
    storage_partitions: Mapped[list] = mapped_column(JSON)
    windows_edition: Mapped[str | None] = mapped_column(String(128))
    os_version: Mapped[str | None] = mapped_column(String(128))
    build_number: Mapped[str | None] = mapped_column(String(64))
    architecture: Mapped[str] = mapped_column(String(64))
    hostname: Mapped[str] = mapped_column(String(255))
    boot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    uptime_seconds: Mapped[float] = mapped_column(Float)
    network_interfaces: Mapped[list] = mapped_column(JSON)


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"
    __table_args__ = (Index("ix_telemetry_device_received", "device_id", "received_at"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_used_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_percent: Mapped[float] = mapped_column(Float)
    disk_used_bytes: Mapped[int] = mapped_column(BigInteger)
    disk_total_bytes: Mapped[int] = mapped_column(BigInteger)
    disk_percent: Mapped[float | None] = mapped_column(Float)


class DeviceAuthChallenge(Base):
    __tablename__ = "device_auth_challenges"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceTicket(Base):
    __tablename__ = "device_tickets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (CheckConstraint("grid_rows > 0 AND grid_columns > 0", name="ck_rooms_grid_positive"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    grid_rows: Mapped[int] = mapped_column(Integer, default=5)
    grid_columns: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    positions: Mapped[list["DevicePosition"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class DevicePosition(Base):
    __tablename__ = "device_positions"
    __table_args__ = (UniqueConstraint("room_id", "row_index", "column_index", name="uq_room_grid_cell"),)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    row_index: Mapped[int] = mapped_column(Integer)
    column_index: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    room: Mapped[Room] = relationship(back_populates="positions")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(20), default="SUCCESS")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text)
