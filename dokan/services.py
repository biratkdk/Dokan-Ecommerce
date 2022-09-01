from __future__ import annotations

from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Prefetch
from django.utils import timezone

from .models import (
    Coupon,
    Item,
    Order,
    OrderItem,
    OrderStatusEvent,
    ProductReview,
    ReturnRequest,
    WishlistItem,
)


FULFILLMENT_STATUSES = [
    Order.Status.PLACED,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
]


def get_active_order(user):
    if not user.is_authenticated:
        return None
    return (
        Order.objects.filter(user=user, status=Order.Status.CART)
        .prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related("item")),
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


def _ensure_stock_available(order_lines: list[OrderItem]) -> None:
    for order_item in order_lines:
        if order_item.quantity > order_item.item.stock:
            raise ValidationError(
                f"{order_item.item.title} has only {order_item.item.stock} units left."
            )


def _commit_inventory(order_lines: list[OrderItem]) -> None:
    for order_item in order_lines:
        if order_item.ordered:
            continue
        item = order_item.item
        item.stock -= order_item.quantity
        item.save(update_fields=["stock"])
        order_item.ordered = True
        order_item.save(update_fields=["ordered"])


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

    _commit_inventory(order_lines)
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
        note="Order placed and queued for processing.",
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

    locked_order.status = Order.Status.PAYMENT_PENDING
    locked_order.payment_provider = "stripe"
    locked_order.payment_status = Order.PaymentStatus.PENDING
    locked_order.payment_reference = ""
    locked_order.payment_session_id = ""
    locked_order.payment_failure_reason = ""
    locked_order.payment_payload = {}
    locked_order.placed_at = timezone.now()
    locked_order.save()

    record_status_event(
        locked_order,
        status=Order.Status.PAYMENT_PENDING,
        note="Awaiting Stripe payment confirmation.",
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
    locked_order.save(update_fields=["payment_provider", "payment_session_id", "payment_payload", "updated_at"])
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
    _ensure_stock_available([line for line in order_lines if not line.ordered])
    _commit_inventory(order_lines)
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
            note="Stripe payment confirmed and order released for processing.",
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
) -> Order:
    locked_order = Order.objects.select_for_update().get(pk=order.pk)
    if locked_order.status != Order.Status.PAYMENT_PENDING:
        return locked_order

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
