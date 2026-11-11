from django.shortcuts import render

from accounts.permissions import requires
from catalog.models import Origin
from parties.models import Party
from system.services import clock_status

from . import services


@requires("dashboard.view")
def dashboard(request):
    rows = services.debt_rows()
    return render(request, "reports/dashboard.html", {
        "totals": services.totals(rows), "alerts": services.alerts(), "drawer": services.drawer(),
        "clock": clock_status(),
    })


@requires("debts.view")
def debts(request):
    get = request.GET
    rows = services.debt_rows()
    if get.get("direction") == "to_me":
        rows = [r for r in rows if r["to_me"]]
    elif get.get("direction") == "by_me":
        rows = [r for r in rows if not r["to_me"]]
    if get.get("asset") in ("money", "gold"):
        rows = [r for r in rows if r["asset"] == get["asset"]]
    if get.get("origin", "").isdigit():
        rows = [r for r in rows if r["origin_id"] == int(get["origin"])]
    if get.get("party_kind"):
        rows = [r for r in rows if r["kind"] == get["party_kind"]]
    return render(request, "reports/debts.html", {
        "rows": rows, "totals": services.totals(rows), "origins": Origin.objects.all(),
        "party_kinds": Party.KINDS, "f": get,
    })
