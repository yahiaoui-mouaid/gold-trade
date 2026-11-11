"""Deny by default. Every view declares what it needs; a view that declares
nothing is refused by DenyByDefaultMiddleware."""
import time
from functools import wraps
from urllib.parse import quote

from django.shortcuts import redirect
from django.urls import reverse

PUBLIC = "__public__"
AUTHENTICATED = "__authenticated__"
RECONFIRM_SECONDS = 300

SALESMAN_PERMISSIONS = frozenset({
    "operation.post",
    "operation.receipt",
    "party.search",
    "party.add_basic",
})


def role_allows(user, permission):
    if permission == AUTHENTICATED:
        return True
    if user.is_owner:
        return True
    return permission in SALESMAN_PERMISSIONS


def public(view):
    view.gv_permission = PUBLIC
    return view


def logged_in(view):
    view.gv_permission = AUTHENTICATED
    return view


def requires(permission):
    def decorator(view):
        view.gv_permission = permission
        return view
    return decorator


def require_reconfirm(view):
    """Asks for password and code again when the last confirmation is old."""
    @wraps(view)
    def inner(request, *args, **kwargs):
        if time.time() - request.session.get("confirmed_at", 0) > RECONFIRM_SECONDS:
            return redirect(f"{reverse('confirm')}?next={quote(request.get_full_path())}")
        return view(request, *args, **kwargs)
    return inner
