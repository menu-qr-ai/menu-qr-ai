from enum import StrEnum


class OrderStatus(StrEnum):
    DRAFT = "draft"
    DRAFT_CUSTOMER = "draft_customer"
    SUBMITTED_CUSTOMER = "submitted_customer"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


CUSTOMER_PENDING_ORDER_STATUSES = (
    OrderStatus.DRAFT_CUSTOMER.value,
    OrderStatus.SUBMITTED_CUSTOMER.value,
)

ACTIVE_ORDER_STATUSES = (
    OrderStatus.DRAFT.value,
    OrderStatus.SUBMITTED.value,
    *CUSTOMER_PENDING_ORDER_STATUSES,
)
