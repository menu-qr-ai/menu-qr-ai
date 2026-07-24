from datetime import datetime

from pydantic import Field, field_validator

from app.core.dining import ServiceSessionStatus
from app.schemas.common import ORMModel


class ZoneCreate(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    display_order: int = 0
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.split())


class ZoneUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    display_order: int | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None


class ZoneRead(ORMModel):
    id: int
    restaurant_id: int
    name: str
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RestaurantTableCreate(ORMModel):
    zone_id: int | None = None
    code: str = Field(min_length=1, max_length=80)
    capacity: int = Field(gt=0)
    display_order: int = 0
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return " ".join(value.split())


class RestaurantTableUpdate(ORMModel):
    zone_id: int | None = None
    code: str | None = Field(default=None, min_length=1, max_length=80)
    capacity: int | None = Field(default=None, gt=0)
    display_order: int | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None


class RestaurantTableRead(ORMModel):
    id: int
    restaurant_id: int
    zone_id: int | None
    code: str
    capacity: int
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ServiceSessionOpen(ORMModel):
    guest_count: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)


class ServiceSessionRead(ORMModel):
    id: int
    restaurant_id: int
    table_id: int
    status: ServiceSessionStatus
    opened_at: datetime
    closed_at: datetime | None
    guest_count: int | None
    opened_by_user_id: int
    closed_by_user_id: int | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class DiningRoomTableState(ORMModel):
    table: RestaurantTableRead
    zone: ZoneRead | None
    is_occupied: bool
    current_session: ServiceSessionRead | None
    responsible_user_name: str | None = None


class DiningRoomState(ORMModel):
    restaurant_id: int
    zones: list[ZoneRead]
    tables: list[DiningRoomTableState]
    free_tables: int
    occupied_tables: int
