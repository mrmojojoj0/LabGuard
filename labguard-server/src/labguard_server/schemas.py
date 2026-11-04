from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

