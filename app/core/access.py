from enum import StrEnum


class RestaurantRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    WAITER = "waiter"
    COOK = "cook"
    VIEWER = "viewer"


class Permission(StrEnum):
    RESTAURANT_READ = "restaurant:read"
    RESTAURANT_MANAGE = "restaurant:manage"
    MEMBERSHIP_MANAGE = "membership:manage"
    MENU_READ = "menu:read"
    DASHBOARD_READ = "dashboard:read"
    ANALYTICS_READ = "analytics:read"
    INVENTORY_READ = "inventory:read"
    INVENTORY_WRITE = "inventory:write"
    PRODUCTION_WRITE = "production:write"
    OPERATIONS_WRITE = "operations:write"
    COSTING_READ = "costing:read"
    DINING_ROOM_READ = "dining_room:read"
    DINING_ROOM_MANAGE = "dining_room:manage"
    CUSTOMER_QR_READ = "customer_qr:read"
    CUSTOMER_QR_MANAGE = "customer_qr:manage"
    SERVICE_SESSION_WRITE = "service_session:write"
    SETTLEMENT_READ = "settlement:read"
    SETTLEMENT_CREATE = "settlement:create"
    PAYMENT_READ = "payment:read"
    PAYMENT_WRITE = "payment:write"
    ORDER_READ = "order:read"
    ORDER_WRITE = "order:write"
    ORDER_FULFILL = "order:fulfill"
    KITCHEN_READ = "kitchen:read"
    KITCHEN_OPERATE = "kitchen:operate"


ROLE_PERMISSIONS: dict[RestaurantRole, frozenset[Permission]] = {
    RestaurantRole.OWNER: frozenset(Permission),
    RestaurantRole.MANAGER: frozenset(
        {
            Permission.RESTAURANT_READ,
            Permission.RESTAURANT_MANAGE,
            Permission.MENU_READ,
            Permission.DASHBOARD_READ,
            Permission.ANALYTICS_READ,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_WRITE,
            Permission.PRODUCTION_WRITE,
            Permission.OPERATIONS_WRITE,
            Permission.COSTING_READ,
            Permission.DINING_ROOM_READ,
            Permission.DINING_ROOM_MANAGE,
            Permission.CUSTOMER_QR_READ,
            Permission.CUSTOMER_QR_MANAGE,
            Permission.SERVICE_SESSION_WRITE,
            Permission.SETTLEMENT_READ,
            Permission.SETTLEMENT_CREATE,
            Permission.PAYMENT_READ,
            Permission.PAYMENT_WRITE,
            Permission.ORDER_READ,
            Permission.ORDER_WRITE,
            Permission.ORDER_FULFILL,
            Permission.KITCHEN_READ,
            Permission.KITCHEN_OPERATE,
        }
    ),
    RestaurantRole.WAITER: frozenset(
        {
            Permission.RESTAURANT_READ,
            Permission.MENU_READ,
            Permission.OPERATIONS_WRITE,
            Permission.DINING_ROOM_READ,
            Permission.CUSTOMER_QR_READ,
            Permission.SERVICE_SESSION_WRITE,
            Permission.SETTLEMENT_READ,
            Permission.SETTLEMENT_CREATE,
            Permission.PAYMENT_READ,
            Permission.PAYMENT_WRITE,
            Permission.ORDER_READ,
            Permission.ORDER_WRITE,
            Permission.ORDER_FULFILL,
            Permission.KITCHEN_READ,
        }
    ),
    RestaurantRole.COOK: frozenset(
        {
            Permission.RESTAURANT_READ,
            Permission.MENU_READ,
            Permission.INVENTORY_READ,
            Permission.PRODUCTION_WRITE,
            Permission.KITCHEN_READ,
            Permission.KITCHEN_OPERATE,
        }
    ),
    RestaurantRole.VIEWER: frozenset(
        {
            Permission.RESTAURANT_READ,
            Permission.MENU_READ,
            Permission.DASHBOARD_READ,
            Permission.ANALYTICS_READ,
            Permission.INVENTORY_READ,
            Permission.COSTING_READ,
            Permission.DINING_ROOM_READ,
            Permission.SETTLEMENT_READ,
            Permission.PAYMENT_READ,
            Permission.ORDER_READ,
            Permission.KITCHEN_READ,
        }
    ),
}


def role_has_permission(role: str, permission: Permission) -> bool:
    try:
        normalized_role = RestaurantRole(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS[normalized_role]


def role_home_path(role: str) -> str:
    try:
        normalized_role = RestaurantRole(role)
    except ValueError:
        return "/app"
    if normalized_role == RestaurantRole.WAITER:
        return "/staff/waiter"
    if normalized_role == RestaurantRole.COOK:
        return "/staff/kitchen"
    return "/admin/dashboard"
