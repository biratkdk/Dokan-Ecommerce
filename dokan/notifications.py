from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .accounts import build_email_verification_token
from .models import EmailNotification, Order, ReturnRequest, SupportMessage, SupportThread


def _build_absolute_url(path: str, *, request=None) -> str:
    if request is not None:
        return request.build_absolute_uri(path)
    base_url = getattr(settings, "SITE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base_url}{path}"


def _delivery_mode() -> str:
    return getattr(settings, "EMAIL_DELIVERY_MODE", "queue").strip().lower() or "queue"


def _should_queue_delivery() -> bool:
    return _delivery_mode() != "sync"


def _create_notification_log(
    *,
    kind: str,
    recipient_email: str,
    subject: str,
    text_body: str = "",
    html_body: str = "",
    user=None,
    order: Order | None = None,
    support_thread: SupportThread | None = None,
    payload: dict | None = None,
    delivery_state: str = EmailNotification.DeliveryState.PENDING,
    error_message: str = "",
) -> EmailNotification:
    return EmailNotification.objects.create(
        user=user,
        order=order,
        support_thread=support_thread,
        kind=kind,
        recipient_email=recipient_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        delivery_state=delivery_state,
        error_message=error_message,
        payload=payload or {},
    )


def _mark_notification_sent(
    notification: EmailNotification,
    *,
    attempted_at,
) -> EmailNotification:
    notification.delivery_state = EmailNotification.DeliveryState.SENT
    notification.sent_at = attempted_at
    notification.last_attempt_at = attempted_at
    notification.attempt_count += 1
    notification.error_message = ""
    notification.save(
        update_fields=[
            "delivery_state",
            "sent_at",
            "last_attempt_at",
            "attempt_count",
            "error_message",
            "updated_at",
        ]
    )
    return notification


def _mark_notification_failed(
    notification: EmailNotification,
    *,
    error_message: str,
    attempted_at,
) -> EmailNotification:
    notification.delivery_state = EmailNotification.DeliveryState.FAILED
    notification.last_attempt_at = attempted_at
    notification.attempt_count += 1
    notification.error_message = error_message[:255]
    notification.save(
        update_fields=[
            "delivery_state",
            "last_attempt_at",
            "attempt_count",
            "error_message",
            "updated_at",
        ]
    )
    return notification


def deliver_email_notification(notification: EmailNotification) -> EmailNotification:
    if notification.delivery_state in {
        EmailNotification.DeliveryState.SENT,
        EmailNotification.DeliveryState.SKIPPED,
    }:
        return notification

    if not notification.recipient_email:
        notification.delivery_state = EmailNotification.DeliveryState.SKIPPED
        notification.error_message = "Recipient email was blank."
        notification.save(update_fields=["delivery_state", "error_message", "updated_at"])
        return notification

    attempted_at = timezone.now()
    message = EmailMultiAlternatives(
        subject=notification.subject,
        body=notification.text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@redstore.local"),
        to=[notification.recipient_email],
    )
    if notification.html_body:
        message.attach_alternative(notification.html_body, "text/html")

    try:
        message.send(fail_silently=False)
    except Exception as exc:
        return _mark_notification_failed(
            notification,
            error_message=str(exc),
            attempted_at=attempted_at,
        )
    return _mark_notification_sent(notification, attempted_at=attempted_at)


def process_pending_email_queue(
    *,
    limit: int | None = None,
    kinds: Iterable[str] | None = None,
    include_failed: bool = False,
) -> dict[str, int]:
    states = [EmailNotification.DeliveryState.PENDING]
    if include_failed:
        states.append(EmailNotification.DeliveryState.FAILED)

    queryset = EmailNotification.objects.filter(delivery_state__in=states).order_by(
        "created_at",
        "pk",
    )
    if kinds:
        queryset = queryset.filter(kind__in=list(kinds))

    if limit:
        notifications = list(queryset[:limit])
    else:
        notifications = list(queryset)

    summary = {
        "processed": len(notifications),
        "sent": 0,
        "failed": 0,
        "skipped": 0,
    }
    for notification in notifications:
        notification = deliver_email_notification(notification)
        if notification.delivery_state == EmailNotification.DeliveryState.SENT:
            summary["sent"] += 1
        elif notification.delivery_state == EmailNotification.DeliveryState.FAILED:
            summary["failed"] += 1
        elif notification.delivery_state == EmailNotification.DeliveryState.SKIPPED:
            summary["skipped"] += 1
    return summary


def _queue_template_email(
    *,
    kind: str,
    recipient_email: str,
    subject: str,
    text_template: str,
    context: dict,
    html_template: str | None = None,
    user=None,
    order: Order | None = None,
    support_thread: SupportThread | None = None,
    payload: dict | None = None,
    skip_if_sent: bool = False,
) -> EmailNotification:
    if not recipient_email:
        return _create_notification_log(
            kind=kind,
            recipient_email="",
            subject=subject,
            user=user,
            order=order,
            support_thread=support_thread,
            payload=payload,
            delivery_state=EmailNotification.DeliveryState.SKIPPED,
            error_message="Recipient email was blank.",
        )

    if skip_if_sent and EmailNotification.objects.filter(
        kind=kind,
        recipient_email=recipient_email,
        order=order,
        delivery_state__in=[
            EmailNotification.DeliveryState.PENDING,
            EmailNotification.DeliveryState.SENT,
        ],
    ).exists():
        return _create_notification_log(
            kind=kind,
            recipient_email=recipient_email,
            subject=subject,
            user=user,
            order=order,
            support_thread=support_thread,
            payload=payload,
            delivery_state=EmailNotification.DeliveryState.SKIPPED,
            error_message="Notification already queued or sent.",
        )

    notification = _create_notification_log(
        kind=kind,
        recipient_email=recipient_email,
        subject=subject,
        text_body=render_to_string(text_template, context),
        html_body=render_to_string(html_template, context) if html_template else "",
        user=user,
        order=order,
        support_thread=support_thread,
        payload=payload,
    )
    if _should_queue_delivery():
        return notification
    return deliver_email_notification(notification)


def send_email_verification_email(user, *, request=None) -> EmailNotification:
    verification_url = _build_absolute_url(
        reverse("store:verify-email", kwargs={"token": build_email_verification_token(user)}),
        request=request,
    )
    return _queue_template_email(
        kind=EmailNotification.Kind.VERIFY_EMAIL,
        recipient_email=user.email,
        subject="Verify your Redstore account email",
        text_template="emails/verify_email.txt",
        context={
            "user": user,
            "verification_url": verification_url,
        },
        user=user,
        payload={"verification_url": verification_url},
    )


def send_order_placed_email(order: Order) -> EmailNotification:
    return _queue_template_email(
        kind=EmailNotification.Kind.ORDER_PLACED,
        recipient_email=order.user.email,
        subject=f"Redstore order {order.reference} placed",
        text_template="emails/order_placed.txt",
        context={
            "order": order,
            "user": order.user,
        },
        user=order.user,
        order=order,
        payload={"reference": order.reference},
    )


def send_payment_received_email(order: Order) -> EmailNotification:
    return _queue_template_email(
        kind=EmailNotification.Kind.PAYMENT_RECEIVED,
        recipient_email=order.user.email,
        subject=f"Payment received for Redstore order {order.reference}",
        text_template="emails/payment_received.txt",
        context={
            "order": order,
            "user": order.user,
        },
        user=order.user,
        order=order,
        payload={"reference": order.reference, "payment_reference": order.payment_reference},
        skip_if_sent=True,
    )


def send_return_requested_email(return_request: ReturnRequest) -> EmailNotification:
    return _queue_template_email(
        kind=EmailNotification.Kind.RETURN_REQUESTED,
        recipient_email=return_request.user.email,
        subject=f"Return request received for order {return_request.order.reference}",
        text_template="emails/return_requested.txt",
        context={
            "return_request": return_request,
            "order": return_request.order,
            "user": return_request.user,
        },
        user=return_request.user,
        order=return_request.order,
        payload={"return_request_id": return_request.pk},
    )


def send_support_reply_email(thread: SupportThread, message: SupportMessage) -> EmailNotification:
    return _queue_template_email(
        kind=EmailNotification.Kind.SUPPORT_REPLY,
        recipient_email=thread.user.email,
        subject=f"Redstore support update: {thread.subject}",
        text_template="emails/support_reply.txt",
        context={
            "thread": thread,
            "message": message,
            "user": thread.user,
            "thread_url": _build_absolute_url(
                reverse("store:support-thread-detail", kwargs={"thread_id": thread.pk})
            ),
        },
        user=thread.user,
        support_thread=thread,
        payload={"thread_id": thread.pk, "message_id": message.pk},
    )
