from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.urls import reverse

from .models import Order

try:
    import stripe
except ImportError:  # pragma: no cover - handled via configuration guards
    stripe = None


STRIPE_PROVIDER = "stripe"


def is_stripe_enabled() -> bool:
    return bool(
        stripe
        and getattr(settings, "STRIPE_SECRET_KEY", "")
    )


def _require_stripe_sdk() -> None:
    if not stripe:
        raise ImproperlyConfigured(
            "Stripe is not installed. Add the stripe package before enabling online payments."
        )


def _require_stripe_secret_key() -> None:
    if not getattr(settings, "STRIPE_SECRET_KEY", ""):
        raise ImproperlyConfigured(
            "Set STRIPE_SECRET_KEY to create Stripe Checkout sessions."
        )


def _require_webhook_secret() -> None:
    if not getattr(settings, "STRIPE_WEBHOOK_SECRET", ""):
        raise ImproperlyConfigured(
            "Set STRIPE_WEBHOOK_SECRET to verify Stripe webhook signatures."
        )


def _configure_stripe() -> None:
    _require_stripe_sdk()
    _require_stripe_secret_key()
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _to_minor_units(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _build_discounted_product_lines(order: Order) -> list[dict]:
    order_lines = list(order.items.select_related("item"))
    discount_cents = _to_minor_units(order.coupon_discount)
    total_product_cents = sum(_to_minor_units(order_item.total_price) for order_item in order_lines)
    allocated_discount = 0
    checkout_lines = []

    for index, order_item in enumerate(order_lines):
        base_cents = _to_minor_units(order_item.total_price)
        if index == len(order_lines) - 1:
            discount_share = discount_cents - allocated_discount
        elif total_product_cents:
            discount_share = (discount_cents * base_cents) // total_product_cents
            allocated_discount += discount_share
        else:
            discount_share = 0

        effective_cents = max(base_cents - discount_share, 0)
        if effective_cents == 0:
            continue
        checkout_lines.append(
            {
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "product_data": {
                        "name": f"{order_item.item.title} x {order_item.quantity}",
                        "description": order_item.item.short_description,
                        "metadata": {
                            "item_slug": order_item.item.slug,
                            "sku": order_item.item.sku or "",
                        },
                    },
                    "unit_amount": effective_cents,
                },
                "quantity": 1,
            }
        )

    return checkout_lines


def _build_checkout_line_items(order: Order) -> list[dict]:
    if order.total <= Decimal("0.00"):
        raise ValidationError("Stripe Checkout requires a positive order total.")

    line_items = _build_discounted_product_lines(order)
    if order.shipping_total > Decimal("0.00"):
        line_items.append(
            {
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "product_data": {"name": "Standard shipping"},
                    "unit_amount": _to_minor_units(order.shipping_total),
                },
                "quantity": 1,
            }
        )
    if order.tax_total > Decimal("0.00"):
        line_items.append(
            {
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "product_data": {"name": "Tax"},
                    "unit_amount": _to_minor_units(order.tax_total),
                },
                "quantity": 1,
            }
        )
    return line_items


def _session_metadata(order: Order) -> dict[str, str]:
    return {
        "order_id": str(order.pk),
        "order_reference": order.reference,
        "user_id": str(order.user_id),
    }


def create_stripe_checkout_session(request, order: Order):
    _configure_stripe()

    success_url = request.build_absolute_uri(reverse("store:payment-success"))
    cancel_url = request.build_absolute_uri(
        reverse("store:payment-cancel", kwargs={"reference": order.reference})
    )

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=_build_checkout_line_items(order),
        success_url=f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=cancel_url,
        client_reference_id=order.reference,
        metadata=_session_metadata(order),
        customer_email=order.user.email or None,
        billing_address_collection="required",
    )
    return session


def retrieve_stripe_checkout_session(session_id: str):
    _configure_stripe()
    return stripe.checkout.Session.retrieve(session_id)


def construct_stripe_event(payload: bytes, signature: str):
    _configure_stripe()
    _require_webhook_secret()
    return stripe.Webhook.construct_event(
        payload,
        signature,
        settings.STRIPE_WEBHOOK_SECRET,
    )


def stripe_object_to_payload(value):
    if hasattr(value, "to_dict"):
        return value.to_dict(recursive=True, for_json=True)
    if isinstance(value, dict):
        return value
    return {}
