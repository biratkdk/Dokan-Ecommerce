from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, update_session_auth_hash
from django.db.models import F, Prefetch, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .accounts import ensure_customer_profile, mark_email_unverified
from .api_serializers import (
    serialize_address,
    serialize_customer_profile,
    serialize_inventory_reservation,
    serialize_item,
    serialize_login_activity,
    serialize_search_result,
    serialize_stock_level,
    serialize_stock_movement,
    serialize_warehouse,
)
from .api_v2_serializers import (
    ApiTokenRequestSerializer,
    AccountProfileUpdatePayloadSerializer,
    AddressPayloadSerializer,
    InventoryAdjustmentPayloadSerializer,
    InventoryTransferPayloadSerializer,
    PasswordChangePayloadSerializer,
)
from .forms import AccountIdentityForm, AccountPasswordChangeForm, CustomerProfileSettingsForm
from .intelligence import rank_catalog_search
from .models import Address, InventoryReservation, Item, Order, StockLevel, StockMovement, Warehouse
from .notifications import send_email_verification_email
from .permissions import (
    can_manage_inventory_network,
    can_view_inventory_dashboard,
    user_capability_map,
    user_permission_codes,
    user_role_labels,
)
from .services import adjust_stock_level, transfer_stock


def _limit_offset(request, *, default_limit: int = 20, max_limit: int = 50) -> tuple[int, int]:
    try:
        limit = int(request.query_params.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(request.query_params.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(limit, max_limit)), max(0, offset)


def _parse_decimal_param(request, key: str) -> Decimal | None:
    raw = str(request.query_params.get(key, "")).strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValidationError({key: "Enter a valid decimal value."})


class InventoryAccessMixin:
    def enforce_inventory_access(self, request) -> None:
        if not can_view_inventory_dashboard(request.user):
            raise PermissionDenied("You do not have access to inventory data.")


class InventoryManagementMixin(InventoryAccessMixin):
    def enforce_inventory_management(self, request) -> None:
        if not can_manage_inventory_network(request.user):
            raise PermissionDenied("You do not have permission to change inventory data.")


class ApiV2RootView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(
            {
                "application": "Redstore Advanced Ecommerce",
                "version": "v2",
                "style": "Django REST Framework API",
                "endpoints": {
                    "catalog": "/api/v2/catalog/",
                    "account_profile": "/api/v2/account/profile/",
                    "account_security": "/api/v2/account/security/",
                    "account_access": "/api/v2/account/access/",
                    "account_password": "/api/v2/account/password/",
                    "auth_token": "/api/v2/auth/token/",
                    "account_addresses": "/api/v2/account/addresses/",
                    "inventory_overview": "/api/v2/inventory/overview/",
                    "inventory_warehouses": "/api/v2/inventory/warehouses/",
                    "inventory_active_reservations": "/api/v2/inventory/reservations/active/",
                    "inventory_movements": "/api/v2/inventory/movements/",
                    "inventory_adjustments": "/api/v2/inventory/adjustments/",
                    "inventory_transfers": "/api/v2/inventory/transfers/",
                    "order_reservations": "/api/v2/orders/<reference>/reservations/",
                },
            }
        )


class CatalogListV2View(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "catalog"

    def get(self, request):
        min_price = _parse_decimal_param(request, "min_price")
        max_price = _parse_decimal_param(request, "max_price")

        queryset = (
            Item.objects.active()
            .with_metrics()
            .prefetch_related("stock_levels__warehouse")
            .annotate(display_price=Coalesce("discount_price", "price"))
        )
        search_term = str(request.query_params.get("q", "")).strip()
        category_slug = str(request.query_params.get("category", "")).strip()
        brand_slug = str(request.query_params.get("brand", "")).strip()
        sort = str(request.query_params.get("sort", "latest")).strip()
        in_stock_only = str(request.query_params.get("in_stock", "")).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        include_inventory = str(
            request.query_params.get("include_inventory", "")
        ).strip().lower() in {"1", "true", "yes"}
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
            paged_results = ranked_results[offset : offset + limit]
            results = []
            for entry in paged_results:
                payload = serialize_item(entry.item, include_details=True)
                payload["search_score"] = entry.score
                payload["search_reasons"] = entry.reasons
                if include_inventory:
                    payload["stock_levels"] = [
                        serialize_stock_level(stock_level)
                        for stock_level in entry.item.stock_levels.all()
                    ]
                results.append(payload)
            return Response(
                {
                    "meta": {
                        "count": len(ranked_results),
                        "limit": limit,
                        "offset": offset,
                        "returned": len(results),
                        "sort": sort,
                    },
                    "results": results,
                    "search_matches": [
                        serialize_search_result(entry) for entry in paged_results
                    ],
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
                    serialize_stock_level(stock_level) for stock_level in item.stock_levels.all()
                ]
            results.append(payload)
        return Response(
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


class AccountProfileV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def get(self, request):
        profile = ensure_customer_profile(request.user)
        return Response(
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

    def patch(self, request):
        profile = ensure_customer_profile(request.user)
        payload_serializer = AccountProfileUpdatePayloadSerializer(
            data=request.data,
            partial=True,
        )
        payload_serializer.is_valid(raise_exception=True)
        payload = payload_serializer.validated_data

        current_email = request.user.email
        user_payload = {
            "username": payload.get("username", request.user.username),
            "email": payload.get("email", request.user.email),
            "first_name": payload.get("first_name", request.user.first_name),
            "last_name": payload.get("last_name", request.user.last_name),
        }
        profile_payload = {
            "phone_number": payload.get("phone_number", profile.phone_number),
            "company_name": payload.get("company_name", profile.company_name),
            "job_title": payload.get("job_title", profile.job_title),
            "preferred_contact_channel": payload.get(
                "preferred_contact_channel", profile.preferred_contact_channel
            ),
            "marketing_opt_in": payload.get("marketing_opt_in", profile.marketing_opt_in),
        }

        user_form = AccountIdentityForm(user_payload, instance=request.user)
        profile_form = CustomerProfileSettingsForm(profile_payload, instance=profile)
        if not (user_form.is_valid() and profile_form.is_valid()):
            raise ValidationError(
                {
                    "user": user_form.errors,
                    "profile": profile_form.errors,
                }
            )

        updated_user = user_form.save()
        profile_form.save()
        email_reverification_required = (
            current_email.strip().lower() != updated_user.email.strip().lower()
        )
        if email_reverification_required:
            mark_email_unverified(updated_user)
            send_email_verification_email(updated_user, request=request._request)

        return Response(
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


class AccountSecurityV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def get(self, request):
        profile = ensure_customer_profile(request.user)
        recent_logins = request.user.login_activities.all()[:10]
        return Response(
            {
                "profile": serialize_customer_profile(profile),
                "roles": user_role_labels(request.user),
                "capabilities": user_capability_map(request.user),
                "recent_logins": [
                    serialize_login_activity(activity) for activity in recent_logins
                ],
            }
        )


class AccountAccessV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def get(self, request):
        return Response(
            {
                "roles": user_role_labels(request.user),
                "permissions": user_permission_codes(request.user),
                "capabilities": user_capability_map(request.user),
            }
        )


class AccountPasswordV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def post(self, request):
        payload_serializer = PasswordChangePayloadSerializer(data=request.data)
        payload_serializer.is_valid(raise_exception=True)
        password_form = AccountPasswordChangeForm(
            request.user,
            payload_serializer.validated_data,
        )
        if not password_form.is_valid():
            raise ValidationError(password_form.errors)
        updated_user = password_form.save()
        update_session_auth_hash(request._request, updated_user)
        return Response({"message": "Password updated successfully."})


class AddressListCreateV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def get(self, request):
        addresses = request.user.addresses.all()
        return Response(
            {
                "count": addresses.count(),
                "results": [serialize_address(address) for address in addresses],
            }
        )

    def post(self, request):
        serializer = AddressPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("default"):
            request.user.addresses.filter(
                address_type=data["address_type"],
                default=True,
            ).update(default=False)
        address = Address.objects.create(user=request.user, **data)
        return Response({"address": serialize_address(address)}, status=status.HTTP_201_CREATED)


class AddressDetailV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def get_object(self, request, address_id: int) -> Address:
        return get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)

    def get(self, request, address_id: int):
        return Response({"address": serialize_address(self.get_object(request, address_id))})

    def patch(self, request, address_id: int):
        address = self.get_object(request, address_id)
        serializer = AddressPayloadSerializer(
            instance=address,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("default"):
            request.user.addresses.filter(
                address_type=data.get("address_type", address.address_type),
                default=True,
            ).exclude(pk=address.pk).update(default=False)
        for field, value in data.items():
            setattr(address, field, value)
        address.save()
        return Response({"address": serialize_address(address)})

    def delete(self, request, address_id: int):
        self.get_object(request, address_id).delete()
        return Response({"deleted": True})


class AddressDefaultV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def post(self, request, address_id: int):
        address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
        request.user.addresses.filter(
            address_type=address.address_type,
            default=True,
        ).exclude(pk=address.pk).update(default=False)
        if not address.default:
            address.default = True
            address.save(update_fields=["default", "updated_at"])
        return Response({"address": serialize_address(address), "default_updated": True})


class OrderReservationsV2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "account"

    def get(self, request, reference: str):
        order_queryset = Order.objects.prefetch_related(
            "inventory_reservations__warehouse",
            "inventory_reservations__item",
            "items__item",
        )
        if not can_view_inventory_dashboard(request.user):
            order_queryset = order_queryset.filter(user=request.user)
        order = get_object_or_404(order_queryset, reference=reference)
        reservations = order.inventory_reservations.select_related("warehouse", "item", "order_item")
        return Response(
            {
                "order": {
                    "reference": order.reference,
                    "status": order.get_status_display(),
                    "payment_status": order.get_payment_status_display(),
                },
                "reservations": [
                    serialize_inventory_reservation(reservation) for reservation in reservations
                ],
            }
        )


class InventoryOverviewV2View(InventoryAccessMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "inventory"

    def get(self, request):
        self.enforce_inventory_access(request)
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
        search_term = str(request.query_params.get("q", "")).strip()
        warehouse_code = str(request.query_params.get("warehouse", "")).strip()
        low_stock_only = str(
            request.query_params.get("low_stock_only", "")
        ).strip().lower() in {"1", "true", "yes"}
        limit, offset = _limit_offset(request)

        if search_term:
            queryset = queryset.filter(
                Q(title__icontains=search_term)
                | Q(sku__icontains=search_term)
                | Q(brand__name__icontains=search_term)
            )
        if warehouse_code:
            queryset = queryset.filter(
                stock_levels__warehouse__code__iexact=warehouse_code
            ).distinct()
        if low_stock_only:
            queryset = queryset.filter(stock__lte=F("reorder_level"))

        total_count = queryset.count()
        items = list(queryset[offset : offset + limit])
        warehouses = list(
            Warehouse.objects.filter(is_active=True)
            .prefetch_related("stock_levels")
            .order_by("priority", "name")
        )
        active_reservations = InventoryReservation.objects.filter(
            status=InventoryReservation.Status.ACTIVE
        ).count()
        return Response(
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


class InventoryWarehousesV2View(InventoryAccessMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "inventory"

    def get(self, request):
        self.enforce_inventory_access(request)
        include_stock = str(request.query_params.get("include_stock", "")).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        include_inactive = str(
            request.query_params.get("include_inactive", "")
        ).strip().lower() in {"1", "true", "yes"}
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
                payload["stock_levels"] = [
                    serialize_stock_level(stock_level) for stock_level in stock_levels
                ]
            results.append(payload)
        return Response(
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


class InventoryActiveReservationsV2View(InventoryAccessMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "inventory"

    def get(self, request):
        self.enforce_inventory_access(request)
        queryset = InventoryReservation.objects.filter(
            status=InventoryReservation.Status.ACTIVE
        ).select_related("order", "order_item", "item", "warehouse")
        warehouse_code = str(request.query_params.get("warehouse", "")).strip()
        item_slug = str(request.query_params.get("item", "")).strip()
        order_reference = str(request.query_params.get("reference", "")).strip()
        limit, offset = _limit_offset(request)

        if warehouse_code:
            queryset = queryset.filter(warehouse__code__iexact=warehouse_code)
        if item_slug:
            queryset = queryset.filter(item__slug=item_slug)
        if order_reference:
            queryset = queryset.filter(order__reference=order_reference)

        total_count = queryset.count()
        reservations = list(queryset.order_by("expires_at", "-created_at")[offset : offset + limit])
        return Response(
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


class ApiTokenV2View(APIView):
    throttle_scope = "auth"

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def post(self, request):
        serializer = ApiTokenRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request=request._request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if not user:
            raise ValidationError({"detail": "Invalid username or password."})
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user": {
                    "username": user.username,
                    "email": user.email,
                },
                "roles": user_role_labels(user),
                "capabilities": user_capability_map(user),
            }
        )

    def delete(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InventoryMovementsV2View(InventoryAccessMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "inventory"

    def get(self, request):
        self.enforce_inventory_access(request)
        queryset = StockMovement.objects.select_related(
            "item",
            "warehouse",
            "related_warehouse",
            "actor",
            "order",
            "reservation",
        )
        warehouse_code = str(request.query_params.get("warehouse", "")).strip()
        item_slug = str(request.query_params.get("item", "")).strip()
        movement_type = str(request.query_params.get("type", "")).strip()
        limit, offset = _limit_offset(request)

        if warehouse_code:
            queryset = queryset.filter(warehouse__code__iexact=warehouse_code)
        if item_slug:
            queryset = queryset.filter(item__slug=item_slug)
        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)

        total_count = queryset.count()
        movements = list(queryset.order_by("-created_at", "-pk")[offset : offset + limit])
        return Response(
            {
                "meta": {
                    "count": total_count,
                    "limit": limit,
                    "offset": offset,
                    "returned": len(movements),
                },
                "results": [serialize_stock_movement(movement) for movement in movements],
            }
        )


class InventoryAdjustmentV2View(InventoryManagementMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "inventory"

    def post(self, request):
        self.enforce_inventory_management(request)
        serializer = InventoryAdjustmentPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        quantity_delta = payload["quantity"]
        if payload["direction"] == "decrease":
            quantity_delta *= -1
        stock_level = adjust_stock_level(
            actor=request.user,
            item=payload["item"],
            warehouse=payload["warehouse"],
            quantity_delta=quantity_delta,
            reason=payload["reason"],
            reference=payload.get("reference", ""),
        )
        return Response(
            {
                "message": "Inventory adjustment recorded.",
                "stock_level": serialize_stock_level(stock_level),
            },
            status=status.HTTP_201_CREATED,
        )


class InventoryTransferV2View(InventoryManagementMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "inventory"

    def post(self, request):
        self.enforce_inventory_management(request)
        serializer = InventoryTransferPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        source_level, destination_level = transfer_stock(
            actor=request.user,
            item=payload["item"],
            source_warehouse=payload["source_warehouse"],
            destination_warehouse=payload["destination_warehouse"],
            quantity=payload["quantity"],
            reason=payload["reason"],
            reference=payload.get("reference", ""),
        )
        return Response(
            {
                "message": "Inventory transfer recorded.",
                "source": serialize_stock_level(source_level),
                "destination": serialize_stock_level(destination_level),
            },
            status=status.HTTP_201_CREATED,
        )
