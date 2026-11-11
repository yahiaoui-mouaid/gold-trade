from django.core.paginator import Paginator
from django.shortcuts import render

from accounts.models import User
from accounts.permissions import requires
from parties.views import _day

from .models import AuditEvent
from .services import verify_chain


@requires("activity.view")
def log(request):
    get = request.GET
    rows = AuditEvent.objects.all()
    if get.get("user", "").isdigit():
        rows = rows.filter(user_id=int(get["user"]))
    if get.get("action"):
        rows = rows.filter(action__icontains=get["action"])
    if get.get("party", "").isdigit():
        rows = rows.filter(party_id=int(get["party"]))
    if get.get("pages") != "1":
        rows = rows.exclude(action="page.open")
    start, end = _day(get.get("from")), _day(get.get("to"), end=True)
    if start:
        rows = rows.filter(at__gte=start)
    if end:
        rows = rows.filter(at__lte=end)
    report = verify_chain() if request.method == "POST" else None
    page = Paginator(rows, 100).get_page(get.get("page"))
    return render(request, "audit/log.html", {"page": page, "users": User.objects.all(), "f": get, "report": report})
