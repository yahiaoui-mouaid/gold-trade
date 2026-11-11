from datetime import datetime, time

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.permissions import requires
from catalog.models import Category, Origin
from ledger.models import PartyLedgerEntry, Transaction
from ledger.services import party_balances

from . import services
from .models import Party
from .services import PartyError

KINDS_FOR = {"sale": [Party.CLIENT], "purchase": [Party.SUPPLIER, Party.WORKSHOP]}


def _extra_fields(post):
    alert = post.get("alert_days", "").strip()
    return {
        "id_number": post.get("id_number", "").strip(),
        "address": post.get("address", "").strip(),
        "notes": post.get("notes", "").strip(),
        "alert_days": int(alert) if alert.isdigit() else None,
    }


@requires("party.manage")
def party_list(request):
    query = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    rows = services.search_parties(query, include_archived=True) if query else Party.objects.all()
    if kind:
        rows = rows.filter(kind=kind)
    return render(request, "parties/list.html", {"parties": rows[:300], "q": query, "kind": kind})


@requires("party.manage")
def party_new(request):
    error = None
    if request.method == "POST":
        try:
            party = services.create_party(request.user, request.POST.get("kind"), request.POST.get("name"),
                                          request.POST.get("phone"), **_extra_fields(request.POST))
        except PartyError as exc:
            error = str(exc)
        else:
            return redirect("party_folder", pk=party.pk)
    return render(request, "parties/form.html", {"party": None, "error": error, "kinds": Party.KINDS})


@requires("party.manage")
def party_edit(request, pk):
    party = get_object_or_404(Party, pk=pk)
    error = None
    if request.method == "POST":
        try:
            services.update_party(request.user, party, kind=request.POST.get("kind"), name=request.POST.get("name"),
                                  phone=request.POST.get("phone"), **_extra_fields(request.POST))
        except PartyError as exc:
            error = str(exc)
        else:
            return redirect("party_folder", pk=party.pk)
    return render(request, "parties/form.html", {"party": party, "error": error, "kinds": Party.KINDS})


@requires("party.manage")
def party_archive(request, pk):
    party = get_object_or_404(Party, pk=pk)
    if request.method == "POST":
        services.set_archived(request.user, party, not party.archived)
    return redirect("party_folder", pk=party.pk)


def _day(value, end=False):
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return timezone.make_aware(datetime.combine(day, time.max if end else time.min))


@requires("party.manage")
def party_folder(request, pk):
    """Everything about one client or supplier, filterable and printable."""
    party = get_object_or_404(Party, pk=pk)
    txns = Transaction.objects.filter(party=party).prefetch_related(
        "lines__stock_item__category", "lines__stock_item__origin", "lines__stock_item__purity",
        "ledger_entries__origin")
    get = request.GET
    start, end = _day(get.get("from")), _day(get.get("to"), end=True)
    if start:
        txns = txns.filter(operation_at__gte=start)
    if end:
        txns = txns.filter(operation_at__lte=end)
    if get.get("asset") in (PartyLedgerEntry.MONEY_ASSET, PartyLedgerEntry.GOLD):
        txns = txns.filter(ledger_entries__asset=get["asset"])
    if get.get("origin", "").isdigit():
        txns = txns.filter(lines__stock_item__origin_id=int(get["origin"]))
    if get.get("category", "").isdigit():
        txns = txns.filter(lines__stock_item__category_id=int(get["category"]))
    return render(request, "parties/folder.html", {
        "party": party, "balances": party_balances(party), "transactions": txns.distinct()[:1000],
        "origins": Origin.objects.all(), "categories": Category.objects.all(), "f": get,
    })


@requires("party.search")
def party_search(request):
    """Names and phones only: this fragment is all a salesman can ever see."""
    purpose = request.GET.get("for", "")
    rows = services.search_parties(request.GET.get("q", ""), kinds=KINDS_FOR.get(purpose))
    results = [{"id": r.pk, "name": r.name, "phone": r.phone or ""} for r in rows[:services.SEARCH_LIMIT]]
    return render(request, "parties/_results.html", {"results": results})


@requires("party.add_basic")
def party_quick_add(request):
    """New client or supplier from the operation screen: name and phone only."""
    if request.method != "POST":
        return redirect("home")
    purpose = request.POST.get("purpose", "sale")
    kind = request.POST.get("quick_kind") if purpose == "payment" else KINDS_FOR.get(purpose, [Party.CLIENT])[0]
    message, party = None, None
    try:
        party = services.create_party(request.user, kind, request.POST.get("quick_name"),
                                      request.POST.get("quick_phone"), require_phone=True)
    except PartyError as exc:
        message = str(exc)
        party = exc.existing
    results = [{"id": party.pk, "name": party.name, "phone": party.phone or "", "checked": True}] if party else []
    if party and message:
        message = _("This phone number already exists, so that person is selected instead.")
    return render(request, "parties/_results.html", {"results": results, "message": message})
