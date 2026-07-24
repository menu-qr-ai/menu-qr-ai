from enum import StrEnum


class CustomerSessionStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


CUSTOMER_SESSION_TTL_SECONDS = 60 * 60 * 4
