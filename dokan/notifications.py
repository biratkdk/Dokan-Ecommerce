from __future__ import annotations

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


def _create_notification_log(
    *,
    kind: str,
    recipient_email: str,
    subject: str,
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
        delivery_state=delivery_state,
        error_message=error_message,
        payload=payload or {},
    )


def _mark_notification_sent(notification: EmailNotification) -> EmailNotification:
    notification.delivery_state = EmailNotification.DeliveryState.SENT
    notification.sent_at = timezone.now()
    notification.error_message = ""
    notification.save(update_fields=["delivery_state", "sent_at", "error_message", "updated_at"])
    return notification


def _mark_notification_failed(notification: EmailNotification, *, error_message: str) -> EmailNotification:
    notification.delivery_state = EmailNotification.DeliveryState.FAILED
    notification.error_message = error_message[:255]
    notification.save(update_fields=["delivery_state", "error_message", "updated_at"])
    return notification


def _send_template_email(
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
        delivery_state=EmailNotification.DeliveryState.SENT,
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
            error_message="Notification already sent.",
        )

    notification = _create_notification_log(
        kind=kind,
        recipient_email=recipient_email,
        subject=subject,
        user=user,
        order=order,
        support_thread=support_thread,
        payload=payload,
    )

    text_body = render_to_string(text_template, context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@redstore.local"),
        to=[recipient_email],
    )
    if html_template:
        message.attach_alternative(
            render_to_string(html_template, context),
            "text/html",
        )

    try:
        message.send(fail_silently=False)
    except Exception as exc:
        return _mark_notification_failed(notification, error_message=str(exc))
    return _mark_notification_sent(notification)


def send_email_verification_email(user, *, request=None) -> EmailNotification:
    verification_url = _build_absolute_url(
        reverse("store:verify-email", kwargs={"token": build_email_verification_token(user)}),
        request=request,
    )
    return _send_template_email(
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
    return _send_template_email(
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
    return _send_template_email(
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
    return _send_template_email(
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
    return _send_template_email(
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
