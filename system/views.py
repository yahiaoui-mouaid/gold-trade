from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import check_for_language
from django.conf import settings
from django.db import connection
from django.views.decorators.csrf import requires_csrf_token

from accounts.permissions import public, requires

from .services import confirm_clock


@public
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


@public
def set_language(request):
    if request.method != "POST":
        return HttpResponseForbidden()
    code = request.POST.get("language", "")
    target = request.POST.get("next", "")
    response = redirect(target if target.startswith("/") and not target.startswith("//") else "/")
    if code in dict(settings.LANGUAGES) and check_for_language(code):
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, code, samesite="Strict", max_age=31536000)
    return response


@requires("clock.confirm")
def clock_confirm(request):
    if request.method == "POST":
        confirm_clock(request.user)
    return redirect("dashboard")


@requires_csrf_token
def forbidden(request, exception=None):
    return render(request, "403.html", status=403)


@requires_csrf_token
def not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    return HttpResponse(
        '<!doctype html><meta charset="utf-8"><title>Gold Volt</title>'
        "<p>حدث خطأ غير متوقع. أعد المحاولة.</p><p>Erreur inattendue. Réessayez.</p>",
        status=500,
    )
