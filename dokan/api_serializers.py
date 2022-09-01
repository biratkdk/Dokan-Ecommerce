from __future__ import annotations

from .intelligence import (
    CustomerHealth,
    CustomerSegment,
    Recommendation,
    SearchResult,
    SupportSuggestion,
    calculate_demand_score,
    estimate_days_to_stockout,
)
from .models import (
    CustomerProfile,
    Item,
    LoginActivity,
    Order,
    OrderStatusEvent,
    ProductReview,
    ReturnRequest,
    SupportMessage,
    SupportThread,
)


def serialize_item(item: Item, *, include_details: bool = False) -> dict:
    payload = {
        "id": item.pk,
        "title": item.title,
        "slug": item.slug,
        "sku": item.sku,
        "brand": item.brand_name,
        "category": item.category_name,
        "legacy_category": item.get_category_display(),
        "label": item.get_label_display() if item.label else "",
        "price": float(item.price),
        "unit_price": float(item.unit_price),
        "discount_price": float(item.discount_price) if item.discount_price else None,
        "has_discount": item.has_discount,
        "short_description": item.short_description,
        "primary_image": item.primary_image,
        "stock": item.stock,
        "inventory_status": item.inventory_status,
        "average_rating": item.average_rating,
        "review_count": item.review_count,
        "wishlist_count": item.wishlist_count,
        "sold_units": item.sold_units,
        "view_count": item.view_count,
        "launch_year": item.launch_year,
        "demand_score": calculate_demand_score(item),
        "estimated_days_to_stockout": estimate_days_to_stockout(item),
    }
    if include_details:
        payload.update(
            {
                "description": item.description,
                "gallery_images": item.gallery_images,
                "attributes": item.attributes,
                "tags": item.tags,
                "reorder_level": item.reorder_level,
            }
        )
    return payload


def serialize_review(review: ProductReview) -> dict:
    return {
        "id": review.pk,
        "user": review.user.username,
        "rating": review.rating,
        "title": review.title,
        "comment": review.comment,
        "verified_purchase": review.verified_purchase,
        "created_at": review.created_at.isoformat(),
    }


def serialize_status_event(event: OrderStatusEvent) -> dict:
    return {
        "status": event.get_status_display(),
        "note": event.note,
        "actor": event.actor,
        "created_at": event.created_at.isoformat(),
    }


def serialize_order(order: Order) -> dict:
    return {
        "reference": order.reference,
        "status": order.get_status_display(),
        "payment_method": order.get_payment_method_display(),
        "payment_status": order.get_payment_status_display(),
        "payment_provider": order.payment_provider,
        "payment_reference": order.payment_reference,
        "is_paid": order.is_paid,
        "customer_note": order.customer_note,
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "estimated_delivery_days": order.estimated_delivery_days,
        "totals": {
            "subtotal": float(order.subtotal),
            "discount": float(order.coupon_discount),
            "shipping": float(order.shipping_total),
            "tax": float(order.tax_total),
            "total": float(order.total),
        },
        "items": [
            {
                "title": order_item.item.title,
                "slug": order_item.item.slug,
                "quantity": order_item.quantity,
                "unit_price": float(order_item.item.unit_price),
                "line_total": float(order_item.total_price),
            }
            for order_item in order.items.select_related("item")
        ],
        "timeline": [
            serialize_status_event(event)
            for event in order.status_events.all()
        ],
        "return_requests": [
            serialize_return_request(return_request)
            for return_request in order.return_requests.select_related("order_item__item")
        ],
    }


def serialize_recommendation(entry: Recommendation) -> dict:
    return {
        "score": entry.score,
        "reasons": entry.reasons,
        "item": serialize_item(entry.item),
    }


def serialize_search_result(entry: SearchResult) -> dict:
    return {
        "score": entry.score,
        "reasons": entry.reasons,
        "item": serialize_item(entry.item),
    }


def serialize_return_request(return_request: ReturnRequest) -> dict:
    return {
        "id": return_request.pk,
        "order_reference": return_request.order.reference,
        "item": return_request.order_item.item.title,
        "item_slug": return_request.order_item.item.slug,
        "quantity": return_request.quantity,
        "reason": return_request.get_reason_display(),
        "details": return_request.details,
        "status": return_request.get_status_display(),
        "resolution_note": return_request.resolution_note,
        "created_at": return_request.created_at.isoformat(),
    }


def serialize_customer_segment(segment: CustomerSegment | None) -> dict | None:
    if not segment:
        return None
    return {
        "code": segment.code,
        "label": segment.label,
        "confidence": segment.confidence,
        "summary": segment.summary,
    }


def serialize_customer_health(health: CustomerHealth | None) -> dict | None:
    if not health:
        return None
    return {
        "retention_score": health.retention_score,
        "churn_risk": health.churn_risk,
        "next_best_action": health.next_best_action,
        "summary": health.summary,
    }


def serialize_customer_profile(profile: CustomerProfile | None) -> dict | None:
    if not profile:
        return None
    return {
        "email_verified": profile.email_verified,
        "email_verified_at": profile.email_verified_at.isoformat() if profile.email_verified_at else None,
        "marketing_opt_in": profile.marketing_opt_in,
        "preferred_contact_channel": profile.get_preferred_contact_channel_display(),
        "loyalty_score": profile.loyalty_score,
    }


def serialize_login_activity(activity: LoginActivity) -> dict:
    return {
        "status": activity.get_status_display(),
        "ip_address": activity.ip_address,
        "user_agent": activity.user_agent,
        "created_at": activity.created_at.isoformat(),
    }


def serialize_support_message(message: SupportMessage) -> dict:
    return {
        "id": message.pk,
        "author": message.author.username if message.author else "system",
        "sender_role": message.get_sender_role_display(),
        "message": message.message,
        "created_at": message.created_at.isoformat(),
    }


def serialize_support_thread(thread: SupportThread, *, include_messages: bool = False) -> dict:
    payload = {
        "id": thread.pk,
        "subject": thread.subject,
        "category": thread.get_category_display(),
        "priority": thread.get_priority_display(),
        "status": thread.get_status_display(),
        "order_reference": thread.order.reference if thread.order else None,
        "latest_customer_message_at": thread.latest_customer_message_at.isoformat() if thread.latest_customer_message_at else None,
        "latest_support_message_at": thread.latest_support_message_at.isoformat() if thread.latest_support_message_at else None,
        "auto_reply_snapshot": thread.auto_reply_snapshot,
        "created_at": thread.created_at.isoformat(),
        "updated_at": thread.updated_at.isoformat(),
    }
    if include_messages:
        payload["messages"] = [
            serialize_support_message(message)
            for message in thread.messages.select_related("author")
        ]
    return payload


def serialize_support_suggestion(suggestion: SupportSuggestion) -> dict:
    return {
        "title": suggestion.title,
        "answer": suggestion.answer,
        "confidence": suggestion.confidence,
    }
