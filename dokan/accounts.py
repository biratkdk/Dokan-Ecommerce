from __future__ import annotations

import secrets

from django.core import signing
from django.db import transaction
from django.utils import timezone

from .models import CustomerProfile, LoginActivity


EMAIL_VERIFICATION_SALT = "dokan.email-verification"
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24 * 7

EMAIL_OTP_LENGTH = 6
EMAIL_OTP_TTL_SECONDS = 60 * 10
EMAIL_OTP_MAX_ATTEMPTS = 5


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


@transaction.atomic
def mark_email_unverified(user) -> CustomerProfile:
    profile = ensure_customer_profile(user)
    profile.email_verified = False
    profile.email_verified_at = None
    profile.save(update_fields=["email_verified", "email_verified_at", "updated_at"])
    return profile


def generate_email_verification_code(user) -> str:
    """Create a fresh numeric verification code for the user, valid for
    EMAIL_OTP_TTL_SECONDS and resetting the attempt counter.
    """
    profile = ensure_customer_profile(user)
    code = f"{secrets.randbelow(10 ** EMAIL_OTP_LENGTH):0{EMAIL_OTP_LENGTH}d}"
    profile.email_verification_code = code
    profile.email_verification_code_expires_at = timezone.now() + timezone.timedelta(
        seconds=EMAIL_OTP_TTL_SECONDS
    )
    profile.email_verification_attempts = 0
    profile.save(
        update_fields=[
            "email_verification_code",
            "email_verification_code_expires_at",
            "email_verification_attempts",
            "updated_at",
        ]
    )
    return code


@transaction.atomic
def verify_email_code(user, submitted_code: str) -> tuple[bool, str]:
    """Validate a submitted OTP against the user's profile.

    Returns (success, error_message). On success the profile is marked
    verified and the code is cleared so it can't be reused.
    """
    profile = ensure_customer_profile(user)

    if profile.email_verified:
        return True, ""

    if not profile.email_verification_code:
        return False, "Request a new verification code first."

    if (
        not profile.email_verification_code_expires_at
        or timezone.now() > profile.email_verification_code_expires_at
    ):
        return False, "That code has expired. Request a new one."

    if profile.email_verification_attempts >= EMAIL_OTP_MAX_ATTEMPTS:
        return False, "Too many incorrect attempts. Request a new code."

    submitted = (submitted_code or "").strip()
    if not submitted or not secrets.compare_digest(submitted, profile.email_verification_code):
        profile.email_verification_attempts += 1
        profile.save(update_fields=["email_verification_attempts", "updated_at"])
        return False, "That code doesn't match. Check your email and try again."

    profile.email_verified = True
    profile.email_verified_at = timezone.now()
    profile.email_verification_code = ""
    profile.email_verification_code_expires_at = None
    profile.email_verification_attempts = 0
    profile.save(
        update_fields=[
            "email_verified",
            "email_verified_at",
            "email_verification_code",
            "email_verification_code_expires_at",
            "email_verification_attempts",
            "updated_at",
        ]
    )
    return True, ""


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
