from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from datetime import date
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StrictStr, field_validator, model_validator


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


class RdpAccessRequestOut(BaseModel):
    id: UUID
    device_id: UUID
    hostname: str
    username: str | None
    status: Literal["PENDING", "READY", "FAILED", "EXPIRED"]
    error_code: str | None
    created_at: datetime
    expires_at: datetime
    access_expires_at: datetime


class RdpAccessResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    status: Literal["READY", "FAILED"]
    error_code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9_:-]+$")
    username: StrictStr | None = Field(default=None, max_length=256)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        if value is not None and (not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("RDP username must contain printable characters")
        return value


class ProcessEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pid: StrictInt = Field(ge=0, le=2_147_483_647)
    name: StrictStr = Field(min_length=1, max_length=256)
    username: StrictStr | None = Field(default=None, max_length=256)
    executable_path: StrictStr | None = Field(default=None, max_length=1024)
    cpu_percent: FiniteFloat | None = Field(default=None, ge=0, le=10000)
    memory_bytes: StrictInt | None = Field(default=None, ge=0, le=2**63 - 1)
    created_at_us: StrictInt | None = Field(default=None, ge=1, le=2**63 - 1)


class ProcessRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["LIST", "TERMINATE", "KILL"]
    target_pid: StrictInt | None = Field(default=None, ge=1, le=2_147_483_647)
    target_created_at_us: StrictInt | None = Field(default=None, ge=1, le=2**63 - 1)

    @model_validator(mode="after")
    def operation_target_matches(self):
        if self.operation == "LIST" and (self.target_pid is not None or self.target_created_at_us is not None):
            raise ValueError("List requests cannot contain a target process")
        if self.operation != "LIST" and (self.target_pid is None or self.target_created_at_us is None):
            raise ValueError("Termination requests require PID and creation time")
        return self


class ProcessRequestOut(BaseModel):
    id: UUID
    device_id: UUID
    operation: Literal["LIST", "TERMINATE", "KILL"]
    status: Literal["PENDING", "COMPLETE", "FAILED", "EXPIRED"]
    target_pid: int | None
    target_created_at_us: int | None
    result_code: str | None
    processes: list[ProcessEntry] | None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None


class ProcessResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    batch_index: StrictInt = Field(default=0, ge=0, le=124)
    batch_count: StrictInt = Field(default=1, ge=1, le=125)
    processes: list[ProcessEntry] = Field(default_factory=list, max_length=8)
    result_code: Literal["request_expired", "process_list_failed", "process_list_truncated", "terminated", "killed", "process_not_found",
                         "pid_reused", "access_denied", "invalid_process_identity",
                         "protected_process", "terminate_timeout", "kill_timeout",
                         "operation_failed"] | None = None

    @model_validator(mode="after")
    def batch_is_valid(self):
        if self.batch_index >= self.batch_count:
            raise ValueError("Process result batch index exceeds batch count")
        if self.result_code not in (None, "request_expired", "process_list_failed", "process_list_truncated") and (
                self.batch_count != 1 or self.batch_index != 0 or self.processes):
            raise ValueError("Process action results cannot contain process batches")
        if self.result_code == "process_list_failed" and (self.batch_count != 1 or self.processes):
            raise ValueError("Failed process listings cannot contain process entries")
        return self

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
    username: str | None = Field(default=None, max_length=256)
    agent_account: str | None = Field(default=None, max_length=256)

    @field_validator("username")
    @classmethod
    def username_is_printable(cls, value):
        if value is not None and (not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("Username must contain printable characters")
        return value

    @field_validator("agent_account")
    @classmethod
    def agent_account_is_printable(cls, value):
        if value is not None and (not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("Agent account must contain printable characters")
        return value


class TelemetryNetworkInterface(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    status: str = Field(pattern=r"^(UP|DOWN|UNKNOWN)$")
    mac_address: str | None = Field(default=None, max_length=32)
    ipv4_addresses: list[IPv4Address] = Field(default_factory=list, max_length=32)
    ipv6_addresses: list[IPv6Address] = Field(default_factory=list, max_length=32)
    speed_mbps: FiniteFloat | None = Field(default=None, ge=0, le=10_000_000)


class TelemetryNetworkConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: datetime
    direction: Literal["INCOMING", "OUTGOING", "UNKNOWN"]
    protocol: Literal["TCP", "UDP", "ICMP"]
    local_ip: IPv4Address | IPv6Address
    local_port: StrictInt = Field(ge=0, le=65535)
    remote_ip: IPv4Address | IPv6Address | None = None
    remote_port: StrictInt | None = Field(default=None, ge=0, le=65535)
    interface: StrictStr = Field(min_length=1, max_length=128)
    state: StrictStr = Field(min_length=1, max_length=32)

    @field_validator("observed_at")
    @classmethod
    def timestamp_has_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("Network connection timestamp must include a timezone")
        return value


class WfpConnectionEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_record_id: StrictInt = Field(ge=1, le=2**63 - 1)
    event_id: Literal[5152, 5156, 5157]
    event_time: datetime
    event_kind: Literal["PACKET_BLOCKED", "CONNECTION_ALLOWED", "CONNECTION_BLOCKED"]
    direction: Literal["INCOMING", "OUTGOING", "UNKNOWN"]
    protocol: Literal["TCP", "UDP", "ICMP", "OTHER"]
    protocol_number: StrictInt = Field(ge=0, le=255)
    source_ip: IPv4Address | IPv6Address
    source_port: StrictInt | None = Field(default=None, ge=0, le=65535)
    destination_ip: IPv4Address | IPv6Address
    destination_port: StrictInt | None = Field(default=None, ge=0, le=65535)
    process_id: StrictInt | None = Field(default=None, ge=0, le=4_294_967_295)
    process_path: StrictStr | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def event_fields_are_consistent(self):
        if self.event_time.tzinfo is None:
            raise ValueError("WFP event timestamp must include a timezone")
        expected = {5152: "PACKET_BLOCKED", 5156: "CONNECTION_ALLOWED", 5157: "CONNECTION_BLOCKED"}[self.event_id]
        if self.event_kind != expected:
            raise ValueError("WFP event kind does not match event ID")
        return self


class WfpEventBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    log_generation: UUID
    cursor_record_id: StrictInt = Field(ge=0, le=2**63 - 1)
    status: Literal["STARTING", "ACTIVE", "GAP", "UNAVAILABLE"]
    gap_reason: Literal["CURSOR_INVALID", "SECURITY_LOG_CLEARED", "SECURITY_LOG_ROLLOVER"] | None = None
    error_code: StrictStr | None = Field(default=None, max_length=64, pattern=r"^[A-Z0-9_:-]+$")
    events: list[WfpConnectionEventIn] = Field(default_factory=list, max_length=25)

    @model_validator(mode="after")
    def cursor_covers_events(self):
        ids = [event.event_record_id for event in self.events]
        if ids != sorted(set(ids)) or (ids and self.cursor_record_id < ids[-1]):
            raise ValueError("WFP event IDs must be unique, ordered, and covered by the cursor")
        if self.status == "GAP" and self.gap_reason is None:
            raise ValueError("WFP gaps require a reason")
        return self


class PeripheralEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_key: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    name: StrictStr = Field(min_length=1, max_length=256)
    category: Literal["EXTERNAL_DRIVE", "USB_PERIPHERAL", "INPUT_DEVICE", "BLUETOOTH",
                      "CAMERA_OR_SCANNER", "PRINTER", "MODEM"]
    is_storage: StrictBool

    @field_validator("name")
    @classmethod
    def printable_name(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Peripheral name must contain printable characters")
        return value


class PeripheralSnapshotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collected_at: datetime
    peripherals: list[PeripheralEntryIn] = Field(max_length=256)

    @model_validator(mode="after")
    def valid_snapshot(self):
        if self.collected_at.tzinfo is None:
            raise ValueError("Peripheral snapshot timestamp must include a timezone")
        keys = [item.device_key for item in self.peripherals]
        if len(set(keys)) != len(keys):
            raise ValueError("Peripheral snapshot keys must be unique")
        return self


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
    network_connections: list[TelemetryNetworkConnection] | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def timestamps_have_timezone(self):
        if self.collected_at.tzinfo is None or self.boot_time.tzinfo is None:
            raise ValueError("telemetry timestamps must include a timezone")
        return self


class SoftwareInventoryEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_key: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    name: StrictStr = Field(min_length=1, max_length=256)
    version: StrictStr | None = Field(default=None, max_length=128)
    publisher: StrictStr | None = Field(default=None, max_length=256)
    architecture: StrictStr = Field(min_length=1, max_length=32)
    install_date: StrictStr | None = Field(default=None, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")
    install_location: StrictStr | None = Field(default=None, max_length=1024)
    package_id: StrictStr | None = Field(default=None, max_length=256)
    source: Literal["WINDOWS_REGISTRY", "WINGET", "CHOCO"]
    discovery_sources: list[Literal["WINDOWS_REGISTRY", "WINGET", "CHOCO"]] = Field(default_factory=list, max_length=3)
    installation_scope: Literal["MACHINE", "USER", "UNKNOWN"]

    @field_validator("install_date")
    @classmethod
    def valid_install_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class SoftwareInventoryBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: UUID
    request_id: UUID | None = None
    job_id: UUID | None = None
    inventory_version: StrictInt = Field(ge=1, le=1)
    started_at: datetime
    batch_index: StrictInt = Field(ge=0, le=255)
    batch_count: StrictInt = Field(ge=1, le=256)
    collection_status: Literal["COMPLETE", "PARTIAL"]
    inventory_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    unchanged: StrictBool = False
    errors: list[StrictStr] = Field(default_factory=list, max_length=20)
    entries: list[SoftwareInventoryEntryIn] = Field(default_factory=list, max_length=100)

    @field_validator("errors")
    @classmethod
    def safe_error_codes(cls, values):
        if any(len(value) > 160 or not re.fullmatch(r"[a-z0-9_:-]+", value) for value in values):
            raise ValueError("inventory errors must be bounded diagnostic codes")
        return values

    @model_validator(mode="after")
    def batch_metadata_is_consistent(self):
        if self.started_at.tzinfo is None:
            raise ValueError("inventory start time must include a timezone")
        if self.batch_index >= self.batch_count:
            raise ValueError("batch index must be less than batch count")
        keys = [entry.entry_key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("a batch cannot contain duplicate entries")
        if self.unchanged and (self.batch_count != 1 or self.batch_index != 0 or self.entries or self.errors
                               or self.job_id is not None or self.collection_status != "COMPLETE"):
            raise ValueError("unchanged inventory must be one empty complete batch")
        return self


class SoftwareCatalogPackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: StrictStr = Field(min_length=1, max_length=256)
    package_id: StrictStr = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
    package_manager: Literal["WINGET", "CHOCO"]
    publisher: StrictStr | None = Field(default=None, max_length=256)
    description: StrictStr | None = Field(default=None, max_length=1000)
    version_policy: Literal["LATEST", "PINNED", "SELECTABLE"] = "LATEST"
    approved_version: StrictStr | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
    supported_scopes: list[Literal["MACHINE", "USER"]] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_package_policy(self):
        if len(self.supported_scopes) != len(set(self.supported_scopes)):
            raise ValueError("supported scopes must be unique")
        if self.version_policy == "PINNED" and not self.approved_version:
            raise ValueError("pinned packages require an approved version")
        if self.version_policy != "PINNED" and self.approved_version is not None:
            raise ValueError("only pinned packages can set an approved version")
        if self.package_manager == "CHOCO" and self.supported_scopes != ["MACHINE"]:
            raise ValueError("Chocolatey supports machine scope only in this release")
        return self


class WingetCatalogImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: StrictStr = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
    source: StrictStr = Field(default="winget", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    supported_scopes: list[Literal["MACHINE", "USER"]] = Field(default_factory=lambda: ["MACHINE"], min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_scopes(self):
        if len(self.supported_scopes) != len(set(self.supported_scopes)):
            raise ValueError("supported scopes must be unique")
        return self


class SoftwareJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["INSTALL", "UNINSTALL"]
    catalog_package_id: UUID | None = None
    package_manager: Literal["WINGET"] | None = None
    package_id: StrictStr | None = Field(default=None, min_length=1, max_length=256,
                                           pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
    source: StrictStr | None = Field(default=None, min_length=1, max_length=64,
                                     pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    installation_scope: Literal["MACHINE", "USER"] = "MACHINE"
    version: StrictStr | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
    inventory_item_id: UUID | None = None
    expires_in_seconds: StrictInt = Field(default=1800, ge=60, le=86400)

    @model_validator(mode="after")
    def action_parameters_match(self):
        if self.action == "INSTALL":
            if self.inventory_item_id is not None:
                raise ValueError("install jobs cannot specify an inventory item")
            direct_fields = (self.package_manager, self.package_id, self.source)
            if self.catalog_package_id is None and any(value is None for value in direct_fields):
                raise ValueError("install jobs require a catalog package or a complete direct WinGet identity")
            if self.catalog_package_id is not None and any(value is not None for value in direct_fields):
                raise ValueError("catalog and direct package identities cannot be combined")
            if self.source is not None and self.source.casefold() != "winget":
                raise ValueError("direct WinGet jobs must use the winget source")
        if self.action == "UNINSTALL":
            if self.inventory_item_id is None or self.version is not None:
                raise ValueError("uninstall jobs require an inventory item and do not accept a version")
            if any(value is not None for value in (self.package_manager, self.package_id, self.source)):
                raise ValueError("uninstall identity is derived from the selected inventory item")
        return self


class SoftwareJobEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    progress_percent: StrictInt | None = Field(default=None, ge=0, le=100)
    progress_message: StrictStr | None = Field(default=None, max_length=256)
    result_code: StrictStr | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_:-]+$")
    result_summary: StrictStr | None = Field(default=None, max_length=1000)
    error_message: StrictStr | None = Field(default=None, max_length=500)

