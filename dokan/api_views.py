from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import F, Prefetch, Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .accounts import ensure_customer_profile, mark_email_unverified
from .api_serializers import (
    serialize_address,
    serialize_customer_health,
    serialize_customer_profile,
    serialize_customer_segment,
    serialize_inventory_reservation,
    serialize_item,
    serialize_login_activity,
    serialize_order,
    serialize_recommendation,
    serialize_review,
    serialize_search_result,
    serialize_stock_level,
    serialize_support_suggestion,
    serialize_support_thread,
    serialize_warehouse,
)
from .forms import (
    AccountIdentityForm,
    AccountPasswordChangeForm,
    AddressBookForm,
    CustomerProfileSettingsForm,
)
from .intelligence import (
    assess_customer_health,
    build_storefront_insights,
    classify_customer,
    rank_catalog_search,
    recommend_items,
    suggest_support_answers,
)
from .models import Address, InventoryReservation, Item, Order, StockLevel, SupportThread, Warehouse
from .notifications import send_email_verification_email
from .permissions import (
    can_manage_inventory_network,
    can_view_inventory_dashboard,
    user_capability_map,
    user_permission_codes,
    user_role_labels,
)
from .session_features import get_compare_items, get_recently_viewed_items
from .services import get_active_order, toggle_wishlist
from .support import create_support_thread, post_support_message, support_queryset_for_user


def _json(payload: dict, *, status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status)


def _json_error(message: str, *, status: int = 400, code: str = "invalid_request") -> JsonResponse:
    return _json({"error": {"code": code, "message": message}}, status=status)


def _parse_json_body(request) -> dict:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError("Request body must contain valid JSON.")
    if not isinstance(payload, dict):
        raise ValidationError("JSON body must be an object.")
    return payload


def _limit_offset(request, *, default_limit: int = 20, max_limit: int = 50) -> tuple[int, int]:
    try:
        limit = int(request.GET.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, max_limit))
    offset = max(0, offset)
    return limit, offset


def _parse_decimal_param(request, key: str) -> Decimal | None:
    raw = request.GET.get(key, "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValidationError(f"{key} must be a valid decimal value.")


@require_GET
def api_root(request):
    return _json(
        {
            "application": "Redstore Advanced Ecommerce",
            "version": "v1",
            "endpoints": {
                "catalog": "/api/v1/catalog/",
                "product_detail": "/api/v1/catalog/<slug>/",
                "recommendations": "/api/v1/recommendations/<slug>/",
                "compare": "/api/v1/compare/",
                "analytics": "/api/v1/analytics/overview/",
                "account": "/api/v1/account/overview/",
                "account_security": "/api/v1/account/security/",
                "assistant": "/api/v1/intelligence/assistant/?q=<query>",
                "support_threads": "/api/v1/support/threads/",
                "support_thread_detail": "/api/v1/support/threads/<id>/",
                "health": "/api/v1/health/",
                "order_tracking": "/api/v1/orders/<reference>/",
                "wishlist_toggle": "/api/v1/wishlist/<slug>/toggle/",
            },
        }
    )


@require_GET
def api_catalog(request):
    queryset = Item.objects.active().with_metrics()
    search_term = request.GET.get("q", "").strip()
    category_slug = request.GET.get("category", "").strip()
    brand_slug = request.GET.get("brand", "").strip()

    if category_slug:
        queryset = queryset.filter(catalog_category__slug=category_slug)
    if brand_slug:
        queryset = queryset.filter(brand__slug=brand_slug)

    page_number = request.GET.get("page", 1)

    if search_term:
        filtered_queryset = queryset.filter(
            Q(title__icontains=search_term)
            | Q(short_description__icontains=search_term)
            | Q(description__icontains=search_term)
            | Q(brand__name__icontains=search_term)
            | Q(catalog_category__name__icontains=search_term)
        )
        ranked_matches = rank_catalog_search(search_term, queryset=list(filtered_queryset))
        paginator = Paginator(ranked_matches, 8)
        page = paginator.get_page(page_number)
        return _json(
            {
                "count": paginator.count,
                "page": page.number,
                "num_pages": paginator.num_pages,
                "results": [serialize_item(entry.item) for entry in page.object_list],
                "search_matches": [
                    serialize_search_result(entry) for entry in page.object_list
                ],
            }
        )

    paginator = Paginator(queryset.order_by("-featured", "-is_trending", "title"), 8)
    page = paginator.get_page(page_number)
    return _json(
        {
            "count": paginator.count,
            "page": page.number,
            "num_pages": paginator.num_pages,
            "results": [serialize_item(item) for item in page.object_list],
        }
    )


@require_GET
def api_product_detail(request, slug: str):
    item = get_object_or_404(Item.objects.active().with_metrics(), slug=slug)
    return _json(
        {
            "product": serialize_item(item, include_details=True),
            "reviews": [
                serialize_review(review)
                for review in item.reviews.approved().select_related("user")[:10]
            ],
            "recommendations": [
                serialize_recommendation(entry)
                for entry in recommend_items(item, limit=4)
            ],
        }
    )


@require_GET
def api_recommendations(request, slug: str):
    item = get_object_or_404(Item.objects.active().with_metrics(), slug=slug)
    recommendations = recommend_items(item, limit=6)
    return _json(
        {
            "source_product": serialize_item(item),
            "recommendations": [
                serialize_recommendation(entry)
                for entry in recommendations
            ],
        }
    )


@require_GET
def api_compare_state(request):
    compare_items = get_compare_items(request)
    recent_items = get_recently_viewed_items(request, limit=6)
    return _json(
        {
            "compare_count": len(compare_items),
            "compare_items": [serialize_item(item, include_details=True) for item in compare_items],
            "recently_viewed": [serialize_item(item) for item in recent_items],
        }
    )


@require_GET
def api_analytics_overview(request):
    insights = build_storefront_insights(
        user=request.user if request.user.is_authenticated else None,
        limit=5,
    )
    return _json(
        {
            "trending_items": [serialize_item(item) for item in insights["trending_items"]],
            "top_rated_items": [serialize_item(item) for item in insights["top_rated_items"]],
            "low_stock_items": [serialize_item(item) for item in insights["low_stock_items"]],
            "value_picks": [serialize_item(item) for item in insights["value_picks"]],
            "customer_segment": serialize_customer_segment(insights["customer_segment"]),
            "customer_health": serialize_customer_health(insights["customer_health"]),
        }
    )


@require_GET
def api_health(request):
    return _json(
        {
            "status": "ok",
            "application": "redstore",
            "catalog_items": Item.objects.filter(is_active=True).count(),
            "pending_payments": Order.objects.filter(status=Order.Status.PAYMENT_PENDING).count(),
            "open_support_threads": SupportThread.objects.exclude(
                status__in=[SupportThread.Status.RESOLVED, SupportThread.Status.CLOSED]
            ).count(),
            "timestamp": timezone.now().isoformat(),
        }
    )


@login_required
@require_GET
def api_account_overview(request):
    active_order = get_active_order(request.user)
    segment = classify_customer(request.user)
    health = assess_customer_health(request.user)
    profile = ensure_customer_profile(request.user)
    recent_orders = (
        Order.objects.filter(user=request.user)
        .exclude(status=Order.Status.CART)
        .prefetch_related("items__item", "status_events", "return_requests__order_item__item")[:5]
    )
    return _json(
        {
            "user": request.user.username,
            "profile": serialize_customer_profile(profile),
            "wishlist_count": request.user.wishlist_items.count(),
            "active_cart": serialize_order(active_order) if active_order else None,
            "recent_orders": [serialize_order(order) for order in recent_orders],
            "customer_segment": serialize_customer_segment(segment),
            "customer_health": serialize_customer_health(health),
        }
    )


@login_required
@require_GET
def api_account_security(request):
    profile = ensure_customer_profile(request.user)
    recent_logins = request.user.login_activities.all()[:10]
    return _json(
        {
            "user": request.user.username,
            "profile": serialize_customer_profile(profile),
            "recent_logins": [serialize_login_activity(activity) for activity in recent_logins],
        }
    )


@require_GET
def api_ai_assistant(request):
    query = request.GET.get("q", "").strip()
    if not query:
        return _json({"error": "Query parameter q is required."}, status=400)

    order = None
    order_reference = request.GET.get("reference", "").strip()
    if request.user.is_authenticated and order_reference:
        order = Order.objects.filter(user=request.user, reference=order_reference).first()

    catalog_matches = rank_catalog_search(query, queryset=list(Item.objects.active().with_metrics()), limit=5)
    support_suggestions = suggest_support_answers(query, order=order, limit=3)
    return _json(
        {
            "query": query,
            "catalog_matches": [
                serialize_search_result(entry) for entry in catalog_matches
            ],
            "support_suggestions": [
                serialize_support_suggestion(entry) for entry in support_suggestions
            ],
        }
    )


@login_required
@require_GET
def api_order_tracking(request, reference: str):
    order = get_object_or_404(
        Order.objects.filter(user=request.user).prefetch_related(
            "items__item",
            "status_events",
            "return_requests__order_item__item",
        ),
        reference=reference,
    )
    return _json({"order": serialize_order(order)})


@login_required
@require_http_methods(["GET", "POST"])
def api_support_threads(request):
    if request.method == "POST":
        order = None
        order_reference = request.POST.get("order_reference", "").strip()
        if order_reference:
            order = Order.objects.filter(user=request.user, reference=order_reference).first()
            if not order:
                return _json({"error": "Order reference was not found."}, status=400)
        try:
            thread = create_support_thread(
                request.user,
                subject=request.POST.get("subject", "").strip(),
                category=request.POST.get("category", "general").strip() or "general",
                priority=request.POST.get("priority", "normal").strip() or "normal",
                message=request.POST.get("message", "").strip(),
                order=order,
            )
        except ValidationError as exc:
            return _json({"error": str(exc)}, status=400)
        return _json(
            {"thread": serialize_support_thread(thread, include_messages=True)},
            status=201,
        )

    threads = support_queryset_for_user(request.user)[:20]
    return _json({"threads": [serialize_support_thread(thread) for thread in threads]})


@login_required
@require_http_methods(["GET", "POST"])
def api_support_thread_detail(request, thread_id: int):
    thread = get_object_or_404(support_queryset_for_user(request.user), pk=thread_id)

    if request.method == "POST":
        try:
            message = post_support_message(
                thread,
                request.user,
                message=request.POST.get("message", "").strip(),
            )
        except ValidationError as exc:
            return _json({"error": str(exc)}, status=400)
        thread.refresh_from_db()
        return _json(
            {
                "thread": serialize_support_thread(thread, include_messages=True),
                "message_id": message.pk,
            },
            status=201,
        )

    return _json({"thread": serialize_support_thread(thread, include_messages=True)})


@login_required
@require_POST
def api_wishlist_toggle(request, slug: str):
    item = get_object_or_404(Item.objects.active(), slug=slug)
    added = toggle_wishlist(request.user, item)
    return _json(
        {
            "product": item.slug,
            "in_wishlist": added,
            "wishlist_count": request.user.wishlist_items.count(),
        }
    )


@require_GET
def api_v2_root(request):
    return _json(
        {
            "application": "Redstore Advanced Ecommerce",
            "version": "v2",
            "style": "Structured JSON API with write endpoints and inventory visibility",
            "endpoints": {
                "catalog": "/api/v2/catalog/",
                "account_profile": "/api/v2/account/profile/",
                "account_security": "/api/v2/account/security/",
                "account_access": "/api/v2/account/access/",
                "account_password": "/api/v2/account/password/",
                "account_addresses": "/api/v2/account/addresses/",
                "inventory_overview": "/api/v2/inventory/overview/",
                "inventory_warehouses": "/api/v2/inventory/warehouses/",
                "inventory_active_reservations": "/api/v2/inventory/reservations/active/",
                "order_reservations": "/api/v2/orders/<reference>/reservations/",
            },
        }
    )


@require_GET
def api_v2_catalog(request):
    try:
        min_price = _parse_decimal_param(request, "min_price")
        max_price = _parse_decimal_param(request, "max_price")
    except ValidationError as exc:
        return _json_error(str(exc))

    queryset = (
        Item.objects.active()
        .with_metrics()
        .prefetch_related("stock_levels__warehouse")
        .annotate(display_price=Coalesce("discount_price", "price"))
    )
    search_term = request.GET.get("q", "").strip()
    category_slug = request.GET.get("category", "").strip()
    brand_slug = request.GET.get("brand", "").strip()
    sort = request.GET.get("sort", "latest").strip()
    in_stock_only = request.GET.get("in_stock", "").strip().lower() in {"1", "true", "yes"}
    include_inventory = request.GET.get("include_inventory", "").strip().lower() in {"1", "true", "yes"}
    limit, offset = _limit_offset(request)

    if category_slug:
        queryset = queryset.filter(catalog_category__slug=category_slug)
    if brand_slug:
        queryset = queryset.filter(brand__slug=brand_slug)
    if min_price is not None:
        queryset = queryset.filter(display_price__gte=min_price)
    if max_price is not None:
        queryset = queryset.filter(display_price__lte=max_price)
    if in_stock_only:
        queryset = queryset.filter(stock__gt=0)

    if search_term:
        queryset = queryset.filter(
            Q(title__icontains=search_term)
            | Q(short_description__icontains=search_term)
            | Q(description__icontains=search_term)
            | Q(brand__name__icontains=search_term)
            | Q(catalog_category__name__icontains=search_term)
        )
        ranked_results = rank_catalog_search(search_term, queryset=list(queryset))
        total_count = len(ranked_results)
        page_results = ranked_results[offset : offset + limit]
        results = []
        for entry in page_results:
            payload = serialize_item(entry.item, include_details=True)
            payload["search_score"] = entry.score
            payload["search_reasons"] = entry.reasons
            if include_inventory:
                payload["stock_levels"] = [
                    serialize_stock_level(stock_level)
                    for stock_level in entry.item.stock_levels.all()
                ]
            results.append(payload)
        return _json(
            {
                "meta": {
                    "count": total_count,
                    "limit": limit,
                    "offset": offset,
                    "returned": len(results),
                    "sort": sort,
                },
                "results": results,
            }
        )

    sort_options = {
        "latest": ("-created_at", "title"),
        "price_low": ("display_price", "title"),
        "price_high": ("-display_price", "title"),
        "rating": ("-average_rating_value", "-review_count_value", "title"),
        "popular": ("-sold_units_value", "-wishlist_count_value", "-view_count", "title"),
        "demand": ("-stock", "-view_count", "title"),
    }
    ordered_queryset = queryset.order_by(*sort_options.get(sort, ("-created_at", "title")))
    total_count = ordered_queryset.count()
    items = list(ordered_queryset[offset : offset + limit])
    results = []
    for item in items:
        payload = serialize_item(item, include_details=True)
        if include_inventory:
            payload["stock_levels"] = [
                serialize_stock_level(stock_level)
                for stock_level in item.stock_levels.all()
            ]
        results.append(payload)

    return _json(
        {
            "meta": {
                "count": total_count,
                "limit": limit,
                "offset": offset,
                "returned": len(results),
                "sort": sort,
            },
            "results": results,
        }
    )


@login_required
@require_http_methods(["GET", "PATCH"])
def api_v2_account_profile(request):
    profile = ensure_customer_profile(request.user)
    if request.method == "GET":
        return _json(
            {
                "user": {
                    "username": request.user.username,
                    "email": request.user.email,
                    "first_name": request.user.first_name,
                    "last_name": request.user.last_name,
                },
                "profile": serialize_customer_profile(profile),
            }
        )

    try:
        payload = _parse_json_body(request)
    except ValidationError as exc:
        return _json_error(str(exc))

    current_email = request.user.email
    user_form = AccountIdentityForm(payload, instance=request.user)
    profile_form = CustomerProfileSettingsForm(payload, instance=profile)
    if not (user_form.is_valid() and profile_form.is_valid()):
        return _json(
            {
                "errors": {
                    "user": user_form.errors,
                    "profile": profile_form.errors,
                }
            },
            status=400,
        )

    updated_user = user_form.save()
    profile_form.save()
    email_reverification_required = current_email.strip().lower() != updated_user.email.strip().lower()
    if email_reverification_required:
        mark_email_unverified(updated_user)
        send_email_verification_email(updated_user, request=request)

    return _json(
        {
            "message": "Account profile updated.",
            "email_reverification_required": email_reverification_required,
            "user": {
                "username": updated_user.username,
                "email": updated_user.email,
                "first_name": updated_user.first_name,
                "last_name": updated_user.last_name,
            },
            "profile": serialize_customer_profile(ensure_customer_profile(updated_user)),
        }
    )


@login_required
@require_GET
def api_v2_account_security(request):
    profile = ensure_customer_profile(request.user)
    recent_logins = request.user.login_activities.all()[:10]
    return _json(
        {
            "profile": serialize_customer_profile(profile),
            "roles": user_role_labels(request.user),
            "capabilities": user_capability_map(request.user),
            "recent_logins": [serialize_login_activity(activity) for activity in recent_logins],
        }
    )


@login_required
@require_GET
def api_v2_account_access(request):
    return _json(
        {
            "roles": user_role_labels(request.user),
            "permissions": user_permission_codes(request.user),
            "capabilities": user_capability_map(request.user),
        }
    )


@login_required
@require_POST
def api_v2_account_password(request):
    try:
        payload = _parse_json_body(request)
    except ValidationError as exc:
        return _json_error(str(exc))

    password_form = AccountPasswordChangeForm(request.user, payload)
    if not password_form.is_valid():
        return _json({"errors": password_form.errors}, status=400)

    updated_user = password_form.save()
    update_session_auth_hash(request, updated_user)
    return _json({"message": "Password updated successfully."})


@login_required
@require_http_methods(["GET", "POST"])
def api_v2_account_addresses(request):
    if request.method == "GET":
        addresses = request.user.addresses.all()
        return _json(
            {
                "count": addresses.count(),
                "results": [serialize_address(address) for address in addresses],
            }
        )

    try:
        payload = _parse_json_body(request)
    except ValidationError as exc:
        return _json_error(str(exc))

    form = AddressBookForm(payload)
    if not form.is_valid():
        return _json({"errors": form.errors}, status=400)

    address = form.save(commit=False)
    address.user = request.user
    if address.default:
        request.user.addresses.filter(
            address_type=address.address_type,
            default=True,
        ).update(default=False)
    address.save()
    return _json({"address": serialize_address(address)}, status=201)


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def api_v2_account_address_detail(request, address_id: int):
    address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
    if request.method == "GET":
        return _json({"address": serialize_address(address)})

    if request.method == "DELETE":
        address.delete()
        return _json({"deleted": True})

    try:
        payload = _parse_json_body(request)
    except ValidationError as exc:
        return _json_error(str(exc))

    form = AddressBookForm(payload, instance=address)
    if not form.is_valid():
        return _json({"errors": form.errors}, status=400)

    address = form.save(commit=False)
    address.user = request.user
    if address.default:
        request.user.addresses.filter(
            address_type=address.address_type,
            default=True,
        ).exclude(pk=address.pk).update(default=False)
    address.save()
    return _json({"address": serialize_address(address)})


@login_required
@require_POST
def api_v2_account_address_default(request, address_id: int):
    address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
    request.user.addresses.filter(
        address_type=address.address_type,
        default=True,
    ).exclude(pk=address.pk).update(default=False)
    if not address.default:
        address.default = True
        address.save(update_fields=["default", "updated_at"])
    return _json({"address": serialize_address(address), "default_updated": True})


@login_required
@require_GET
def api_v2_order_reservations(request, reference: str):
    order_queryset = Order.objects.prefetch_related(
        "inventory_reservations__warehouse",
        "inventory_reservations__item",
        "items__item",
    )
    if not can_view_inventory_dashboard(request.user):
        order_queryset = order_queryset.filter(user=request.user)
    order = get_object_or_404(order_queryset, reference=reference)
    reservations = order.inventory_reservations.select_related("warehouse", "item", "order_item")
    return _json(
        {
            "order": {
                "reference": order.reference,
                "status": order.get_status_display(),
                "payment_status": order.get_payment_status_display(),
            },
            "reservations": [
                serialize_inventory_reservation(reservation)
                for reservation in reservations
            ],
        }
    )


@login_required
@require_GET
def api_v2_inventory_overview(request):
    if not can_view_inventory_dashboard(request.user):
        return _json_error("You do not have access to inventory data.", status=403, code="forbidden")

    queryset = (
        Item.objects.active()
        .with_metrics()
        .prefetch_related(
            "stock_levels__warehouse",
            Prefetch(
                "inventory_reservations",
                queryset=InventoryReservation.objects.filter(
                    status=InventoryReservation.Status.ACTIVE
                ).select_related("warehouse", "order", "order_item"),
                to_attr="active_reservation_rows",
            ),
        )
        .order_by("title")
    )
    search_term = request.GET.get("q", "").strip()
    warehouse_code = request.GET.get("warehouse", "").strip()
    low_stock_only = request.GET.get("low_stock_only", "").strip().lower() in {"1", "true", "yes"}
    limit, offset = _limit_offset(request)

    if search_term:
        queryset = queryset.filter(
            Q(title__icontains=search_term)
            | Q(sku__icontains=search_term)
            | Q(brand__name__icontains=search_term)
        )
    if warehouse_code:
        queryset = queryset.filter(stock_levels__warehouse__code__iexact=warehouse_code).distinct()
    if low_stock_only:
        queryset = queryset.filter(stock__lte=F("reorder_level"))

    total_count = queryset.count()
    items = list(queryset[offset : offset + limit])
    active_reservations = InventoryReservation.objects.filter(
        status=InventoryReservation.Status.ACTIVE
    ).count()
    warehouses = list(
        Warehouse.objects.filter(is_active=True)
        .prefetch_related("stock_levels")
        .order_by("priority", "name")
    )

    return _json(
        {
            "meta": {
                "count": total_count,
                "limit": limit,
                "offset": offset,
                "active_reservations": active_reservations,
                "warehouse_count": len(warehouses),
            },
            "warehouses": [
                {
                    **serialize_warehouse(warehouse),
                    "stock_levels": len(warehouse.stock_levels.all()),
                }
                for warehouse in warehouses
            ],
            "results": [
                {
                    **serialize_item(item, include_details=True),
                    "stock_levels": [
                        serialize_stock_level(stock_level)
                        for stock_level in item.stock_levels.all()
                    ],
                    "active_reservations": [
                        serialize_inventory_reservation(reservation)
                        for reservation in item.active_reservation_rows[:10]
                    ],
                }
                for item in items
            ],
        }
    )


@login_required
@require_GET
def api_v2_inventory_warehouses(request):
    if not can_view_inventory_dashboard(request.user):
        return _json_error("You do not have access to warehouse data.", status=403, code="forbidden")

    include_stock = request.GET.get("include_stock", "").strip().lower() in {"1", "true", "yes"}
    include_inactive = request.GET.get("include_inactive", "").strip().lower() in {"1", "true", "yes"}
    limit, offset = _limit_offset(request, default_limit=10, max_limit=25)

    queryset = Warehouse.objects.order_by("priority", "name").prefetch_related(
        Prefetch(
            "stock_levels",
            queryset=StockLevel.objects.select_related("item").order_by("item__title"),
        )
    )
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    total_count = queryset.count()
    warehouses = list(queryset[offset : offset + limit])
    results = []
    for warehouse in warehouses:
        stock_levels = list(warehouse.stock_levels.all())
        on_hand_total = sum(stock_level.on_hand for stock_level in stock_levels)
        reserved_total = sum(stock_level.reserved for stock_level in stock_levels)
        payload = {
            **serialize_warehouse(warehouse),
            "item_count": len(stock_levels),
            "on_hand_total": on_hand_total,
            "reserved_total": reserved_total,
            "available_total": max(on_hand_total - reserved_total, 0),
        }
        if include_stock:
            payload["stock_levels"] = [serialize_stock_level(stock_level) for stock_level in stock_levels]
        results.append(payload)

    return _json(
        {
            "meta": {
                "count": total_count,
                "limit": limit,
                "offset": offset,
                "returned": len(results),
            },
            "results": results,
        }
    )


@login_required
@require_GET
def api_v2_inventory_active_reservations(request):
    if not can_view_inventory_dashboard(request.user):
        return _json_error("You do not have access to reservation data.", status=403, code="forbidden")

    queryset = InventoryReservation.objects.filter(
        status=InventoryReservation.Status.ACTIVE
    ).select_related("order", "order_item", "item", "warehouse")
    warehouse_code = request.GET.get("warehouse", "").strip()
    item_slug = request.GET.get("item", "").strip()
    order_reference = request.GET.get("reference", "").strip()
    limit, offset = _limit_offset(request)

    if warehouse_code:
        queryset = queryset.filter(warehouse__code__iexact=warehouse_code)
    if item_slug:
        queryset = queryset.filter(item__slug=item_slug)
    if order_reference:
        queryset = queryset.filter(order__reference=order_reference)

    total_count = queryset.count()
    reservations = list(queryset.order_by("expires_at", "-created_at")[offset : offset + limit])

    return _json(
        {
            "meta": {
                "count": total_count,
                "limit": limit,
                "offset": offset,
                "returned": len(reservations),
            },
            "results": [
                serialize_inventory_reservation(reservation)
                for reservation in reservations
            ],
        }
    )
