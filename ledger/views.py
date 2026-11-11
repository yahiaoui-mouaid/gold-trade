import uuid

from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import User
from accounts.permissions import require_reconfirm, requires
from audit.services import record_event
from catalog.models import Category, Origin, Purity
from parties.models import Party
from parties.views import _day
from system.services import ClockBlocked

from . import forms, services
from .forms import FormError
from .models import PartyLedgerEntry, Transaction
from .services import InsufficientStock, OperationError
from .settlement import ZERO

REFUSALS = (FormError, OperationError, ClockBlocked)


def _options():
    return {
        "origins": Origin.objects.filter(disabled=False),
        "purities": Purity.objects.filter(disabled=False),
        "categories": Category.objects.filter(disabled=False),
    }


def _message(exc, user):
    if isinstance(exc, InsufficientStock) and user.is_owner:
        grams, pieces = exc.available
        return _("Not enough stock: %(item)s has %(grams)s g and %(pieces)s pieces.") % {
            "item": exc.item, "grams": grams, "pieces": pieces}
    return str(exc)


def _refused(request, kind, exc):
    message = _message(exc, request.user)
    record_event("operation.refused", user=request.user, details={"kind": kind, "reason": message})
    return message


def _selected_party(post):
    raw = (post.get("party") or "").strip()
    party = Party.objects.filter(pk=raw).first() if raw.isdigit() else None
    return {"id": party.pk, "name": party.name, "phone": party.phone or "", "checked": True} if party else None


def _base_context(request, kind):
    now = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
    post = request.POST if request.method == "POST" else {}
    selected = _selected_party(post) if post else None
    return {
        **_options(),
        "kind": kind,
        "form_token": post.get("form_token") or uuid.uuid4(),
        "operation_at": post.get("operation_at") or now,
        "operation_at_default": post.get("operation_at_default") or now,
        "selected": selected,
        "selected_list": [selected] if selected else [],
        "post": post,
    }


def _operation(request, kind):
    error = None
    if request.method == "POST":
        try:
            draft = forms.read_draft(request.POST, kind)
            txn = services.post_transaction(request.user, draft)
        except REFUSALS as exc:
            error = _refused(request, kind, exc)
        else:
            request.session["just_posted"] = txn.pk
            return redirect("receipt", pk=txn.pk)
    context = _base_context(request, kind)
    context["error"] = error
    in_list = forms.in_rows(request.POST) if request.method == "POST" else []
    out_list = forms.out_rows(request.POST) if request.method == "POST" else []
    context["in_rows"] = in_list or [{}]
    context["out_rows"] = out_list or [{}]
    return render(request, "ledger/operation.html", context)


@requires("operation.post")
def new_sale(request):
    return _operation(request, Transaction.SALE)


@requires("operation.post")
def new_purchase(request):
    return _operation(request, Transaction.PURCHASE)


def _describe(calc):
    origins = Origin.objects.in_bulk(list(calc.gold))
    return [{"origin": origins[o].name, "value": v} for o, v in calc.gold.items()]


@requires("operation.post")
def preview(request):
    """The live result for this operation only. Nothing is saved."""
    kind = request.POST.get("kind")
    if request.method != "POST" or kind not in (Transaction.SALE, Transaction.PURCHASE):
        return HttpResponseForbidden()
    try:
        draft = forms.read_draft(request.POST, kind)
        calc = services.preview_transaction(draft)
    except (FormError, OperationError) as exc:
        return render(request, "ledger/_preview.html", {"hint": str(exc)})
    return render(request, "ledger/_preview.html", {
        "gold": _describe(calc), "facon_total": calc.facon_total, "money_difference": calc.money_difference,
        "kind": kind,
    })


@requires("operation.post")
def new_payment(request):
    error = None
    over_warning = False
    if request.method == "POST":
        try:
            draft = forms.read_payment(request.POST)
            if request.user.is_owner and not request.POST.get("confirm_over") and _overpays(draft):
                over_warning = True
            else:
                txn = services.post_transaction(request.user, draft)
                request.session["just_posted"] = txn.pk
                return redirect("receipt", pk=txn.pk)
        except REFUSALS as exc:
            error = _refused(request, "payment", exc)
    context = _base_context(request, Transaction.PAYMENT)
    context.update(error=error, over_warning=over_warning)
    return render(request, "ledger/payment.html", context)


def _overpays(draft):
    """True when a payment is larger than the matching debt. Owner only: a
    salesman must learn nothing about a balance."""
    party = Party.objects.filter(pk=draft.party_id).first()
    if party is None:
        return False
    calc = services.calculate(draft)
    entries = PartyLedgerEntry.objects.filter(party=party)
    if calc.gold:
        origin_id, change = next(iter(calc.gold.items()))
        balance = sum((e.fine_grams for e in entries.filter(asset="gold", origin_id=origin_id)), ZERO)
    else:
        change = calc.money_difference
        balance = sum((e.amount_da for e in entries.filter(asset="money")), ZERO)
    after = balance + change
    return after != ZERO and (balance == ZERO or (balance > ZERO) != (after > ZERO))


@requires("operation.receipt")
def receipt(request, pk):
    """The owner can open any receipt. A salesman sees only the operation they
    just posted, once, and never a running balance."""
    txn = get_object_or_404(
        Transaction.objects.select_related("party", "reversal_of").prefetch_related(
            "lines__stock_item__category", "lines__stock_item__origin", "lines__stock_item__purity",
            "ledger_entries__origin"),
        pk=pk,
    )
    if not request.user.is_owner:
        if request.session.get("just_posted") != txn.pk or txn.author_id != request.user.pk:
            record_event("access.denied", user=request.user, details={"path": request.path})
            return render(request, "403.html", status=403)
        del request.session["just_posted"]
    record_event("receipt.opened", user=request.user, obj=txn, party_id=txn.party_id, details={"number": txn.number})
    lines = list(txn.lines.all())
    return render(request, "ledger/receipt.html", {
        "t": txn,
        "lines_in": [li for li in lines if li.direction == "in"],
        "lines_out": [li for li in lines if li.direction == "out"],
        "entries": list(txn.ledger_entries.all()),
        "balances": services.party_balances(txn.party) if request.user.is_owner and txn.party_id else None,
        "date_differs": abs((txn.operation_at - txn.recorded_at).total_seconds()) > 60,
    })


@requires("operation.list")
def operations(request):
    rows = Transaction.objects.select_related("party").all()
    get = request.GET
    if get.get("kind"):
        rows = rows.filter(kind=get["kind"])
    if get.get("user", "").isdigit():
        rows = rows.filter(author_id=int(get["user"]))
    start, end = _day(get.get("from")), _day(get.get("to"), end=True)
    if start:
        rows = rows.filter(operation_at__gte=start)
    if end:
        rows = rows.filter(operation_at__lte=end)
    page = Paginator(rows, 100).get_page(get.get("page"))
    return render(request, "ledger/list.html", {"page": page, "users": User.objects.all(),
                                                "kinds": Transaction.KINDS, "f": get})


@requires("operation.void")
@require_reconfirm
def void(request, pk):
    txn = get_object_or_404(Transaction, pk=pk)
    error = None
    if request.method == "POST":
        try:
            reversal = services.reverse_transaction(request.user, txn.pk, request.POST.get("reason", ""))
        except OperationError as exc:
            error = _message(exc, request.user)
        else:
            return redirect("receipt", pk=reversal.pk)
    return render(request, "ledger/void.html", {"t": txn, "error": error})
