from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


def _rate_for_scope(scope: str) -> int:
    """Reuse the DRF throttle rates already defined for the v2 API so the
    legacy v1 endpoints get comparable protection instead of none at all.
    """
    rate = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"][scope]
    count, _, _ = rate.partition("/")
    return int(count)


def rate_limit(scope: str):
    """Simple fixed-window per-identity rate limiter for function-based views.

    The legacy v1 JSON API predates DRF throttling and has no rate limiting
    at all, unlike its v2 equivalents. This gives it comparable protection
    using the same cache backend and throttle rates already configured.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            identity = (
                f"user:{request.user.pk}"
                if request.user.is_authenticated
                else f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"
            )
            cache_key = f"dokan:ratelimit:{scope}:{identity}"
            limit = _rate_for_scope(scope)

            current_count = cache.get(cache_key)
            if current_count is None:
                cache.set(cache_key, 1, timeout=3600)
            elif current_count >= limit:
                return JsonResponse(
                    {"error": "Rate limit exceeded. Try again later."}, status=429
                )
            else:
                cache.incr(cache_key)

            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
