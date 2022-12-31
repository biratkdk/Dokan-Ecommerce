from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .intelligence import SupportSuggestion, suggest_support_answers
from .models import SupportMessage, SupportThread
from .permissions import can_manage_support_threads


def _serialize_suggestions(suggestions: list[SupportSuggestion]) -> list[dict]:
    return [
        {
            "title": suggestion.title,
            "confidence": suggestion.confidence,
            "answer": suggestion.answer,
        }
        for suggestion in suggestions
    ]


def support_queryset_for_user(user):
    queryset = SupportThread.objects.select_related("user", "order").prefetch_related("messages__author")
    if can_manage_support_threads(user):
        return queryset
    return queryset.filter(user=user)


@transaction.atomic
def create_support_thread(
    user,
    *,
    subject: str,
    category: str,
    priority: str,
    message: str,
    order=None,
) -> SupportThread:
    cleaned_subject = subject.strip()
    cleaned_message = message.strip()
    if not cleaned_subject:
        raise ValidationError("Subject cannot be blank.")
    if not cleaned_message:
        raise ValidationError("Message cannot be blank.")
    if category not in dict(SupportThread.Category.choices):
        raise ValidationError("Choose a valid support category.")
    if priority not in dict(SupportThread.Priority.choices):
        raise ValidationError("Choose a valid support priority.")

    suggestions = suggest_support_answers(message, order=order, limit=3)
    thread = SupportThread.objects.create(
        user=user,
        order=order,
        subject=cleaned_subject,
        category=category,
        priority=priority,
        status=SupportThread.Status.AWAITING_SUPPORT,
        latest_customer_message_at=timezone.now(),
        auto_reply_snapshot=_serialize_suggestions(suggestions),
    )
    SupportMessage.objects.create(
        thread=thread,
        author=user,
        sender_role=SupportMessage.SenderRole.CUSTOMER,
        message=cleaned_message,
    )
    return thread


@transaction.atomic
def post_support_message(thread: SupportThread, author, *, message: str) -> SupportMessage:
    body = message.strip()
    if not body:
        raise ValidationError("Message cannot be blank.")

    if not can_manage_support_threads(author) and thread.user_id != author.pk:
        raise ValidationError("You do not have access to this support conversation.")

    sender_role = (
        SupportMessage.SenderRole.SUPPORT
        if can_manage_support_threads(author)
        else SupportMessage.SenderRole.CUSTOMER
    )
    support_message = SupportMessage.objects.create(
        thread=thread,
        author=author,
        sender_role=sender_role,
        message=body,
    )

    if sender_role == SupportMessage.SenderRole.CUSTOMER:
        thread.latest_customer_message_at = support_message.created_at
        thread.status = SupportThread.Status.AWAITING_SUPPORT
        thread.auto_reply_snapshot = _serialize_suggestions(
            suggest_support_answers(body, order=thread.order, limit=3)
        )
    else:
        thread.latest_support_message_at = support_message.created_at
        thread.status = SupportThread.Status.AWAITING_CUSTOMER

    thread.save(
        update_fields=[
            "latest_customer_message_at",
            "latest_support_message_at",
            "status",
            "auto_reply_snapshot",
            "updated_at",
        ]
    )
    return support_message


@transaction.atomic
def resolve_support_thread(thread: SupportThread, *, actor=None) -> SupportThread:
    thread.status = SupportThread.Status.RESOLVED
    thread.save(update_fields=["status", "updated_at"])
    if actor:
        SupportMessage.objects.create(
            thread=thread,
            author=actor if getattr(actor, "is_authenticated", False) else None,
            sender_role=SupportMessage.SenderRole.SYSTEM,
            message="Conversation marked as resolved.",
        )
    return thread
