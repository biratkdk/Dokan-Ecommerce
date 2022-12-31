from django.conf import settings

from .intelligence import classify_customer
from .models import CustomerProfile, SupportThread
from .permissions import (
    can_manage_inventory_network,
    can_manage_support_threads,
    can_view_inventory_dashboard,
    can_view_operations_dashboard,
)
from .session_features import get_compare_ids
from .services import get_active_order


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
    }
