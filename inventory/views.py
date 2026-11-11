from collections import defaultdict
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import DecimalField, IntegerField, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from accounts.models import User
from accounts.permissions import requires
from catalog.models import Category, Origin, Purity, StockItem
from ledger import forms
from ledger.forms import FormError
from ledger.models import StockMovement
from ledger.services import OperationError, post_adjustment
from parties.models import Party
from parties.views import _day

ZERO_GRAMS = Value(Decimal(0), output_field=DecimalField(max_digits=18, decimal_places=3))


def _digit(get, key):
    value = get.get(key, "")
    return int(value) if value.isdigit() else None


@requires("stock.view")
def stock(request):
    get = request.GET
    rows = StockItem.objects.select_related("category", "origin", "purity").annotate(
        grams=Coalesce(Sum("movements__grams"), ZERO_GRAMS),
        pieces=Coalesce(Sum("movements__pieces"), Value(0, output_field=IntegerField())),
    )
    if get.get("kind"):
        rows = rows.filter(kind=get["kind"])
    for key in ("origin", "category", "purity"):
        if _digit(get, key) is not None:
            rows = rows.filter(**{f"{key}_id": _digit(get, key)})
    rows = list(rows.order_by("kind", "category_id", "origin_id", "purity_id"))
    if not get.get("zero"):
        rows = [r for r in rows if r.grams or r.pieces]
    by_category = defaultdict(lambda: {"grams": Decimal(0), "pieces": 0})
    for row in rows:
        if row.category_id:
            by_category[row.category.name]["grams"] += row.grams
            by_category[row.category.name]["pieces"] += row.pieces
    return render(request, "inventory/stock.html", {
        "rows": rows, "by_category": dict(by_category), "origins": Origin.objects.all(),
        "categories": Category.objects.all(), "purities": Purity.objects.all(),
        "kinds": StockItem.KINDS, "f": get,
    })


@requires("stock.view")
def movements(request):
    get = request.GET
    rows = StockMovement.objects.select_related(
        "transaction__party", "stock_item__category", "stock_item__origin", "stock_item__purity"
    ).order_by("-transaction__operation_at", "-id")
    if _digit(get, "user") is not None:
        rows = rows.filter(transaction__author_id=_digit(get, "user"))
    if get.get("party_kind"):
        rows = rows.filter(transaction__party__kind=get["party_kind"])
    if _digit(get, "party") is not None:
        rows = rows.filter(transaction__party_id=_digit(get, "party"))
    if _digit(get, "origin") is not None:
        rows = rows.filter(stock_item__origin_id=_digit(get, "origin"))
    if _digit(get, "category") is not None:
        rows = rows.filter(stock_item__category_id=_digit(get, "category"))
    start, end = _day(get.get("from")), _day(get.get("to"), end=True)
    if start:
        rows = rows.filter(transaction__operation_at__gte=start)
    if end:
        rows = rows.filter(transaction__operation_at__lte=end)
    page = Paginator(rows, 100).get_page(get.get("page"))
    return render(request, "inventory/movements.html", {
        "page": page, "users": User.objects.all(), "origins": Origin.objects.all(),
        "categories": Category.objects.all(), "parties": Party.objects.filter(archived=False)[:500],
        "party_kinds": Party.KINDS, "f": get,
    })


@requires("stock.adjust")
def adjust(request):
    error = None
    if request.method == "POST":
        post = request.POST
        try:
            kind = post.get("kind")
            if kind not in dict(StockItem.KINDS):
                raise FormError(_("Check the numbers you entered."))
            origin = Origin.objects.filter(pk=post.get("origin") or 0).first()
            purity = Purity.objects.filter(pk=post.get("purity") or 0).first()
            category = Category.objects.filter(pk=post.get("category") or 0).first()
            if origin is None:
                raise FormError(_("Choose a valid origin."))
            if purity is None:
                raise FormError(_("Choose a valid purity."))
            if kind == StockItem.READY and category is None:
                raise FormError(_("Choose a valid category."))
            grams = forms.signed_weight(post.get("grams") or "0")
            raw_pieces = (post.get("pieces") or "0").strip()
            if not raw_pieces.lstrip("-").isdigit():
                raise FormError(_("Check the numbers you entered."))
            item, _created = StockItem.objects.get_or_create(
                kind=kind, category=category if kind == StockItem.READY else None, origin=origin, purity=purity)
            when, _changed = forms.read_operation_at(post)
            post_adjustment(request.user, item, grams, int(raw_pieces), post.get("reason"), when)
        except (FormError, OperationError) as exc:
            error = str(exc)
        else:
            return redirect("stock")
    return render(request, "inventory/adjust.html", {
        "origins": Origin.objects.filter(disabled=False), "purities": Purity.objects.filter(disabled=False),
        "categories": Category.objects.filter(disabled=False), "kinds": StockItem.KINDS, "error": error,
    })
