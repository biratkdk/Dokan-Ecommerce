CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://stackpath.bootstrapcdn.com; "
    "font-src 'self' https://fonts.gstatic.com https://stackpath.bootstrapcdn.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self' https://checkout.stripe.com;"
)


EXEMPT_PATH_PREFIXES = ("/admin/", "/api/docs/", "/api/schema/")


class ContentSecurityPolicyMiddleware:
    """Django admin and the Swagger UI docs page both rely on inline
    scripts/styles this policy doesn't allow, so those are left alone --
    this is scoped to the customer-facing storefront."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith(EXEMPT_PATH_PREFIXES):
            response.setdefault("Content-Security-Policy", CSP_POLICY)
        return response
