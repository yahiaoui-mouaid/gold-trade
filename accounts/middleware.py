import time

from django.contrib.auth import logout
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse

from audit.services import record_event

from .permissions import PUBLIC, role_allows

IDLE_SECONDS = {"owner": 600, "salesman": 300}


class SessionGuardMiddleware:
    """Idle lock, and the screens that must be finished before anything else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/static/") or not request.user.is_authenticated:
            return self.get_response(request)

        now = time.time()
        last_seen = request.session.get("last_seen", now)
        if now - last_seen > IDLE_SECONDS[request.user.role]:
            record_event("session.idle_lock", user=request.user)
            logout(request)
            return redirect("login")
        request.session["last_seen"] = now

        allowed = {reverse("logout"), reverse("recovery")}
        if request.session.get("recovery_display") and request.path not in allowed:
            return redirect("recovery")
        allowed.add(reverse("enroll"))
        if request.session.get("must_reenroll") and request.path not in allowed:
            return redirect("enroll")
        return self.get_response(request)


class DenyByDefaultMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        permission = getattr(view_func, "gv_permission", None)
        if permission == PUBLIC:
            return None
        if permission is None:
            return HttpResponseForbidden("Forbidden")
        if not request.user.is_authenticated:
            if request.headers.get("HX-Request"):
                response = HttpResponse(status=401)
                response["HX-Redirect"] = reverse("login")
                return response
            return redirect("login")
        if not role_allows(request.user, permission):
            record_event("access.denied", user=request.user,
                         details={"path": request.path, "permission": permission})
            return render(request, "403.html", status=403)
        return None
