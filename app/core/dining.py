from enum import StrEnum


class ServiceSessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
