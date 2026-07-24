from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import ORMModel


MOVEMENT_TYPES = {
    "IN",
    "OUT",
    "ADJUSTMENT",
    "ADJUSTMENT_POSITIVE",
    "ADJUSTMENT_NEGATIVE",
    "WASTE",
    "PRODUCTION_CONSUME",
    "PRODUCTION_OUTPUT",
}
RECIPE_UNITS = {"g", "kg", "ml", "l", "unit"}
DEFAULT_MOVEMENT_REASON = "manual"
WASTE_LOSS_CATEGORIES = {"expiration", "spoilage", "preparation_error", "breakage", "unknown_loss", "other"}


class InventoryItemBase(ORMModel):
    restaurant_id: int
    name: str = Field(min_length=1, max_length=160)
    unit: str = Field(default="unit", min_length=1, max_length=32)
    current_stock: float = Field(default=0, ge=0)
    minimum_stock: float = Field(default=0, ge=0)
    ideal_stock: float = Field(default=0, ge=0)
    cost: float | None = Field(default=None, ge=0)
    supplier: str | None = Field(default=None, max_length=180)
    is_active: bool = True

    @field_validator("name", "unit", "supplier", mode="before")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    minimum_stock: float | None = Field(default=None, ge=0)
    ideal_stock: float | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0)
    supplier: str | None = Field(default=None, max_length=180)
    is_active: bool | None = None

    @field_validator("name", "unit", "supplier", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class InventoryItemRead(InventoryItemBase):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InventoryCriticalItem(ORMModel):
    id: int
    name: str
    unit: str
    current_stock: float
    minimum_stock: float
    ideal_stock: float
    shortage: float


class DishIngredientCreate(ORMModel):
    restaurant_id: int
    dish_id: int
    inventory_item_id: int
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_recipe_unit(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        return normalized


class DishIngredientRead(DishIngredientCreate):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InventoryMovementCreate(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    movement_type: str
    quantity: float = Field(gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    historical_unit_cost: float | None = Field(default=None, ge=0)
    historical_total_cost: float | None = Field(default=None, ge=0)
    wac_previous_stock: float | None = Field(default=None, ge=0)
    wac_previous_unit_cost: float | None = Field(default=None, ge=0)
    wac_resulting_unit_cost: float | None = Field(default=None, ge=0)
    reason: str = Field(default=DEFAULT_MOVEMENT_REASON, min_length=1, max_length=80)
    origin_type: str | None = Field(default=None, min_length=1, max_length=80)
    origin_id: str | None = Field(default=None, min_length=1, max_length=120)
    reference: str | None = Field(default=None, min_length=1, max_length=120)
    loss_category: str | None = Field(default=None, min_length=1, max_length=80)
    created_by: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = None
    created_at: datetime | None = None

    @field_validator("movement_type", mode="before")
    @classmethod
    def normalize_movement_type(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        return normalized

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_movement_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

    @field_validator("reason", "origin_type", "origin_id", "reference", "loss_category", "created_by", mode="before")
    @classmethod
    def normalize_movement_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class InventoryMovementRead(InventoryMovementCreate):
    id: int
    created_at: datetime


class PurchaseIntakeCreate(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    unit_cost: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=80)
    received_at: datetime | None = None
    reference: str | None = Field(default=None, min_length=1, max_length=120)
    origin_type: str = Field(default="purchase_intake", min_length=1, max_length=80)
    origin_id: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = None

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_intake_unit(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("reason", "reference", "origin_type", "origin_id", mode="before")
    @classmethod
    def normalize_intake_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class PurchaseIntakeResult(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    quantity: float
    unit: str
    unit_cost: float | None = None
    historical_total_cost: float | None = None
    reason: str
    received_at: datetime
    reference: str | None = None
    movement_id: int
    current_stock: float


class PurchaseIntakeRead(ORMModel):
    id: int
    movement_id: int
    restaurant_id: int
    inventory_item_id: int
    ingredient_name: str | None = None
    quantity: float
    unit: str
    reference: str | None = None
    reason: str
    received_at: datetime
    created_by: str | None = None
    purchase_unit_cost: float | None = None
    purchase_total_cost: float | None = None
    previous_stock: float | None = None
    previous_unit_cost: float | None = None
    resulting_unit_cost: float | None = None
    is_valued: bool


class InventoryAdjustmentCreate(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    stock_difference: float
    unit: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=120)
    adjusted_at: datetime | None = None
    reference: str | None = Field(default=None, min_length=1, max_length=120)
    created_by: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = None

    @field_validator("stock_difference")
    @classmethod
    def validate_non_zero_difference(cls, value: float) -> float:
        if value == 0:
            raise ValueError("stock_difference must be different from zero")
        return value

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_adjustment_unit(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("reason", "reference", "created_by", mode="before")
    @classmethod
    def normalize_adjustment_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class InventoryAdjustmentResult(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    stock_difference: float
    unit: str
    reason: str
    adjusted_at: datetime
    reference: str | None = None
    movement_id: int
    movement_type: str
    current_stock: float


class InventoryReconciliationItem(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    ingredient_name: str
    unit: str
    operational_stock: float
    expected_stock: float
    difference: float
    status: str


class InventoryReconciliationResponse(ORMModel):
    restaurant_id: int | None = None
    total_items: int
    discrepant_items: int
    items: list[InventoryReconciliationItem]


class InventoryWasteLossCreate(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=120)
    loss_category: str = Field(min_length=1, max_length=80)
    occurred_at: datetime | None = None
    reference: str | None = Field(default=None, min_length=1, max_length=120)
    created_by: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = None

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_waste_unit(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("loss_category", mode="before")
    @classmethod
    def normalize_waste_category(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("loss_category")
    @classmethod
    def validate_waste_category(cls, value: str) -> str:
        if value not in WASTE_LOSS_CATEGORIES:
            raise ValueError("invalid waste loss category")
        return value

    @field_validator("reason", "reference", "created_by", mode="before")
    @classmethod
    def normalize_waste_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class InventoryWasteLossRead(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    quantity: float
    unit: str
    reason: str
    loss_category: str
    occurred_at: datetime
    reference: str | None = None
    created_by: str | None = None
    movement_id: int
    current_stock: float
    historical_unit_cost: float
    historical_total_cost: float


class InventoryProductionCreate(ORMModel):
    restaurant_id: int
    dish_id: int
    produced_inventory_item_id: int
    quantity: float = Field(gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    produced_at: datetime | None = None
    reference: str | None = Field(default=None, min_length=1, max_length=120)
    created_by: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = None

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_production_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

    @field_validator("reference", "created_by", mode="before")
    @classmethod
    def normalize_production_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class ProducedIngredientConsumption(ORMModel):
    inventory_item_id: int
    name: str
    quantity: float
    unit: str
    movement_id: int
    historical_unit_cost: float
    historical_total_cost: float


class InventoryProductionRead(ORMModel):
    restaurant_id: int
    dish_id: int
    produced_inventory_item_id: int
    produced_item_name: str
    quantity: float
    unit: str
    produced_at: datetime
    reference: str | None = None
    created_by: str | None = None
    origin_id: str
    output_movement_id: int
    consumed_ingredients: list[ProducedIngredientConsumption]
    current_stock: float
    historical_unit_cost: float
    historical_total_cost: float


class InventoryAlertRead(ORMModel):
    id: int | None = None
    restaurant_id: int
    inventory_item_id: int | None = None
    severity: str
    title: str
    message: str
    is_active: bool = True
    created_at: datetime | None = None


class InventoryInsightRead(ORMModel):
    id: int | None = None
    restaurant_id: int
    inventory_item_id: int | None = None
    dish_id: int | None = None
    insight_type: str
    priority: str = "medium"
    title: str
    message: str
    created_at: datetime | None = None


class RecommendedAction(ORMModel):
    title: str
    message: str
    priority: str = "medium"
    action_type: str
    inventory_item_id: int | None = None
    dish_id: int | None = None


class DishAtRisk(ORMModel):
    dish_id: int
    name: str
    views: int = 0
    critical_ingredients: list[str]


class InventoryStatus(ORMModel):
    restaurant_id: int | None = None
    total_items: int
    active_items: int
    critical_items: int
    warning_items: int
    healthy_items: int
    low_stock_items: int
    ideal_items: int
    inactive_items: int
    inventory_health_percentage: float


class InventoryOverview(ORMModel):
    restaurant_id: int | None = None
    total_items: int
    critical_items: int
    warning_items: int
    healthy_items: int
    inventory_health_percentage: float
    status: InventoryStatus
    alerts: list[InventoryAlertRead]
    insights: list[InventoryInsightRead]
    recommended_actions: list[RecommendedAction]
    top_critical_items: list[InventoryCriticalItem]
    dishes_at_risk: list[DishAtRisk]


class LedgerAuditIssue(ORMModel):
    code: str
    severity: str
    restaurant_id: int | None = None
    inventory_item_id: int | None = None
    ingredient_name: str | None = None
    movement_id: int | None = None
    movement_type: str | None = None
    origin_type: str | None = None
    origin_id: str | None = None
    message: str
    observed: dict[str, object | None] = Field(default_factory=dict)
    recommended_action: str
    created_at: datetime | None = None


class LedgerAuditSummary(ORMModel):
    total_issues: int
    issues_by_severity: dict[str, int]
    issues_by_code: dict[str, int]
    movements_audited: int
    inventory_items_audited: int


class LedgerAuditResponse(ORMModel):
    restaurant_id: int | None = None
    summary: LedgerAuditSummary
    issues: list[LedgerAuditIssue]
