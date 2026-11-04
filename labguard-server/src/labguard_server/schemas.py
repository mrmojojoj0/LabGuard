from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class EnrollmentCodeOut(BaseModel):
    id: UUID
    code: str
    expires_at: datetime


class EnrollmentRequestIn(BaseModel):
    enrollment_code: str = Field(min_length=8, max_length=8, pattern=r"^[A-HJ-NP-Z2-9]{8}$")
    device_id: UUID
    public_key: str = Field(min_length=32, max_length=4096)
    hostname: str = Field(min_length=1, max_length=255)
    agent_version: str | None = Field(default=None, max_length=50)


class DeviceChallengeRequest(BaseModel):
    device_id: UUID


class DeviceTicketRequest(BaseModel):
    challenge_id: UUID
    device_id: UUID
    signature: str = Field(min_length=80, max_length=256)


class DeviceApproval(BaseModel):
    assigned_name: str = Field(min_length=1, max_length=100)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assigned_name: str | None
    hostname: str
    enrollment_state: str
    enabled: bool
    agent_version: str | None


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    grid_rows: int = Field(default=5, ge=1, le=100)
    grid_columns: int = Field(default=10, ge=1, le=100)


class RoomPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    grid_rows: int | None = Field(default=None, ge=1, le=100)
    grid_columns: int | None = Field(default=None, ge=1, le=100)


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str | None
    grid_rows: int
    grid_columns: int


class CellAssignment(BaseModel):
    device_id: UUID
    row: int = Field(ge=0)
    column: int = Field(ge=0)


class RoomLayout(BaseModel):
    rows: int = Field(ge=1, le=100)
    columns: int = Field(ge=1, le=100)
    assignments: list[CellAssignment] = Field(max_length=1000)

    @model_validator(mode="after")
    def cells_are_unique(self):
        cells = [(item.row, item.column) for item in self.assignments]
        devices = [item.device_id for item in self.assignments]
        if len(set(cells)) != len(cells):
            raise ValueError("Each grid cell may contain at most one device")
        if len(set(devices)) != len(devices):
            raise ValueError("A device may appear only once in a layout")
        return self

    @field_validator("assignments")
    @classmethod
    def bounded_assignments(cls, value):
        return value


class LayoutOut(BaseModel):
    room: RoomOut
    assignments: list[CellAssignment]


class TelemetryCPU(BaseModel):
    model_config = ConfigDict(extra="forbid")
    processor_name: str | None = Field(default=None, max_length=256)
    logical_processors: StrictInt = Field(ge=1, le=512)
    physical_cores: StrictInt | None = Field(default=None, ge=1, le=512)
    utilization_percent: FiniteFloat = Field(ge=0, le=100)

    @model_validator(mode="after")
    def physical_not_above_logical(self):
        if self.physical_cores is not None and self.physical_cores > self.logical_processors:
            raise ValueError("physical core count cannot exceed logical processor count")
        return self


class TelemetryMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_bytes: StrictInt = Field(ge=1, le=2**53)
    used_bytes: StrictInt = Field(ge=0, le=2**53)
    available_bytes: StrictInt = Field(ge=0, le=2**53)
    utilization_percent: FiniteFloat = Field(ge=0, le=100)

    @model_validator(mode="after")
    def counts_fit_total(self):
        if self.used_bytes > self.total_bytes or self.available_bytes > self.total_bytes:
            raise ValueError("memory byte counts cannot exceed total memory")
        return self


class TelemetryPartition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: str = Field(max_length=256)
    mountpoint: str = Field(max_length=1024)
    filesystem: str | None = Field(default=None, max_length=64)
    total_bytes: StrictInt = Field(ge=0, le=2**53)
    used_bytes: StrictInt = Field(ge=0, le=2**53)
    free_bytes: StrictInt = Field(ge=0, le=2**53)
    utilization_percent: FiniteFloat = Field(ge=0, le=100)

    @model_validator(mode="after")
    def counts_fit_total(self):
        if self.used_bytes > self.total_bytes or self.free_bytes > self.total_bytes:
            raise ValueError("partition byte counts cannot exceed total capacity")
        return self


class TelemetryOperatingSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edition: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=128)
    build_number: str | None = Field(default=None, max_length=64)
    architecture: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)


class TelemetryNetworkInterface(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    status: str = Field(pattern=r"^(UP|DOWN|UNKNOWN)$")
    mac_address: str | None = Field(default=None, max_length=32)
    ipv4_addresses: list[IPv4Address] = Field(default_factory=list, max_length=32)
    ipv6_addresses: list[IPv6Address] = Field(default_factory=list, max_length=32)
    speed_mbps: FiniteFloat | None = Field(default=None, ge=0, le=10_000_000)


class TelemetrySnapshotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collected_at: datetime
    cpu: TelemetryCPU
    memory: TelemetryMemory
    storage_partitions: list[TelemetryPartition] = Field(max_length=64)
    operating_system: TelemetryOperatingSystem
    boot_time: datetime
    uptime_seconds: FiniteFloat = Field(ge=0, le=2**53)
    network_interfaces: list[TelemetryNetworkInterface] = Field(max_length=64)

    @model_validator(mode="after")
    def timestamps_have_timezone(self):
        if self.collected_at.tzinfo is None or self.boot_time.tzinfo is None:
            raise ValueError("telemetry timestamps must include a timezone")
        return self

