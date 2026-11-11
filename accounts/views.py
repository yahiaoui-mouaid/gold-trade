import base64
import time

import segno
from django.contrib.auth import login, logout
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from audit.services import record_event

from . import services
from .models import User
from .permissions import logged_in, public, require_reconfirm, requires
from .services import AuthError, LoginStatus

PENDING_SECONDS = 600


def _start_session(request, user, method):
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    services.complete_login(user, method)
    now = time.time()
    request.session["confirmed_at"] = now
    request.session["last_seen"] = now


def _set_pending(request, user, stage):
    request.session["pending"] = {"uid": user.pk, "ts": time.time(), "stage": stage}


def _pending_user(request, stage):
    pending = request.session.get("pending")
    if not pending or pending["stage"] != stage or time.time() - pending["ts"] > PENDING_SECONDS:
        return None
    return User.objects.filter(pk=pending["uid"], is_active=True).first()


@public
def home(request):
    if not services.owner_exists():
        return redirect("setup")
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect("dashboard" if request.user.is_owner else "new_sale")


@public
def setup(request):
    if services.owner_exists():
        return redirect("login")
    error = None
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            if password != request.POST.get("password2", ""):
                raise AuthError(_("The two passwords do not match."))
            username = request.POST.get("username", "").strip()
            if not username:
                raise AuthError(_("This username is empty or already used."))
            user = services.create_owner(username, request.POST.get("display_name", "").strip(), password)
        except AuthError as exc:
            error = str(exc)
        else:
            _set_pending(request, user, "enroll")
            return redirect("enroll")
    return render(request, "accounts/setup.html", {"error": error})


@public
def login_view(request):
    if not services.owner_exists():
        return redirect("setup")
    if request.user.is_authenticated:
        return redirect("home")
    error = None
    if request.method == "POST":
        status, user = services.check_credentials(request.POST.get("username", "").strip(),
                                                  request.POST.get("password", ""))
        if status is LoginStatus.LOCKED:
            error = _("This account is locked for a short time. Try again later.")
        elif status is LoginStatus.BAD:
            error = _("Wrong username or password.")
        elif not user.is_owner:
            _start_session(request, user, "password")
            return redirect("home")
        elif services.confirmed_device(user) is None:
            _set_pending(request, user, "enroll")
            return redirect("enroll")
        else:
            _set_pending(request, user, "code")
            return redirect("login_code")
    return render(request, "accounts/login.html", {"error": error})


@public
def login_code(request):
    user = _pending_user(request, "code")
    if user is None:
        return redirect("login")
    error = None
    if request.method == "POST":
        method = services.verify_second_factor(user, request.POST.get("code", ""))
        if method:
            del request.session["pending"]
            _start_session(request, user, method)
            if method == "backup":
                request.session["must_reenroll"] = True
                return redirect("enroll")
            return redirect("home")
        error = _("That code is not correct.")
    return render(request, "accounts/login_code.html", {"error": error})


@public
def forgot_password(request):
    error = None
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            if password != request.POST.get("password2", ""):
                raise AuthError(_("The two passwords do not match."))
            new_token = services.reset_password_with_token(request.POST.get("token", ""), password)
        except AuthError as exc:
            error = str(exc)
        else:
            request.session["recovery_display"] = {"token": new_token, "codes": None}
            return redirect("recovery")
    return render(request, "accounts/forgot.html", {"error": error})


@public
def enroll(request):
    pending = _pending_user(request, "enroll")
    user = request.user if request.user.is_authenticated else pending
    if user is None:
        return redirect("login")
    if not user.is_owner:
        return redirect("home")
    if (request.user.is_authenticated and not request.session.get("must_reenroll")
            and time.time() - request.session.get("confirmed_at", 0) > 300):
        return redirect(f"{reverse('confirm')}?next={reverse('enroll')}")

    device = services.enrollment_device(user)
    error = None
    if request.method == "POST":
        try:
            codes = services.confirm_enrollment(user, request.POST.get("code", ""))
        except AuthError as exc:
            error = str(exc)
        else:
            token = None if services.has_active_reset_token(user) else services.issue_reset_token(user)
            if pending is not None and not request.user.is_authenticated:
                del request.session["pending"]
                _start_session(request, user, "enrollment")
            request.session.pop("must_reenroll", None)
            request.session["recovery_display"] = {"token": token, "codes": codes}
            return redirect("recovery")
    context = {
        "qr": segno.make(device.config_url, error="m").svg_inline(scale=5, border=2),
        "manual_key": base64.b32encode(device.bin_key).decode("ascii"),
        "error": error,
        "must_reenroll": request.session.get("must_reenroll"),
    }
    return render(request, "accounts/enroll.html", context)


@public
def recovery(request):
    display = request.session.get("recovery_display")
    if not display:
        return redirect("home")
    if request.method == "POST" and request.POST.get("saved"):
        del request.session["recovery_display"]
        record_event("recovery.shown_and_confirmed", user=request.user if request.user.is_authenticated else None)
        return redirect("home")
    lines = ["Gold Volt"]
    if display.get("token"):
        lines += ["", "Password reset token:", display["token"]]
    if display.get("codes"):
        lines += ["", "Backup codes (each works once):", *display["codes"]]
    return render(request, "accounts/recovery.html", {"display": display, "text_file": "\n".join(lines) + "\n"})


@logged_in
def logout_view(request):
    if request.method != "POST":
        return HttpResponseForbidden()
    record_event("logout", user=request.user)
    logout(request)
    return redirect("login")


@logged_in
def confirm(request):
    """Ask again for password and code before a sensitive action."""
    if not request.user.is_owner:
        return HttpResponseForbidden()
    target = request.GET.get("next") or reverse("home")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = reverse("home")
    error = None
    if request.method == "POST":
        if request.user.check_password(request.POST.get("password", "")) and services.verify_second_factor(
                request.user, request.POST.get("code", "")):
            request.session["confirmed_at"] = time.time()
            record_event("identity.confirmed", user=request.user)
            return redirect(target)
        record_event("identity.confirm_failed", user=request.user)
        error = _("Wrong password or code.")
    return render(request, "accounts/confirm.html", {"error": error, "next": target})


@logged_in
def change_password(request):
    error = None
    if request.method == "POST":
        try:
            if request.POST.get("new", "") != request.POST.get("new2", ""):
                raise AuthError(_("The two passwords do not match."))
            services.change_own_password(request.user, request.POST.get("current", ""), request.POST.get("new", ""))
        except AuthError as exc:
            error = str(exc)
        else:
            return redirect("home")
    return render(request, "accounts/password.html", {"error": error})


@requires("users.manage")
@require_reconfirm
def users(request):
    error = None
    if request.method == "POST":
        try:
            services.create_salesman(request.user, request.POST.get("username", "").strip(),
                                     request.POST.get("display_name", "").strip(), request.POST.get("password", ""))
        except AuthError as exc:
            error = str(exc)
        else:
            return redirect("users")
    return render(request, "accounts/users.html", {"users": User.objects.order_by("role", "username"), "error": error})


@requires("users.manage")
@require_reconfirm
def user_reset(request, pk):
    target = get_object_or_404(User, pk=pk, role=User.SALESMAN)
    error = None
    if request.method == "POST":
        try:
            services.reset_salesman_password(request.user, target, request.POST.get("password", ""))
        except AuthError as exc:
            error = str(exc)
        else:
            return redirect("users")
    return render(request, "accounts/user_reset.html", {"target": target, "error": error})


@requires("users.manage")
@require_reconfirm
def user_toggle(request, pk):
    target = get_object_or_404(User, pk=pk, role=User.SALESMAN)
    if request.method == "POST":
        services.set_salesman_active(request.user, target, not target.is_active)
    return redirect("users")
