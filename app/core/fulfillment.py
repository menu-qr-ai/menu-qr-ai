from enum import StrEnum


class FulfillmentStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class FulfillmentLineStatus(StrEnum):
    PROCESSED = "processed"
    SKIPPED = "skipped"
