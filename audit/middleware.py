from .services import record_event

SKIP_PREFIXES = ("/static/", "/health/")


class PageOpenMiddleware:
    """Records every full page a logged-in user opens. HTMX fragments, such as
    live previews, are not recorded."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if (
            request.method == "GET"
            and response.status_code == 200
            and user is not None
            and user.is_authenticated
            and not request.headers.get("HX-Request")
            and not request.path.startswith(SKIP_PREFIXES)
        ):
            record_event("page.open", user=user, details={"path": request.get_full_path()})
        return response
