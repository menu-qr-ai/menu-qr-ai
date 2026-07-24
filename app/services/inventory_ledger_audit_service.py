from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import isclose

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import InventoryItem, InventoryMovement
from app.schemas.inventory import LedgerAuditIssue, LedgerAuditResponse, LedgerAuditSummary, RECIPE_UNITS
from app.services.inventory_adjustment_service import get_inventory_reconciliation
from app.services.restaurant_service import require_restaurant


HISTORICAL_COST_TOLERANCE = 0.01
WAC_TOLERANCE = 0.0001
DEFAULT_LEDGER_AUDIT_LIMIT = 100
MAX_LEDGER_AUDIT_LIMIT = 500
SEVERITY_ORDER = {"critical": 0, "error": 1, "warning": 2, "info": 3}
ECONOMIC_MOVEMENT_TYPES = {"OUT", "WASTE", "PRODUCTION_CONSUME", "PRODUCTION_OUTPUT"}
PURCHASE_INTAKE_ORIGIN = "purchase_intake"
PRODUCTION_ORIGIN = "inventory_production"


@dataclass
class AuditIssueDraft:
    code: str
    severity: str
    message: str
    recommended_action: str
    movement: InventoryMovement | None = None
    item: InventoryItem | None = None
    restaurant_id: int | None = None
    observed: dict[str, object | None] | None = None
    created_at: datetime | None = None


def audit_inventory_ledger(
    db: Session,
    *,
    restaurant_id: int | None = None,
    inventory_item_id: int | None = None,
    severity: str | None = None,
    code: str | None = None,
    limit: int = DEFAULT_LEDGER_AUDIT_LIMIT,
) -> LedgerAuditResponse:
    if restaurant_id is not None:
        require_restaurant(db, restaurant_id)

    movements = _load_movements(db, restaurant_id=restaurant_id, inventory_item_id=inventory_item_id)
    items = _load_items(db, restaurant_id=restaurant_id, inventory_item_id=inventory_item_id)
    issues: list[LedgerAuditIssue] = []

    for movement in movements:
        issues.extend(_audit_movement(movement))

    issues.extend(_audit_production_groups(movements))
    issues.extend(_audit_reconciliation(db, restaurant_id=restaurant_id, inventory_item_id=inventory_item_id))

    if severity is not None:
        issues = [issue for issue in issues if issue.severity == severity]
    if code is not None:
        issues = [issue for issue in issues if issue.code == code]

    issues = sorted(issues, key=_issue_sort_key)
    capped_limit = min(max(limit, 1), MAX_LEDGER_AUDIT_LIMIT)
    limited_issues = issues[:capped_limit]
    return LedgerAuditResponse(
        restaurant_id=restaurant_id,
        summary=_summary(issues, movements_audited=len(movements), inventory_items_audited=len(items)),
        issues=limited_issues,
    )


def _load_movements(
    db: Session,
    *,
    restaurant_id: int | None,
    inventory_item_id: int | None,
) -> list[InventoryMovement]:
    statement = select(InventoryMovement).options(selectinload(InventoryMovement.inventory_item))
    if restaurant_id is not None:
        statement = statement.where(InventoryMovement.restaurant_id == restaurant_id)
    if inventory_item_id is not None:
        statement = statement.where(InventoryMovement.inventory_item_id == inventory_item_id)
    return list(db.scalars(statement).all())


def _load_items(
    db: Session,
    *,
    restaurant_id: int | None,
    inventory_item_id: int | None,
) -> list[InventoryItem]:
    statement = select(InventoryItem)
    if restaurant_id is not None:
        statement = statement.where(InventoryItem.restaurant_id == restaurant_id)
    if inventory_item_id is not None:
        statement = statement.where(InventoryItem.id == inventory_item_id)
    return list(db.scalars(statement).all())


def _audit_movement(movement: InventoryMovement) -> list[LedgerAuditIssue]:
    drafts: list[AuditIssueDraft] = []
    drafts.extend(_audit_required_fields(movement))
    drafts.extend(_audit_origin_compatibility(movement))
    drafts.extend(_audit_historical_cost(movement))
    drafts.extend(_audit_purchase_wac_trace(movement))
    drafts.extend(_audit_waste(movement))
    drafts.extend(_audit_legacy(movement))
    return [_issue(draft) for draft in drafts]


def _audit_required_fields(movement: InventoryMovement) -> list[AuditIssueDraft]:
    drafts: list[AuditIssueDraft] = []
    if not movement.unit or movement.unit not in RECIPE_UNITS:
        drafts.append(
            AuditIssueDraft(
                code="required_field_missing",
                severity="critical",
                movement=movement,
                message="El movimiento no tiene una unidad valida.",
                observed={"unit": movement.unit},
                recommended_action="Revisar el movimiento legacy y corregir la unidad mediante una migracion controlada.",
            )
        )
    if not movement.reason:
        drafts.append(
            AuditIssueDraft(
                code="required_field_missing",
                severity="warning",
                movement=movement,
                message="El movimiento no tiene motivo operativo.",
                observed={"reason": movement.reason},
                recommended_action="Completar el motivo solo mediante un proceso de saneamiento auditado.",
            )
        )
    return drafts


def _audit_origin_compatibility(movement: InventoryMovement) -> list[AuditIssueDraft]:
    incompatible = {
        "OUT": {"purchase_intake", "inventory_waste_loss", "inventory_production", "inventory_adjustment"},
        "WASTE": {"purchase_intake", "sale", "inventory_production", "inventory_adjustment"},
        "PRODUCTION_CONSUME": {"purchase_intake", "sale", "inventory_waste_loss", "inventory_adjustment"},
        "PRODUCTION_OUTPUT": {"purchase_intake", "sale", "inventory_waste_loss", "inventory_adjustment"},
    }
    if movement.origin_type in incompatible.get(movement.movement_type, set()):
        return [
            _draft(
                movement,
                code="movement_origin_mismatch",
                severity="error",
                message="El tipo de movimiento y su origen operativo son incompatibles.",
                observed={"movement_type": movement.movement_type, "origin_type": movement.origin_type},
                recommended_action="Investigar el origen real antes de reclasificar el movimiento.",
            )
        ]
    if movement.movement_type == "PRODUCTION_OUTPUT" and movement.origin_type != PRODUCTION_ORIGIN:
        return [
            _draft(
                movement,
                code="movement_origin_mismatch",
                severity="error",
                message="La salida de produccion no tiene origen de produccion.",
                observed={"origin_type": movement.origin_type},
                recommended_action="Verificar el grupo de produccion asociado al movimiento.",
            )
        ]
    return []


def _audit_historical_cost(movement: InventoryMovement) -> list[AuditIssueDraft]:
    drafts: list[AuditIssueDraft] = []
    if movement.movement_type in ECONOMIC_MOVEMENT_TYPES and (
        movement.historical_unit_cost is None or movement.historical_total_cost is None
    ):
        drafts.append(
            _draft(
                movement,
                code="historical_cost_missing",
                severity="error",
                message="El movimiento economico no conserva coste historico completo.",
                observed={
                    "historical_unit_cost": movement.historical_unit_cost,
                    "historical_total_cost": movement.historical_total_cost,
                },
                recommended_action="No recalcular automaticamente; revisar el evento original y documentar el dato faltante.",
            )
        )
    if movement.historical_unit_cost is not None and movement.historical_total_cost is not None:
        expected = round(movement.quantity * movement.historical_unit_cost, 2)
        if not isclose(movement.historical_total_cost, expected, abs_tol=HISTORICAL_COST_TOLERANCE):
            drafts.append(
                _draft(
                    movement,
                    code="historical_total_mismatch",
                    severity="error",
                    message="El total historico no coincide con cantidad por coste unitario.",
                    observed={
                        "quantity": movement.quantity,
                        "historical_unit_cost": movement.historical_unit_cost,
                        "historical_total_cost": movement.historical_total_cost,
                        "expected_total": expected,
                    },
                    recommended_action="Auditar el evento original antes de cualquier correccion.",
                )
            )
    return drafts


def _audit_purchase_wac_trace(movement: InventoryMovement) -> list[AuditIssueDraft]:
    if not (movement.movement_type == "IN" and movement.origin_type == PURCHASE_INTAKE_ORIGIN):
        return []

    wac_values = [
        movement.historical_unit_cost,
        movement.historical_total_cost,
        movement.wac_previous_stock,
        movement.wac_previous_unit_cost,
        movement.wac_resulting_unit_cost,
    ]
    if all(value is None for value in wac_values):
        return []

    drafts: list[AuditIssueDraft] = []
    required_present = (
        movement.historical_unit_cost is not None
        and movement.historical_total_cost is not None
        and movement.wac_previous_stock is not None
        and movement.wac_resulting_unit_cost is not None
    )
    previous_cost_valid = movement.wac_previous_stock == 0 or movement.wac_previous_unit_cost is not None
    if not required_present or not previous_cost_valid:
        drafts.append(
            _draft(
                movement,
                code="wac_trace_incomplete",
                severity="warning",
                message="La recepcion valorada tiene una traza WAC incompleta.",
                observed=_wac_observed(movement),
                recommended_action="Conservar el movimiento sin recalculo y revisar la fuente de la recepcion.",
            )
        )
        return drafts

    if movement.wac_previous_stock < 0:
        drafts.append(
            _draft(
                movement,
                code="wac_result_mismatch",
                severity="error",
                message="La traza WAC contiene stock previo negativo.",
                observed=_wac_observed(movement),
                recommended_action="Investigar datos legacy antes de confiar en el coste medio resultante.",
            )
        )
        return drafts

    if movement.wac_previous_stock == 0:
        expected = movement.historical_unit_cost
    else:
        denominator = movement.wac_previous_stock + movement.quantity
        if denominator <= 0 or movement.wac_previous_unit_cost is None:
            expected = None
        else:
            expected = (
                movement.wac_previous_stock * movement.wac_previous_unit_cost
                + movement.quantity * movement.historical_unit_cost
            ) / denominator
    if expected is None or not isclose(movement.wac_resulting_unit_cost, expected, abs_tol=WAC_TOLERANCE):
        drafts.append(
            _draft(
                movement,
                code="wac_result_mismatch",
                severity="error",
                message="El coste medio resultante no coincide con la traza WAC.",
                observed={**_wac_observed(movement), "expected_resulting_unit_cost": expected},
                recommended_action="No recalcular automaticamente; revisar la recepcion y su traza.",
            )
        )
    return drafts


def _audit_waste(movement: InventoryMovement) -> list[AuditIssueDraft]:
    if movement.movement_type != "WASTE":
        return []
    drafts: list[AuditIssueDraft] = []
    if not movement.loss_category:
        drafts.append(
            _draft(
                movement,
                code="waste_category_missing",
                severity="warning",
                message="La merma no tiene categoria de perdida.",
                observed={"loss_category": movement.loss_category},
                recommended_action="Clasificar la merma en un proceso auditado si el dato existe.",
            )
        )
    if movement.historical_unit_cost is None or movement.historical_total_cost is None:
        drafts.append(
            _draft(
                movement,
                code="historical_cost_missing",
                severity="error",
                message="La merma no conserva coste historico completo.",
                observed={
                    "historical_unit_cost": movement.historical_unit_cost,
                    "historical_total_cost": movement.historical_total_cost,
                },
                recommended_action="Revisar el coste operativo vigente en el momento de la merma.",
            )
        )
    return drafts


def _audit_legacy(movement: InventoryMovement) -> list[AuditIssueDraft]:
    drafts: list[AuditIssueDraft] = []
    if movement.movement_type == "IN" and movement.origin_type is None:
        drafts.append(
            _draft(
                movement,
                code="legacy_ambiguous_movement",
                severity="info",
                message="Entrada legacy sin origen; no puede clasificarse como compra, ajuste o stock inicial.",
                observed={"movement_type": movement.movement_type, "origin_type": movement.origin_type},
                recommended_action="Mantener como legacy salvo que exista evidencia externa para clasificarla.",
            )
        )
    if movement.movement_type == "ADJUSTMENT":
        drafts.append(
            _draft(
                movement,
                code="legacy_adjustment_movement",
                severity="info",
                message="Movimiento de ajuste legacy anterior a tipos explicitos positivo/negativo.",
                observed={"movement_type": movement.movement_type},
                recommended_action="No modificar salvo proceso de migracion historica aprobado.",
            )
        )
    return drafts


def _audit_production_groups(movements: list[InventoryMovement]) -> list[LedgerAuditIssue]:
    groups: dict[str, list[InventoryMovement]] = defaultdict(list)
    for movement in movements:
        if movement.origin_type == PRODUCTION_ORIGIN and movement.origin_id:
            groups[movement.origin_id].append(movement)

    issues: list[LedgerAuditIssue] = []
    for origin_id, group in groups.items():
        consumes = [movement for movement in group if movement.movement_type == "PRODUCTION_CONSUME"]
        outputs = [movement for movement in group if movement.movement_type == "PRODUCTION_OUTPUT"]
        restaurants = {movement.restaurant_id for movement in group}
        anchor = outputs[0] if outputs else group[0]
        if not consumes:
            issues.append(
                _issue(
                    _draft(
                        anchor,
                        code="production_group_incomplete",
                        severity="error",
                        message="El grupo de produccion no tiene consumos.",
                        observed={"origin_id": origin_id, "consume_count": 0, "output_count": len(outputs)},
                        recommended_action="Revisar movimientos agrupados por origin_id antes de reportar produccion.",
                    )
                )
            )
        if len(outputs) != 1:
            issues.append(
                _issue(
                    _draft(
                        anchor,
                        code="production_group_incomplete",
                        severity="error",
                        message="El grupo de produccion debe tener exactamente una salida.",
                        observed={"origin_id": origin_id, "output_count": len(outputs)},
                        recommended_action="Investigar duplicados o grupos truncados de produccion.",
                    )
                )
            )
        if len(restaurants) > 1:
            issues.append(
                _issue(
                    _draft(
                        anchor,
                        code="production_group_restaurant_mismatch",
                        severity="critical",
                        message="El grupo de produccion mezcla restaurantes.",
                        observed={"origin_id": origin_id, "restaurant_ids": sorted(restaurants)},
                        recommended_action="Investigar integridad multitenant del grupo antes de usar sus costes.",
                    )
                )
            )
    return issues


def _audit_reconciliation(
    db: Session,
    *,
    restaurant_id: int | None,
    inventory_item_id: int | None,
) -> list[LedgerAuditIssue]:
    reconciliation = get_inventory_reconciliation(db, restaurant_id=restaurant_id)
    issues: list[LedgerAuditIssue] = []
    for item in reconciliation.items:
        if inventory_item_id is not None and item.inventory_item_id != inventory_item_id:
            continue
        if item.status != "discrepant":
            continue
        issues.append(
            LedgerAuditIssue(
                code="stock_ledger_mismatch",
                severity="critical",
                restaurant_id=item.restaurant_id,
                inventory_item_id=item.inventory_item_id,
                ingredient_name=item.ingredient_name,
                movement_id=None,
                movement_type=None,
                origin_type=None,
                origin_id=None,
                message="El stock operativo no coincide con el stock esperado segun ledger.",
                observed={
                    "operational_stock": item.operational_stock,
                    "expected_stock": item.expected_stock,
                    "difference": item.difference,
                },
                recommended_action="No ajustar automaticamente; investigar movimientos faltantes o stock operativo alterado.",
                created_at=None,
            )
        )
    return issues


def _draft(
    movement: InventoryMovement,
    *,
    code: str,
    severity: str,
    message: str,
    observed: dict[str, object | None],
    recommended_action: str,
) -> AuditIssueDraft:
    return AuditIssueDraft(
        code=code,
        severity=severity,
        movement=movement,
        message=message,
        observed=observed,
        recommended_action=recommended_action,
    )


def _issue(draft: AuditIssueDraft) -> LedgerAuditIssue:
    movement = draft.movement
    item = draft.item or (movement.inventory_item if movement is not None else None)
    return LedgerAuditIssue(
        code=draft.code,
        severity=draft.severity,
        restaurant_id=draft.restaurant_id if draft.restaurant_id is not None else (movement.restaurant_id if movement else None),
        inventory_item_id=item.id if item is not None else (movement.inventory_item_id if movement else None),
        ingredient_name=item.name if item is not None else None,
        movement_id=movement.id if movement else None,
        movement_type=movement.movement_type if movement else None,
        origin_type=movement.origin_type if movement else None,
        origin_id=movement.origin_id if movement else None,
        message=draft.message,
        observed=draft.observed or {},
        recommended_action=draft.recommended_action,
        created_at=draft.created_at if draft.created_at is not None else (movement.created_at if movement else None),
    )


def _wac_observed(movement: InventoryMovement) -> dict[str, object | None]:
    return {
        "quantity": movement.quantity,
        "historical_unit_cost": movement.historical_unit_cost,
        "historical_total_cost": movement.historical_total_cost,
        "wac_previous_stock": movement.wac_previous_stock,
        "wac_previous_unit_cost": movement.wac_previous_unit_cost,
        "wac_resulting_unit_cost": movement.wac_resulting_unit_cost,
    }


def _issue_sort_key(issue: LedgerAuditIssue) -> tuple[int, float, str, int]:
    timestamp = issue.created_at.timestamp() if issue.created_at else 0
    movement_id = issue.movement_id or 0
    return (SEVERITY_ORDER.get(issue.severity, 99), -timestamp, issue.code, -movement_id)


def _summary(
    issues: list[LedgerAuditIssue],
    *,
    movements_audited: int,
    inventory_items_audited: int,
) -> LedgerAuditSummary:
    return LedgerAuditSummary(
        total_issues=len(issues),
        issues_by_severity=dict(Counter(issue.severity for issue in issues)),
        issues_by_code=dict(Counter(issue.code for issue in issues)),
        movements_audited=movements_audited,
        inventory_items_audited=inventory_items_audited,
    )
