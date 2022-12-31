from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_delete, post_migrate, post_save
from django.dispatch import receiver

from .models import Item, ProductImage, StockLevel, Warehouse


DEFAULT_WAREHOUSE_CODE = "CENTRAL"

ROLE_MATRIX = {
    "Support Team": [
        "manage_support_threads",
        "view_supportthread",
        "change_supportthread",
        "view_supportmessage",
        "add_supportmessage",
        "change_supportmessage",
        "view_order",
        "view_returnrequest",
        "view_emailnotification",
    ],
    "Support Agent": [
        "manage_support_threads",
        "view_supportthread",
        "change_supportthread",
        "view_supportmessage",
        "add_supportmessage",
        "change_supportmessage",
        "view_order",
        "view_returnrequest",
        "view_emailnotification",
    ],
    "Support Lead": [
        "manage_support_threads",
        "manage_customer_accounts",
        "view_supportthread",
        "change_supportthread",
        "view_supportmessage",
        "add_supportmessage",
        "change_supportmessage",
        "view_customerprofile",
        "change_customerprofile",
        "view_loginactivity",
        "view_order",
        "view_returnrequest",
        "change_returnrequest",
        "view_emailnotification",
        "view_user",
        "change_user",
    ],
    "Operations Team": [
        "view_operations_dashboard",
        "view_inventory_dashboard",
        "view_order",
        "view_returnrequest",
        "view_item",
        "view_stockmovement",
        "view_coupon",
        "view_inventoryreservation",
        "view_stocklevel",
        "view_warehouse",
        "view_emailnotification",
    ],
    "Operations Analyst": [
        "view_operations_dashboard",
        "view_inventory_dashboard",
        "view_order",
        "view_returnrequest",
        "view_item",
        "view_stockmovement",
        "view_coupon",
        "view_inventoryreservation",
        "view_stocklevel",
        "view_warehouse",
        "view_emailnotification",
    ],
    "Inventory Manager": [
        "manage_inventory_network",
        "manage_stock_reservations",
        "view_inventory_dashboard",
        "view_stocklevel",
        "add_stocklevel",
        "change_stocklevel",
        "view_stockmovement",
        "view_warehouse",
        "add_warehouse",
        "change_warehouse",
        "view_inventoryreservation",
        "change_inventoryreservation",
        "view_item",
        "change_item",
        "view_order",
    ],
    "Warehouse Manager": [
        "manage_inventory_network",
        "manage_stock_reservations",
        "view_inventory_dashboard",
        "view_stocklevel",
        "change_stocklevel",
        "view_stockmovement",
        "view_warehouse",
        "change_warehouse",
        "view_inventoryreservation",
        "change_inventoryreservation",
        "view_order",
        "change_order",
        "view_orderstatusevent",
        "add_orderstatusevent",
        "change_orderstatusevent",
    ],
    "Finance Analyst": [
        "view_operations_dashboard",
        "view_order",
        "view_coupon",
        "view_emailnotification",
        "view_returnrequest",
    ],
    "Merchandising Manager": [
        "view_item",
        "add_item",
        "change_item",
        "view_productimage",
        "add_productimage",
        "change_productimage",
        "view_brand",
        "add_brand",
        "change_brand",
        "view_category",
        "add_category",
        "change_category",
        "view_coupon",
        "add_coupon",
        "change_coupon",
    ],
    "Customer Success Manager": [
        "manage_customer_accounts",
        "manage_support_threads",
        "view_customerprofile",
        "change_customerprofile",
        "view_loginactivity",
        "view_supportthread",
        "change_supportthread",
        "view_supportmessage",
        "add_supportmessage",
        "change_supportmessage",
        "view_emailnotification",
        "view_address",
        "change_address",
        "view_user",
        "change_user",
    ],
}


def _ensure_default_warehouse() -> Warehouse:
    warehouse, _ = Warehouse.objects.get_or_create(
        code=DEFAULT_WAREHOUSE_CODE,
        defaults={
            "name": "Central Fulfillment Center",
            "city": "Kathmandu",
            "state": "Bagmati",
            "country": "Nepal",
            "priority": 1,
            "is_active": True,
        },
    )
    return warehouse


def _sync_group(group_name: str, *, permission_codenames: list[str]) -> None:
    group, _ = Group.objects.get_or_create(name=group_name)
    permissions = Permission.objects.filter(
        content_type__app_label__in=["dokan", "auth"],
        codename__in=permission_codenames,
    )
    group.permissions.set(permissions)


@receiver(post_migrate)
def ensure_default_staff_groups(sender, **kwargs) -> None:
    if sender.name != "dokan":
        return

    warehouse = _ensure_default_warehouse()
    for group_name, permission_codenames in ROLE_MATRIX.items():
        _sync_group(group_name, permission_codenames=permission_codenames)
    for item in Item.objects.all().only("id", "stock", "reorder_level"):
        if not StockLevel.objects.filter(item=item).exists():
            StockLevel.objects.create(
                warehouse=warehouse,
                item=item,
                on_hand=item.stock,
                reserved=0,
                safety_stock=item.reorder_level,
            )


@receiver(post_save, sender=Item)
def ensure_stock_level_for_new_item(sender, instance: Item, created: bool, **kwargs) -> None:
    if instance.stock_levels.exists():
        instance.stock_levels.exclude(safety_stock=instance.reorder_level).update(
            safety_stock=instance.reorder_level
        )
        return
    warehouse = _ensure_default_warehouse()
    StockLevel.objects.create(
        warehouse=warehouse,
        item=instance,
        on_hand=instance.stock,
        reserved=0,
        safety_stock=instance.reorder_level,
    )


@receiver(post_save, sender=StockLevel)
def sync_item_stock_cache_on_stock_level_save(sender, instance: StockLevel, **kwargs) -> None:
    from .services import sync_item_available_stock

    sync_item_available_stock({instance.item_id})


@receiver(post_delete, sender=StockLevel)
def sync_item_stock_cache_on_stock_level_delete(sender, instance: StockLevel, **kwargs) -> None:
    from .services import sync_item_available_stock

    sync_item_available_stock({instance.item_id})


@receiver(post_save, sender=Warehouse)
def sync_item_stock_cache_on_warehouse_save(sender, instance: Warehouse, **kwargs) -> None:
    from .services import sync_item_available_stock

    item_ids = set(instance.stock_levels.values_list("item_id", flat=True))
    sync_item_available_stock(item_ids)


@receiver(post_delete, sender=Warehouse)
def sync_item_stock_cache_on_warehouse_delete(sender, instance: Warehouse, **kwargs) -> None:
    from .services import sync_item_available_stock

    item_ids = set(instance.stock_levels.values_list("item_id", flat=True))
    sync_item_available_stock(item_ids)


@receiver(post_save, sender=ProductImage)
def normalize_primary_product_image(sender, instance: ProductImage, created: bool, **kwargs) -> None:
    if instance.is_primary:
        ProductImage.objects.filter(item=instance.item).exclude(pk=instance.pk).update(
            is_primary=False
        )
        return

    sibling_images = ProductImage.objects.filter(item=instance.item).exclude(pk=instance.pk)
    if created and not sibling_images.filter(is_primary=True).exists():
        ProductImage.objects.filter(pk=instance.pk).update(is_primary=True)
