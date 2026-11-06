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


class SoftwareInventoryCollection(Base):
    __tablename__ = "software_inventory_collections"
    __table_args__ = (Index("ix_software_collection_device_started", "device_id", "started_at"),
                      Index("ix_software_collection_device_received", "device_id", "received_at"))
    id: Mapped[UUID] = mapped_column(primary_key=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[UUID | None] = mapped_column(index=True)
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("software_jobs.id", ondelete="SET NULL"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), index=True)
    expected_batches: Mapped[int] = mapped_column(Integer)
    received_batches: Mapped[int] = mapped_column(Integer, default=0)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    inventory_digest: Mapped[str] = mapped_column(String(64))


class SoftwareInventoryBatchReceipt(Base):
    __tablename__ = "software_inventory_batch_receipts"
    collection_id: Mapped[UUID] = mapped_column(ForeignKey("software_inventory_collections.id", ondelete="CASCADE"), primary_key=True)
    batch_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_count: Mapped[int] = mapped_column(Integer)


class SoftwareInventoryItem(Base):
    __tablename__ = "software_inventory_items"
    __table_args__ = (
        UniqueConstraint("device_id", "entry_key", name="uq_software_inventory_device_entry"),
        Index("ix_software_inventory_product_present", "product_key", "is_present"),
        Index("ix_software_inventory_device_present", "device_id", "is_present"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    entry_key: Mapped[str] = mapped_column(String(64))
    product_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    version: Mapped[str | None] = mapped_column(String(128))
    publisher: Mapped[str | None] = mapped_column(String(256), index=True)
    architecture: Mapped[str] = mapped_column(String(32))
    install_date: Mapped[str | None] = mapped_column(String(10))
    install_location: Mapped[str | None] = mapped_column(String(1024))
    package_id: Mapped[str | None] = mapped_column(String(256), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    installation_scope: Mapped[str] = mapped_column(String(16), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    is_present: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_collection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("software_inventory_collections.id", ondelete="SET NULL"), index=True)


class SoftwareCatalogPackage(Base):
    __tablename__ = "software_catalog_packages"
    __table_args__ = (UniqueConstraint("package_manager", "package_id", name="uq_software_catalog_manager_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(256))
    package_id: Mapped[str] = mapped_column(String(256))
    package_manager: Mapped[str] = mapped_column(String(16), index=True)
    publisher: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(String(1000))
    version_policy: Mapped[str] = mapped_column(String(16))
    approved_version: Mapped[str | None] = mapped_column(String(128))
    supported_scopes: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32))
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SoftwareJob(Base):
    __tablename__ = "software_jobs"
    __table_args__ = (
        Index("ix_software_jobs_device_status_created", "device_id", "status", "created_at"),
        Index("ix_software_jobs_status_expires", "status", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    catalog_package_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("software_catalog_packages.id", ondelete="SET NULL"), index=True)
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(16))
    package_id: Mapped[str] = mapped_column(String(256))
    package_manager: Mapped[str] = mapped_column(String(16))
    requested_version: Mapped[str | None] = mapped_column(String(128))
    installation_scope: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(256))
    result_code: Mapped[str | None] = mapped_column(String(64))
    result_summary: Mapped[str | None] = mapped_column(String(1000))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
