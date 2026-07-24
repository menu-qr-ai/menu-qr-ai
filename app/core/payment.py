from enum import StrEnum


class PaymentStatus(StrEnum):
    COMPLETED = "completed"


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"
    OTHER = "other"
