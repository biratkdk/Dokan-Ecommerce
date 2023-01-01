from django.conf import settings
from django.db.models import F
from django.urls import reverse

from .intelligence import classify_customer
from .models import CustomerProfile, Order, OrderStatusEvent, SupportThread
from .permissions import (
    can_manage_inventory_network,
    can_manage_support_threads,
    can_view_inventory_dashboard,
    can_view_operations_dashboard,
)
from .session_features import get_compare_ids
from .services import get_active_order

NOTIFIABLE_ORDER_STATUSES = [
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
    Order.Status.CANCELLED,
]


def build_user_notifications(user, *, limit: int = 6) -> list[dict]:
    if not user.is_authenticated:
        return []

    notifications = []

    status_events = (
        OrderStatusEvent.objects.filter(
            order__user=user,
            status__in=NOTIFIABLE_ORDER_STATUSES,
        )
        .select_related("order")
        .order_by("-created_at")[:limit]
    )
    for event in status_events:
        notifications.append(
            {
                "kind": "order",
                "title": f"Order {event.order.reference} {event.get_status_display().lower()}",
                "detail": event.note,
                "url": reverse("store:order-history"),
                "created_at": event.created_at,
            }
        )

    awaiting_customer_threads = SupportThread.objects.filter(
        user=user,
        latest_support_message_at__isnull=False,
    ).filter(
        latest_support_message_at__gt=F("latest_customer_message_at")
    ).order_by("-latest_support_message_at")[:limit]
    for thread in awaiting_customer_threads:
        notifications.append(
            {
                "kind": "support",
                "title": f"New reply on “{thread.subject}”",
                "detail": "Support answered your ticket.",
                "url": reverse("store:support-threads"),
                "created_at": thread.latest_support_message_at,
            }
        )

    notifications.sort(key=lambda entry: entry["created_at"], reverse=True)
    return notifications[:limit]


def cart_summary(request):
    order = get_active_order(request.user)
    segment = classify_customer(request.user) if request.user.is_authenticated else None
    can_manage_support = can_manage_support_threads(request.user)
    support_threads_count = 0
    if request.user.is_authenticated:
        support_thread_queryset = SupportThread.objects.exclude(
            status__in=[SupportThread.Status.RESOLVED, SupportThread.Status.CLOSED]
        )
        if not can_manage_support:
            support_thread_queryset = support_thread_queryset.filter(user=request.user)
        support_threads_count = support_thread_queryset.count()
    profile = (
        CustomerProfile.objects.filter(user=request.user).only("email_verified").first()
        if request.user.is_authenticated
        else None
    )
    notifications = build_user_notifications(request.user)
    return {
        "cart_items_count": order.total_items if order else 0,
        "wishlist_items_count": request.user.wishlist_items.count() if request.user.is_authenticated else 0,
        "compare_items_count": len(get_compare_ids(request)),
        "support_threads_count": support_threads_count,
        "support_contact_email": settings.SUPPORT_CONTACT_EMAIL,
        "is_email_verified": bool(profile and profile.email_verified),
        "customer_segment_label": segment.label if segment else "",
        "can_view_operations_dashboard": can_view_operations_dashboard(request.user),
        "can_view_inventory_dashboard": can_view_inventory_dashboard(request.user),
        "can_manage_inventory_network": can_manage_inventory_network(request.user),
        "notifications": notifications,
        "notifications_count": len(notifications),
    }
