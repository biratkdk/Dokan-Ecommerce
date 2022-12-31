from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Prefetch
from django.utils import timezone

from .models import (
    Coupon,
    InventoryReservation,
    Item,
    Order,
    OrderItem,
    OrderStatusEvent,
    ProductReview,
    ReturnRequest,
    StockLevel,
    StockMovement,
    Warehouse,
    WishlistItem,
)


FULFILLMENT_STATUSES = [
    Order.Status.PLACED,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
]
RESERVATION_HOLD_MINUTES = 30
DEFAULT_WAREHOUSE_CODE = "CENTRAL"


def get_active_order(user):
    if not user.is_authenticated:
        return None
    return (
        Order.objects.filter(user=user, status=Order.Status.CART)
        .prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related("item")),
            Prefetch(
                "inventory_reservations",
                queryset=InventoryReservation.objects.select_related("warehouse", "item"),
            ),
            "status_events",
        )
        .first()
    )


def _merge_payment_payload(order: Order, payload: dict | None) -> dict:
    merged = deepcopy(order.payment_payload or {})
    if payload:
        merged.update(payload)
    return merged


def _load_locked_order(order: Order) -> tuple[Order, list[OrderItem]]:
    locked_order = (
        Order.objects.select_for_update()
        .select_related("coupon", "user")
        .get(pk=order.pk)
    )
    order_lines = list(
        locked_order.items.select_for_update().select_related("item")
    )
    return locked_order, order_lines


def _ensure_checkout_allowed(user) -> None:
    if Order.objects.filter(user=user, status=Order.Status.PAYMENT_PENDING).exists():
        raise ValidationError(
            "Complete or cancel your pending Stripe payment before editing the cart."
        )


def _ensure_order_has_items(order_lines: list[OrderItem]) -> None:
    if not order_lines:
        raise ValidationError("Your cart is empty.")


def _default_warehouse() -> Warehouse:
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


def _ensure_stock_levels_exist(item: Item) -> None:
    if item.stock_levels.exists():
        return
    StockLevel.objects.create(
        warehouse=_default_warehouse(),
        item=item,
        on_hand=item.stock,
        reserved=0,
        safety_stock=item.reorder_level,
    )


def _sync_item_available_stock(item_ids: set[int] | list[int]) -> None:
    normalized_ids = {int(item_id) for item_id in item_ids if item_id}
    if not normalized_ids:
        return

    availability: dict[int, int] = {item_id: 0 for item_id in normalized_ids}
    stock_levels = (
        StockLevel.objects.filter(item_id__in=normalized_ids, warehouse__is_active=True)
        .values("item_id", "on_hand", "reserved")
    )
    seen_item_ids = set()
    for row in stock_levels:
        seen_item_ids.add(row["item_id"])
        availability[row["item_id"]] += max(row["on_hand"] - row["reserved"], 0)

    for item_id in seen_item_ids:
        Item.objects.filter(pk=item_id).update(stock=availability[item_id])
    for item_id in normalized_ids - seen_item_ids:
        Item.objects.filter(pk=item_id).update(stock=0)


def sync_item_available_stock(item_ids: set[int] | list[int]) -> None:
    _sync_item_available_stock(item_ids)


def _get_or_create_locked_stock_level(
    *,
    item: Item,
    warehouse: Warehouse,
    seed_on_hand: int = 0,
) -> StockLevel:
    stock_level, created = StockLevel.objects.get_or_create(
        item=item,
        warehouse=warehouse,
        defaults={
            "on_hand": max(seed_on_hand, 0),
            "reserved": 0,
            "safety_stock": item.reorder_level,
        },
    )
    if created:
        _sync_item_available_stock({item.pk})
    return StockLevel.objects.select_for_update().get(pk=stock_level.pk)


def _record_stock_movement(
    *,
    stock_level: StockLevel,
    movement_type: str,
    quantity: int,
    on_hand_delta: int = 0,
    reserved_delta: int = 0,
    actor=None,
    order: Order | None = None,
    reservation: InventoryReservation | None = None,
    related_warehouse: Warehouse | None = None,
    reference: str = "",
    note: str = "",
    metadata: dict | None = None,
) -> StockMovement:
    return StockMovement.objects.create(
        item=stock_level.item,
        warehouse=stock_level.warehouse,
        related_warehouse=related_warehouse,
        order=order,
        reservation=reservation,
        actor=actor,
        movement_type=movement_type,
        quantity=abs(int(quantity)),
        on_hand_delta=on_hand_delta,
        reserved_delta=reserved_delta,
        reference=reference[:80],
        note=note[:255],
        metadata=metadata or {},
    )


def _apply_stock_level_change(
    stock_level: StockLevel,
    *,
    movement_type: str,
    quantity: int | None = None,
    on_hand_delta: int = 0,
    reserved_delta: int = 0,
    actor=None,
    order: Order | None = None,
    reservation: InventoryReservation | None = None,
    related_warehouse: Warehouse | None = None,
    reference: str = "",
    note: str = "",
    metadata: dict | None = None,
) -> StockLevel:
    new_on_hand = stock_level.on_hand + on_hand_delta
    new_reserved = stock_level.reserved + reserved_delta
    if new_on_hand < 0:
        raise ValidationError(
            f"{stock_level.item.title} cannot go below zero stock in {stock_level.warehouse.code}."
        )
    if new_reserved < 0:
        raise ValidationError(
            f"{stock_level.item.title} cannot go below zero reserved units in {stock_level.warehouse.code}."
        )
    if new_reserved > new_on_hand:
        raise ValidationError(
            f"{stock_level.item.title} cannot reserve more units than on-hand stock in {stock_level.warehouse.code}."
        )

    stock_level.on_hand = new_on_hand
    stock_level.reserved = new_reserved
    stock_level.safety_stock = stock_level.item.reorder_level
    stock_level.save(update_fields=["on_hand", "reserved", "safety_stock", "updated_at"])

    effective_quantity = quantity
    if effective_quantity is None:
        effective_quantity = abs(on_hand_delta or reserved_delta)
    _record_stock_movement(
        stock_level=stock_level,
        movement_type=movement_type,
        quantity=effective_quantity,
        on_hand_delta=on_hand_delta,
        reserved_delta=reserved_delta,
        actor=actor,
        order=order,
        reservation=reservation,
        related_warehouse=related_warehouse,
        reference=reference,
        note=note,
        metadata=metadata,
    )
    return stock_level


def _available_quantity_for_item(item: Item) -> int:
    _ensure_stock_levels_exist(item)
    return sum(
        stock_level.available_quantity
        for stock_level in item.stock_levels.select_related("warehouse").filter(
            warehouse__is_active=True
        )
    )


def _ensure_stock_available(order_lines: list[OrderItem]) -> None:
    for order_item in order_lines:
        available_quantity = _available_quantity_for_item(order_item.item)
        if order_item.quantity > available_quantity:
            raise ValidationError(
                f"{order_item.item.title} has only {available_quantity} reservable units left."
            )


def _release_reservations(
    reservations,
    *,
    status: str,
    reason: str,
    released_at=None,
) -> None:
    released_at = released_at or timezone.now()
    touched_item_ids: set[int] = set()

    for reservation in reservations.select_related("warehouse", "item"):
        if reservation.status != InventoryReservation.Status.ACTIVE:
            continue
        stock_level = StockLevel.objects.select_for_update().get(
            warehouse_id=reservation.warehouse_id,
            item_id=reservation.item_id,
        )
        _apply_stock_level_change(
            stock_level,
            movement_type=StockMovement.MovementType.RESERVATION_RELEASE,
            quantity=reservation.quantity,
            reserved_delta=-reservation.quantity,
            order=reservation.order,
            reservation=reservation,
            reference=reservation.order.reference,
            note=reason,
            metadata={"release_status": status},
        )
        reservation.status = status
        reservation.released_at = released_at
        reservation.release_reason = reason[:255]
        reservation.save(
            update_fields=[
                "status",
                "released_at",
                "release_reason",
                "updated_at",
            ]
        )
        touched_item_ids.add(reservation.item_id)

    _sync_item_available_stock(touched_item_ids)


def _allocate_inventory(
    order: Order,
    order_lines: list[OrderItem],
    *,
    expires_at=None,
) -> None:
    touched_item_ids: set[int] = set()
    for order_item in order_lines:
        if order_item.ordered:
            continue

        _ensure_stock_levels_exist(order_item.item)
        existing_reservations = InventoryReservation.objects.select_for_update().filter(
            order=order,
            order_item=order_item,
            status=InventoryReservation.Status.ACTIVE,
        )
        if existing_reservations.exists():
            existing_quantity = sum(
                reservation.quantity for reservation in existing_reservations
            )
            if existing_quantity == order_item.quantity:
                touched_item_ids.add(order_item.item_id)
                continue
            _release_reservations(
                existing_reservations,
                status=InventoryReservation.Status.RELEASED,
                reason="Reservation refreshed before reallocation.",
            )

        remaining_quantity = order_item.quantity
        stock_levels = list(
            StockLevel.objects.select_for_update()
            .select_related("warehouse")
            .filter(item=order_item.item, warehouse__is_active=True)
            .order_by("warehouse__priority", "warehouse__name", "pk")
        )
        if not stock_levels:
            raise ValidationError(
                f"No active warehouse stock levels exist for {order_item.item.title}."
            )

        for stock_level in stock_levels:
            available_quantity = stock_level.available_quantity
            if available_quantity <= 0:
                continue

            allocated_quantity = min(remaining_quantity, available_quantity)
            if allocated_quantity <= 0:
                continue

            reservation = InventoryReservation.objects.create(
                order=order,
                order_item=order_item,
                item=order_item.item,
                warehouse=stock_level.warehouse,
                quantity=allocated_quantity,
                status=InventoryReservation.Status.ACTIVE,
                expires_at=expires_at,
            )
            _apply_stock_level_change(
                stock_level,
                movement_type=StockMovement.MovementType.RESERVATION_HOLD,
                quantity=allocated_quantity,
                reserved_delta=allocated_quantity,
                order=order,
                reservation=reservation,
                reference=order.reference,
                note=f"Reserved for order {order.reference}.",
                metadata={
                    "order_item_id": order_item.pk,
                    "expires_at": expires_at.isoformat() if expires_at else "",
                },
            )
            remaining_quantity -= allocated_quantity
            touched_item_ids.add(order_item.item_id)
            if remaining_quantity == 0:
                break

        if remaining_quantity > 0:
            raise ValidationError(
                f"{order_item.item.title} could not be fully allocated across active warehouses."
            )

    _sync_item_available_stock(touched_item_ids)


def _fulfill_inventory_reservations(order: Order, order_lines: list[OrderItem]) -> None:
    active_reservations = list(
        InventoryReservation.objects.select_for_update()
        .filter(order=order, status=InventoryReservation.Status.ACTIVE)
        .select_related("warehouse", "item", "order_item")
        .order_by("pk")
    )

    if not active_reservations:
        _allocate_inventory(order, order_lines, expires_at=None)
        active_reservations = list(
            InventoryReservation.objects.select_for_update()
            .filter(order=order, status=InventoryReservation.Status.ACTIVE)
            .select_related("warehouse", "item", "order_item")
            .order_by("pk")
        )

    reservation_totals: dict[int, int] = defaultdict(int)
    for reservation in active_reservations:
        reservation_totals[reservation.order_item_id] += reservation.quantity

    for order_item in order_lines:
        if order_item.ordered:
            continue
        if reservation_totals.get(order_item.pk, 0) < order_item.quantity:
            raise ValidationError(
                f"Inventory reservation coverage is incomplete for {order_item.item.title}."
            )

    touched_item_ids: set[int] = set()
    for reservation in active_reservations:
        stock_level = StockLevel.objects.select_for_update().get(
            warehouse_id=reservation.warehouse_id,
            item_id=reservation.item_id,
        )
        _apply_stock_level_change(
            stock_level,
            movement_type=StockMovement.MovementType.FULFILLMENT,
            quantity=reservation.quantity,
            on_hand_delta=-reservation.quantity,
            reserved_delta=-reservation.quantity,
            order=reservation.order,
            reservation=reservation,
            reference=reservation.order.reference,
            note=f"Committed inventory for order {reservation.order.reference}.",
        )
        reservation.status = InventoryReservation.Status.FULFILLED
        reservation.expires_at = None
        reservation.released_at = None
        reservation.release_reason = ""
        reservation.save(
            update_fields=[
                "status",
                "expires_at",
                "released_at",
                "release_reason",
                "updated_at",
            ]
        )
        touched_item_ids.add(reservation.item_id)

    for order_item in order_lines:
        if order_item.ordered:
            continue
        order_item.ordered = True
        order_item.save(update_fields=["ordered", "updated_at"])

    _sync_item_available_stock(touched_item_ids)


@transaction.atomic
def adjust_stock_level(
    *,
    actor,
    item: Item,
    warehouse: Warehouse,
    quantity_delta: int,
    reason: str,
    reference: str = "",
) -> StockLevel:
    if quantity_delta == 0:
        raise ValidationError("Adjustment quantity must not be zero.")
    if not warehouse.is_active:
        raise ValidationError("Adjustments can only target active warehouses.")

    existing_levels = item.stock_levels.exists()
    stock_level = _get_or_create_locked_stock_level(
        item=item,
        warehouse=warehouse,
        seed_on_hand=item.stock if not existing_levels and warehouse.code == DEFAULT_WAREHOUSE_CODE else 0,
    )
    movement_type = (
        StockMovement.MovementType.ADJUSTMENT_IN
        if quantity_delta > 0
        else StockMovement.MovementType.ADJUSTMENT_OUT
    )
    _apply_stock_level_change(
        stock_level,
        movement_type=movement_type,
        quantity=abs(quantity_delta),
        on_hand_delta=quantity_delta,
        actor=actor,
        reference=reference,
        note=reason,
        metadata={"source": "manual_adjustment"},
    )
    _sync_item_available_stock({item.pk})
    return StockLevel.objects.select_related("warehouse", "item").get(pk=stock_level.pk)


@transaction.atomic
def transfer_stock(
    *,
    actor,
    item: Item,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
    quantity: int,
    reason: str,
    reference: str = "",
) -> tuple[StockLevel, StockLevel]:
    if quantity < 1:
        raise ValidationError("Transfer quantity must be at least 1.")
    if source_warehouse.pk == destination_warehouse.pk:
        raise ValidationError("Choose two different warehouses for a transfer.")
    if not source_warehouse.is_active or not destination_warehouse.is_active:
        raise ValidationError("Transfers can only use active warehouses.")

    source_level = _get_or_create_locked_stock_level(
        item=item,
        warehouse=source_warehouse,
        seed_on_hand=item.stock if not item.stock_levels.exists() and source_warehouse.code == DEFAULT_WAREHOUSE_CODE else 0,
    )
    destination_level = _get_or_create_locked_stock_level(
        item=item,
        warehouse=destination_warehouse,
        seed_on_hand=0,
    )

    _apply_stock_level_change(
        source_level,
        movement_type=StockMovement.MovementType.TRANSFER_OUT,
        quantity=quantity,
        on_hand_delta=-quantity,
        actor=actor,
        related_warehouse=destination_warehouse,
        reference=reference,
        note=reason,
        metadata={"source": "warehouse_transfer"},
    )
    _apply_stock_level_change(
        destination_level,
        movement_type=StockMovement.MovementType.TRANSFER_IN,
        quantity=quantity,
        on_hand_delta=quantity,
        actor=actor,
        related_warehouse=source_warehouse,
        reference=reference,
        note=reason,
        metadata={"source": "warehouse_transfer"},
    )
    _sync_item_available_stock({item.pk})
    return (
        StockLevel.objects.select_related("warehouse", "item").get(pk=source_level.pk),
        StockLevel.objects.select_related("warehouse", "item").get(pk=destination_level.pk),
    )


def _validate_coupon(order: Order) -> None:
    if order.coupon and not order.coupon.is_available(order.subtotal):
        raise ValidationError("The selected coupon is no longer valid.")


def _consume_coupon(order: Order) -> None:
    if order.coupon and not order.coupon_usage_recorded:
        Coupon.objects.filter(pk=order.coupon.pk).update(times_used=F("times_used") + 1)
        order.coupon_usage_recorded = True


def _apply_checkout_fields(
    order: Order,
    *,
    shipping_address,
    billing_address,
    payment_method: str,
    customer_note: str,
) -> None:
    order.shipping_address = shipping_address
    order.billing_address = billing_address
    order.payment_method = payment_method
    order.customer_note = customer_note
    order.estimated_delivery_days = min(8, max(3, 3 + order.total_items // 2))


@transaction.atomic
def add_item_to_cart(user, item: Item, quantity: int = 1) -> OrderItem:
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")

    _ensure_checkout_allowed(user)
    _ensure_stock_levels_exist(item)
    _sync_item_available_stock({item.pk})
    item.refresh_from_db(fields=["stock"])

    order, _ = Order.objects.get_or_create(user=user, status=Order.Status.CART)
    order_item, created = OrderItem.objects.select_for_update().get_or_create(
        user=user,
        item=item,
        ordered=False,
        defaults={"quantity": quantity},
    )

    if created:
        requested_quantity = quantity
    else:
        requested_quantity = order_item.quantity + quantity
        order_item.quantity = requested_quantity

    if requested_quantity > item.stock:
        raise ValidationError(f"Only {item.stock} units of {item.title} are available.")

    order_item.save()
    order.items.add(order_item)
    return order_item


@transaction.atomic
def decrease_item_quantity(user, item: Item):
    order_item = OrderItem.objects.filter(
        user=user,
        item=item,
        ordered=False,
    ).first()
    if not order_item:
        return None
    if order_item.quantity <= 1:
        remove_item_from_cart(user, item)
        return None
    order_item.quantity -= 1
    order_item.save()
    return order_item


@transaction.atomic
def remove_item_from_cart(user, item: Item) -> bool:
    order = get_active_order(user)
    order_item = OrderItem.objects.filter(
        user=user,
        item=item,
        ordered=False,
    ).first()
    if not order or not order_item:
        return False
    order.items.remove(order_item)
    active_reservations = InventoryReservation.objects.select_for_update().filter(
        order=order,
        order_item=order_item,
        status=InventoryReservation.Status.ACTIVE,
    )
    if active_reservations.exists():
        _release_reservations(
            active_reservations,
            status=InventoryReservation.Status.RELEASED,
            reason="Cart line removed before checkout completion.",
        )
    order_item.delete()
    if not order.items.exists():
        order.delete()
    return True


def register_item_view(item: Item) -> None:
    Item.objects.filter(pk=item.pk).update(view_count=F("view_count") + 1)
    item.view_count += 1


@transaction.atomic
def apply_coupon_to_order(order: Order, code: str) -> Coupon:
    coupon = Coupon.objects.filter(code__iexact=code.strip()).first()
    if not coupon:
        raise ValidationError("Coupon code was not found.")
    if not coupon.is_available(order.subtotal):
        raise ValidationError("Coupon is not available for this order.")
    order.coupon = coupon
    order.coupon_usage_recorded = False
    order.save(update_fields=["coupon", "coupon_usage_recorded", "updated_at"])
    return coupon


def record_status_event(
    order: Order,
    *,
    status: str,
    note: str = "",
    actor: str = "system",
) -> OrderStatusEvent:
    return OrderStatusEvent.objects.create(
        order=order,
        status=status,
        note=note,
        actor=actor,
    )


def has_verified_purchase(user, item: Item) -> bool:
    return Order.objects.filter(
        user=user,
        status__in=FULFILLMENT_STATUSES,
        items__item=item,
    ).exists()


@transaction.atomic
def submit_review(user, item: Item, *, rating: int, title: str, comment: str) -> ProductReview:
    review, _ = ProductReview.objects.update_or_create(
        user=user,
        item=item,
        defaults={
            "rating": rating,
            "title": title,
            "comment": comment,
            "verified_purchase": has_verified_purchase(user, item),
            "approved": True,
        },
    )
    return review


@transaction.atomic
def toggle_wishlist(user, item: Item) -> bool:
    wishlist_item = WishlistItem.objects.filter(user=user, item=item).first()
    if wishlist_item:
        wishlist_item.delete()
        return False
    WishlistItem.objects.create(user=user, item=item)
    return True


@transaction.atomic
def place_order(
    order: Order,
    *,
    shipping_address,
    billing_address,
    payment_method: str,
    customer_note: str = "",
) -> Order:
    locked_order, order_lines = _load_locked_order(order)
    if locked_order.status != Order.Status.CART:
        raise ValidationError("This order has already been submitted.")

    _ensure_order_has_items(order_lines)
    _ensure_stock_available(order_lines)
    _validate_coupon(locked_order)
    _apply_checkout_fields(
        locked_order,
        shipping_address=shipping_address,
        billing_address=billing_address,
        payment_method=payment_method,
        customer_note=customer_note,
    )

    _allocate_inventory(locked_order, order_lines, expires_at=None)
    _fulfill_inventory_reservations(locked_order, order_lines)
    _consume_coupon(locked_order)

    locked_order.status = Order.Status.PLACED
    locked_order.payment_provider = "manual"
    locked_order.payment_status = Order.PaymentStatus.PENDING
    locked_order.payment_reference = ""
    locked_order.payment_session_id = ""
    locked_order.payment_failure_reason = ""
    locked_order.payment_payload = {}
    locked_order.placed_at = timezone.now()
    locked_order.save()

    record_status_event(
        locked_order,
        status=Order.Status.PLACED,
        note="Order placed, reserved, and queued for warehouse processing.",
        actor=locked_order.user.username,
    )
    return locked_order


@transaction.atomic
def prepare_order_for_online_payment(
    order: Order,
    *,
    shipping_address,
    billing_address,
    customer_note: str = "",
) -> Order:
    locked_order, order_lines = _load_locked_order(order)
    if locked_order.status != Order.Status.CART:
        raise ValidationError("This order has already been submitted.")

    _ensure_order_has_items(order_lines)
    _ensure_stock_available(order_lines)
    _validate_coupon(locked_order)
    _apply_checkout_fields(
        locked_order,
        shipping_address=shipping_address,
        billing_address=billing_address,
        payment_method=Order.PaymentMethod.STRIPE,
        customer_note=customer_note,
    )

    expires_at = timezone.now() + timedelta(minutes=RESERVATION_HOLD_MINUTES)
    _allocate_inventory(locked_order, order_lines, expires_at=expires_at)

    locked_order.status = Order.Status.PAYMENT_PENDING
    locked_order.payment_provider = "stripe"
    locked_order.payment_status = Order.PaymentStatus.PENDING
    locked_order.payment_reference = ""
    locked_order.payment_session_id = ""
    locked_order.payment_failure_reason = ""
    locked_order.payment_payload = {"reservation_expires_at": expires_at.isoformat()}
    locked_order.placed_at = timezone.now()
    locked_order.save()

    record_status_event(
        locked_order,
        status=Order.Status.PAYMENT_PENDING,
        note="Inventory reserved across warehouses while Stripe payment confirmation is pending.",
        actor=locked_order.user.username,
    )
    return locked_order


@transaction.atomic
def attach_payment_session(
    order: Order,
    *,
    provider: str,
    session_id: str,
    payload: dict | None = None,
) -> Order:
    locked_order = Order.objects.select_for_update().get(pk=order.pk)
    locked_order.payment_provider = provider
    locked_order.payment_session_id = session_id
    locked_order.payment_payload = _merge_payment_payload(locked_order, payload)
    locked_order.save(
        update_fields=[
            "payment_provider",
            "payment_session_id",
            "payment_payload",
            "updated_at",
        ]
    )
    return locked_order


@transaction.atomic
def finalize_paid_order(
    order: Order,
    *,
    payment_reference: str = "",
    payment_session_id: str = "",
    payment_payload: dict | None = None,
    actor: str = "stripe",
) -> Order:
    locked_order, order_lines = _load_locked_order(order)
    if locked_order.payment_status == Order.PaymentStatus.PAID:
        locked_order.payment_reference = payment_reference or locked_order.payment_reference
        locked_order.payment_session_id = payment_session_id or locked_order.payment_session_id
        locked_order.payment_payload = _merge_payment_payload(locked_order, payment_payload)
        if not locked_order.paid_at:
            locked_order.paid_at = timezone.now()
        locked_order.save()
        return locked_order

    if locked_order.status in [Order.Status.CART, Order.Status.CANCELLED]:
        raise ValidationError("This order is not awaiting online payment confirmation.")

    _ensure_order_has_items(order_lines)
    _fulfill_inventory_reservations(locked_order, order_lines)
    _consume_coupon(locked_order)

    locked_order.status = Order.Status.PLACED
    locked_order.payment_method = Order.PaymentMethod.STRIPE
    locked_order.payment_provider = "stripe"
    locked_order.payment_status = Order.PaymentStatus.PAID
    locked_order.payment_reference = payment_reference or locked_order.payment_reference
    locked_order.payment_session_id = payment_session_id or locked_order.payment_session_id
    locked_order.payment_failure_reason = ""
    locked_order.payment_payload = _merge_payment_payload(locked_order, payment_payload)
    locked_order.paid_at = locked_order.paid_at or timezone.now()
    locked_order.placed_at = locked_order.placed_at or timezone.now()
    locked_order.save()

    if not locked_order.status_events.filter(status=Order.Status.PLACED).exists():
        record_status_event(
            locked_order,
            status=Order.Status.PLACED,
            note="Stripe payment confirmed and warehouse reservations fulfilled.",
            actor=actor,
        )
    return locked_order


@transaction.atomic
def reopen_order_for_checkout(
    order: Order,
    *,
    reason: str,
    actor: str = "system",
    payment_status: str = Order.PaymentStatus.UNPAID,
    payment_payload: dict | None = None,
    reservation_status: str = InventoryReservation.Status.RELEASED,
) -> Order:
    locked_order = Order.objects.select_for_update().get(pk=order.pk)
    if locked_order.status != Order.Status.PAYMENT_PENDING:
        return locked_order

    active_reservations = InventoryReservation.objects.select_for_update().filter(
        order=locked_order,
        status=InventoryReservation.Status.ACTIVE,
    )
    _release_reservations(
        active_reservations,
        status=reservation_status,
        reason=reason,
    )

    locked_order.status = Order.Status.CART
    locked_order.payment_status = payment_status
    locked_order.payment_provider = "manual"
    locked_order.payment_reference = ""
    locked_order.payment_session_id = ""
    locked_order.payment_failure_reason = reason
    locked_order.payment_payload = _merge_payment_payload(locked_order, payment_payload)
    locked_order.paid_at = None
    locked_order.placed_at = None
    locked_order.save()

    record_status_event(
        locked_order,
        status=Order.Status.CART,
        note=reason,
        actor=actor,
    )
    return locked_order


@transaction.atomic
def release_expired_reservations(*, at_time=None) -> int:
    at_time = at_time or timezone.now()
    stale_orders = list(
        Order.objects.filter(
            status=Order.Status.PAYMENT_PENDING,
            payment_status=Order.PaymentStatus.PENDING,
            inventory_reservations__status=InventoryReservation.Status.ACTIVE,
            inventory_reservations__expires_at__lt=at_time,
        )
        .distinct()
        .order_by("placed_at", "created_at")
    )

    released_count = 0
    for order in stale_orders:
        previous_status = order.status
        reopened_order = reopen_order_for_checkout(
            order,
            reason="Inventory reservation hold expired and the cart was reopened automatically.",
            actor="reservation-expiry",
            payment_status=Order.PaymentStatus.FAILED,
            payment_payload={"reservation_expired_at": at_time.isoformat()},
            reservation_status=InventoryReservation.Status.EXPIRED,
        )
        if previous_status == Order.Status.PAYMENT_PENDING and reopened_order.status == Order.Status.CART:
            released_count += 1
    return released_count


@transaction.atomic
def submit_return_request(
    user,
    order: Order,
    order_item: OrderItem,
    *,
    quantity: int,
    reason: str,
    details: str = "",
) -> ReturnRequest:
    if order.user_id != user.pk or order_item.user_id != user.pk:
        raise ValidationError("You can only create returns for your own orders.")
    if order.status != Order.Status.DELIVERED:
        raise ValidationError("Returns can only be requested for delivered orders.")
    if not order.items.filter(pk=order_item.pk).exists():
        raise ValidationError("This item does not belong to the selected order.")
    if quantity < 1 or quantity > order_item.quantity:
        raise ValidationError("Choose a valid return quantity.")
    if ReturnRequest.objects.filter(
        order=order,
        order_item=order_item,
        status__in=[
            ReturnRequest.Status.REQUESTED,
            ReturnRequest.Status.APPROVED,
            ReturnRequest.Status.RECEIVED,
        ],
    ).exists():
        raise ValidationError("A return request for this item is already open.")

    return_request = ReturnRequest.objects.create(
        user=user,
        order=order,
        order_item=order_item,
        quantity=quantity,
        reason=reason,
        details=details,
        status=ReturnRequest.Status.REQUESTED,
    )
    record_status_event(
        order,
        status=order.status,
        note=f"Return requested for {order_item.item.title}.",
        actor=user.username,
    )
    return return_request
