from __future__ import annotations

from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .intelligence import build_storefront_insights
from .models import (
    Category,
    CustomerProfile,
    InventoryReservation,
    Item,
    Order,
    ReturnRequest,
    StockLevel,
    StockMovement,
    SupportThread,
    Warehouse,
)


User = get_user_model()

REVENUE_STATUSES = [
    Order.Status.PLACED,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
]


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"))


def build_admin_dashboard(*, limit: int = 6) -> dict:
    order_queryset = (
        Order.objects.exclude(status=Order.Status.CART)
        .select_related("user", "coupon")
        .prefetch_related("items__item", "status_events")
        .order_by("-placed_at", "-created_at")
    )

    revenue_orders = [order for order in order_queryset if order.status in REVENUE_STATUSES]
    gross_revenue = sum((order.total for order in revenue_orders), Decimal("0.00"))
    paid_online_revenue = sum(
        (
            order.total
            for order in order_queryset
            if order.payment_status == Order.PaymentStatus.PAID
        ),
        Decimal("0.00"),
    )
    average_order_value = (
        _quantize(gross_revenue / len(revenue_orders))
        if revenue_orders
        else Decimal("0.00")
    )

    payment_mix = [
        {
            "code": row["payment_method"],
            "label": Order.PaymentMethod(row["payment_method"]).label,
            "count": row["count"],
        }
        for row in (
            order_queryset.values("payment_method")
            .annotate(count=Count("id"))
            .order_by("-count", "payment_method")
        )
    ]

    today = timezone.localdate()
    timeline_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    revenue_map = {day: Decimal("0.00") for day in timeline_days}
    order_count_map = {day: 0 for day in timeline_days}
    for order in revenue_orders:
        if not order.placed_at:
            continue
        order_day = timezone.localtime(order.placed_at).date()
        if order_day in revenue_map:
            revenue_map[order_day] += order.total
            order_count_map[order_day] += 1

    max_revenue = max(revenue_map.values()) if revenue_map else Decimal("0.00")
    revenue_timeline = [
        {
            "label": day.strftime("%b %d"),
            "total": float(_quantize(revenue_map[day])),
            "orders": order_count_map[day],
            "percent": (
                max(8, int((revenue_map[day] / max_revenue) * 100))
                if max_revenue > Decimal("0.00") and revenue_map[day] > Decimal("0.00")
                else 0
            ),
        }
        for day in timeline_days
    ]

    top_products = list(
        Item.objects.active()
        .with_metrics()
        .order_by("-sold_units_value", "-view_count", "title")[:limit]
    )
    low_stock_items = list(
        Item.objects.active()
        .filter(stock__lte=F("reorder_level"))
        .order_by("stock", "title")[:limit]
    )
    category_performance = list(
        Category.objects.filter(items__is_active=True)
        .annotate(
            item_count=Count("items", distinct=True),
            sold_units=Coalesce(
                Sum(
                    "items__order_items__quantity",
                    filter=Q(items__order_items__ordered=True),
                ),
                Value(0),
            ),
        )
        .order_by("-sold_units", "name")[:limit]
    )

    insights = build_storefront_insights(limit=limit)
    stock_levels = list(
        StockLevel.objects.select_related("warehouse", "item").order_by(
            "warehouse__priority",
            "item__title",
        )
    )
    network_on_hand = sum(stock_level.on_hand for stock_level in stock_levels)
    network_reserved = sum(stock_level.reserved for stock_level in stock_levels)

    return {
        "metrics": {
            "gross_revenue": float(_quantize(gross_revenue)),
            "paid_online_revenue": float(_quantize(paid_online_revenue)),
            "average_order_value": float(average_order_value),
            "open_orders": order_queryset.filter(
                status__in=[
                    Order.Status.PAYMENT_PENDING,
                    Order.Status.PLACED,
                    Order.Status.PROCESSING,
                    Order.Status.SHIPPED,
                ]
            ).count(),
            "pending_payment_orders": order_queryset.filter(
                status=Order.Status.PAYMENT_PENDING
            ).count(),
            "delivered_orders": order_queryset.filter(
                status=Order.Status.DELIVERED
            ).count(),
            "open_returns": ReturnRequest.objects.filter(
                status__in=[
                    ReturnRequest.Status.REQUESTED,
                    ReturnRequest.Status.APPROVED,
                    ReturnRequest.Status.RECEIVED,
                ]
            ).count(),
            "open_support_threads": SupportThread.objects.exclude(
                status__in=[SupportThread.Status.RESOLVED, SupportThread.Status.CLOSED]
            ).count(),
            "customers_with_orders": order_queryset.values("user").distinct().count(),
            "registered_users": User.objects.count(),
            "verified_profiles": CustomerProfile.objects.filter(email_verified=True).count(),
            "warehouse_count": Warehouse.objects.filter(is_active=True).count(),
            "network_on_hand": network_on_hand,
            "network_reserved": network_reserved,
            "network_available": max(network_on_hand - network_reserved, 0),
            "active_reservations": InventoryReservation.objects.filter(
                status=InventoryReservation.Status.ACTIVE
            ).count(),
        },
        "payment_mix": payment_mix,
        "revenue_timeline": revenue_timeline,
        "recent_orders": list(order_queryset[:8]),
        "top_products": top_products,
        "low_stock_items": low_stock_items,
        "category_performance": category_performance,
        "trending_items": insights["trending_items"],
        "top_rated_items": insights["top_rated_items"],
    }


def build_inventory_dashboard(*, limit: int = 10) -> dict:
    warehouses = list(
        Warehouse.objects.order_by("priority", "name").prefetch_related(
            "stock_levels__item"
        )
    )
    stock_levels = list(
        StockLevel.objects.select_related("warehouse", "item").order_by(
            "warehouse__priority",
            "item__title",
        )
    )
    active_reservations = list(
        InventoryReservation.objects.filter(
            status=InventoryReservation.Status.ACTIVE
        )
        .select_related("order", "item", "warehouse")
        .order_by("expires_at", "-created_at")
    )
    recent_stock_movements = list(
        StockMovement.objects.select_related("item", "warehouse", "related_warehouse", "actor")
        .order_by("-created_at", "-pk")[:limit]
    )

    warehouse_rows = []
    for warehouse in warehouses:
        warehouse_stock_levels = list(warehouse.stock_levels.all())
        on_hand_total = sum(stock_level.on_hand for stock_level in warehouse_stock_levels)
        reserved_total = sum(stock_level.reserved for stock_level in warehouse_stock_levels)
        warehouse_rows.append(
            {
                "warehouse": warehouse,
                "item_count": len(warehouse_stock_levels),
                "on_hand_total": on_hand_total,
                "reserved_total": reserved_total,
                "available_total": max(on_hand_total - reserved_total, 0),
            }
        )

    low_stock_levels = [
        stock_level
        for stock_level in stock_levels
        if stock_level.available_quantity <= stock_level.safety_stock
    ][:limit]
    fulfillment_queue = list(
        Order.objects.filter(
            status__in=[
                Order.Status.PAYMENT_PENDING,
                Order.Status.PLACED,
                Order.Status.PROCESSING,
            ]
        )
        .prefetch_related("items__item", "inventory_reservations__warehouse")
        .order_by("placed_at", "created_at")[:limit]
    )

    return {
        "inventory_metrics": {
            "active_warehouses": len([warehouse for warehouse in warehouses if warehouse.is_active]),
            "stock_level_count": len(stock_levels),
            "active_reservations": len(active_reservations),
            "network_on_hand": sum(stock_level.on_hand for stock_level in stock_levels),
            "network_reserved": sum(stock_level.reserved for stock_level in stock_levels),
            "network_available": sum(stock_level.available_quantity for stock_level in stock_levels),
            "at_risk_stock_levels": len(
                [
                    stock_level
                    for stock_level in stock_levels
                    if stock_level.available_quantity <= stock_level.safety_stock
                ]
            ),
        },
        "warehouse_rows": warehouse_rows[:limit],
        "low_stock_levels": low_stock_levels,
        "active_reservations": active_reservations[:limit],
        "fulfillment_queue": fulfillment_queue,
        "recent_stock_movements": recent_stock_movements,
    }
