from __future__ import annotations

from django.core import signing
from django.db import transaction
from django.utils import timezone

from .models import CustomerProfile, LoginActivity


EMAIL_VERIFICATION_SALT = "dokan.email-verification"
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24 * 7


def ensure_customer_profile(user) -> CustomerProfile:
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    return profile


def is_email_verified(user) -> bool:
    return ensure_customer_profile(user).email_verified


def build_email_verification_token(user) -> str:
    payload = {
        "user_id": user.pk,
        "email": user.email,
    }
    return signing.dumps(payload, salt=EMAIL_VERIFICATION_SALT)


def resolve_email_verification_token(token: str, *, max_age: int = EMAIL_VERIFICATION_MAX_AGE):
    payload = signing.loads(token, salt=EMAIL_VERIFICATION_SALT, max_age=max_age)
    return payload["user_id"], payload["email"]


@transaction.atomic
def mark_email_verified(user) -> CustomerProfile:
    profile = ensure_customer_profile(user)
    if not profile.email_verified:
        profile.email_verified = True
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=["email_verified", "email_verified_at", "updated_at"])
    return profile


def _extract_client_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def record_login_activity(user, request) -> LoginActivity:
    return LoginActivity.objects.create(
        user=user,
        status=LoginActivity.Status.SUCCESS,
        ip_address=_extract_client_ip(request) or None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )
