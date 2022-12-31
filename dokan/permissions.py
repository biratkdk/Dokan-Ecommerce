from __future__ import annotations


SUPPORT_MANAGER_PERMISSION = "dokan.manage_support_threads"
OPERATIONS_DASHBOARD_PERMISSION = "dokan.view_operations_dashboard"
INVENTORY_DASHBOARD_PERMISSION = "dokan.view_inventory_dashboard"
INVENTORY_NETWORK_PERMISSION = "dokan.manage_inventory_network"
STOCK_RESERVATIONS_PERMISSION = "dokan.manage_stock_reservations"
CUSTOMER_ACCOUNTS_PERMISSION = "dokan.manage_customer_accounts"


def _has_any_permission(user, permissions: list[str]) -> bool:
    return bool(
        user
        and user.is_authenticated
        and any(user.has_perm(permission) for permission in permissions)
    )


def can_manage_support_threads(user) -> bool:
    return _has_any_permission(user, [SUPPORT_MANAGER_PERMISSION])


def can_view_operations_dashboard(user) -> bool:
    return _has_any_permission(user, [OPERATIONS_DASHBOARD_PERMISSION])


def can_view_inventory_dashboard(user) -> bool:
    return _has_any_permission(
        user,
        [INVENTORY_DASHBOARD_PERMISSION, INVENTORY_NETWORK_PERMISSION],
    )


def can_manage_inventory_network(user) -> bool:
    return _has_any_permission(
        user,
        [INVENTORY_NETWORK_PERMISSION, STOCK_RESERVATIONS_PERMISSION],
    )


def can_manage_customer_accounts(user) -> bool:
    return _has_any_permission(user, [CUSTOMER_ACCOUNTS_PERMISSION])


def user_permission_codes(user) -> list[str]:
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser:
        return sorted(
            set(
                user.get_all_permissions()
                | {
                    SUPPORT_MANAGER_PERMISSION,
                    OPERATIONS_DASHBOARD_PERMISSION,
                    INVENTORY_DASHBOARD_PERMISSION,
                    INVENTORY_NETWORK_PERMISSION,
                    STOCK_RESERVATIONS_PERMISSION,
                    CUSTOMER_ACCOUNTS_PERMISSION,
                }
            )
        )
    return sorted(user.get_all_permissions())


def user_capability_map(user) -> dict[str, bool]:
    return {
        "authenticated": bool(user and user.is_authenticated),
        "is_staff": bool(user and user.is_authenticated and user.is_staff),
        "is_superuser": bool(user and user.is_authenticated and user.is_superuser),
        "can_manage_support_threads": can_manage_support_threads(user),
        "can_view_operations_dashboard": can_view_operations_dashboard(user),
        "can_view_inventory_dashboard": can_view_inventory_dashboard(user),
        "can_manage_inventory_network": can_manage_inventory_network(user),
        "can_manage_customer_accounts": can_manage_customer_accounts(user),
    }


def user_role_labels(user) -> list[str]:
    if not user or not user.is_authenticated:
        return []
    labels = list(user.groups.order_by("name").values_list("name", flat=True))
    if user.is_superuser:
        labels.insert(0, "Superuser")
    elif user.is_staff:
        labels.insert(0, "Staff")
    return labels
