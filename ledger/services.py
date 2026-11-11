"""Posting and reversing transactions. Every number is recalculated here; totals
sent by the browser are never used."""
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from audit.services import record_event
from catalog.models import Category, Origin, Purity, StockItem
from parties.models import Party
from system.services import enforce_clock

from .models import CashMovement, DocumentSequence, PartyLedgerEntry, StockMovement, Transaction, TransactionLine
from .settlement import ZERO, Line, settle


class OperationError(Exception):
    pass


class InsufficientStock(OperationError):
    """Carries the item so that only the owner's message shows quantities."""

    def __init__(self, item, available):
        super().__init__(_("Not enough stock."))
        self.item = item
        self.available = available


@dataclass
class InLine:
    origin_id: int
    purity_id: int
    gross: Decimal
    fineness: Decimal | None = None


@dataclass
class OutLine:
    origin_id: int
    purity_id: int
    category_id: int
    gross: Decimal
    pieces: int
    facon_rate: Decimal | None = None


@dataclass
class Draft:
    kind: str
    party_id: int | None
    operation_at: datetime
    in_lines: list = field(default_factory=list)
    out_lines: list = field(default_factory=list)
    money_received: Decimal = ZERO
    money_given: Decimal = ZERO
    form_token: uuid.UUID | None = None
    note: str = ""
    date_changed: bool = False


@dataclass(frozen=True)
class Calculation:
    lines: list
    gold: dict
    facon_total: Decimal
    money_difference: Decimal
    purity_by_id: dict


def _validate_shape(draft):
    if draft.money_received < ZERO or draft.money_given < ZERO:
        raise OperationError(_("Money amounts cannot be negative."))
    has_gold_in = bool(draft.in_lines)
    has_gold_out = bool(draft.out_lines)
    if draft.kind == Transaction.SALE:
        if not has_gold_in:
            raise OperationError(_("In a sale the client must always give gold."))
        if not has_gold_out and draft.money_given == ZERO:
            raise OperationError(_("Enter what the shop gives."))
    elif draft.kind == Transaction.PURCHASE:
        if not has_gold_in:
            raise OperationError(_("Enter the raw gold received."))
        if has_gold_out:
            raise OperationError(_("A purchase cannot give gold."))
    elif draft.kind == Transaction.PAYMENT:
        entries = int(has_gold_in) + int(has_gold_out) + int(draft.money_received > ZERO) + int(draft.money_given > ZERO)
        if entries != 1 or len(draft.in_lines) + len(draft.out_lines) > 1:
            raise OperationError(_("A payment must be one amount of money or one gold entry."))
    else:
        raise OperationError(_("Unknown operation."))

    for line in draft.in_lines + draft.out_lines:
        if line.gross <= ZERO:
            raise OperationError(_("Weights must be greater than zero."))
    for line in draft.out_lines:
        if line.pieces < 1:
            raise OperationError(_("Enter the number of pieces given."))

    if draft.kind == Transaction.SALE:
        rates = {}
        for line in draft.out_lines:
            if line.facon_rate is None:
                raise OperationError(_("Enter the manufacture price per gram for every item given."))
            if line.facon_rate < ZERO:
                raise OperationError(_("The manufacture price cannot be negative."))
            key = (line.origin_id, line.category_id)
            if rates.setdefault(key, line.facon_rate) != line.facon_rate:
                raise OperationError(_("Use one manufacture price per origin and category."))
    elif any(line.facon_rate is not None for line in draft.out_lines):
        raise OperationError(_("A manufacture price only applies to a sale."))


def calculate(draft):
    """Validates a draft and runs the settlement formulas. Writes nothing."""
    _validate_shape(draft)
    purity_ids = {line.purity_id for line in draft.in_lines + draft.out_lines}
    purities = Purity.objects.in_bulk(purity_ids)
    origins = Origin.objects.in_bulk({line.origin_id for line in draft.in_lines + draft.out_lines})
    if len(purities) != len(purity_ids):
        raise OperationError(_("Choose a valid purity."))
    if len(origins) != len({line.origin_id for line in draft.in_lines + draft.out_lines}):
        raise OperationError(_("Choose a valid origin."))

    lines = []
    for raw in draft.in_lines:
        fineness = raw.fineness if raw.fineness is not None else purities[raw.purity_id].fineness
        if not (ZERO < fineness <= 1000):
            raise OperationError(_("Fineness must be a number between 0 and 1000."))
        lines.append(Line("in", raw.origin_id, raw.gross, fineness))
    for out in draft.out_lines:
        lines.append(Line("out", out.origin_id, out.gross, purities[out.purity_id].fineness,
                          out.category_id, out.facon_rate))
    result = settle(lines, draft.money_received, draft.money_given)
    return Calculation(lines, result.gold, result.facon_total, result.money_difference, purities)


preview_transaction = calculate


def _next_number(year):
    row = DocumentSequence.objects.select_for_update().filter(year=year).first()
    if row is None:
        DocumentSequence.objects.get_or_create(year=year)
        row = DocumentSequence.objects.select_for_update().get(year=year)
    row.last_number += 1
    row.save(update_fields=["last_number"])
    return f"GV-{year}-{row.last_number:06d}"


def stock_totals(item_ids):
    """{item_id: (grams, pieces)} as the sum of movements."""
    rows = (StockMovement.objects.filter(stock_item_id__in=item_ids).values("stock_item_id")
            .annotate(g=Sum("grams"), p=Sum("pieces")))
    return {row["stock_item_id"]: (row["g"], row["p"]) for row in rows}


def _lock_items_and_check(movements):
    """Locks items in a fixed order, then refuses any negative result.
    movements: {item_id: (grams_delta, pieces_delta)}"""
    items = {i.pk: i for i in StockItem.objects.select_for_update().filter(pk__in=movements).order_by("pk")}
    totals = stock_totals(list(movements))
    for item_id, (grams, pieces) in movements.items():
        have_g, have_p = totals.get(item_id, (ZERO, 0))
        if have_g + grams < ZERO or have_p + pieces < 0:
            raise InsufficientStock(items[item_id], (have_g, have_p))


def _resolve_party(draft):
    party = Party.objects.filter(pk=draft.party_id, archived=False).first()
    if party is None:
        raise OperationError(_("Choose who this operation is with."))
    if draft.kind == Transaction.SALE and party.kind != Party.CLIENT:
        raise OperationError(_("A sale must be with a client."))
    if draft.kind == Transaction.PURCHASE and party.kind == Party.CLIENT:
        raise OperationError(_("A purchase must be with a supplier."))
    return party


def _raw_item(origin_id, purity_id):
    item, _created = StockItem.objects.get_or_create(kind=StockItem.RAW, category=None,
                                                     origin_id=origin_id, purity_id=purity_id)
    return item


def _ready_item(line):
    item = StockItem.objects.filter(kind=StockItem.READY, category_id=line.category_id,
                                    origin_id=line.origin_id, purity_id=line.purity_id).first()
    if item is None:
        category = Category.objects.filter(pk=line.category_id).first()
        if category is None:
            raise OperationError(_("Choose a valid category."))
        item, _created = StockItem.objects.get_or_create(
            kind=StockItem.READY, category=category, origin_id=line.origin_id, purity_id=line.purity_id)
    return item


def post_transaction(author, draft):
    """Posts a sale, purchase or payment in one database transaction.
    Posting the same form token twice returns the first transaction."""
    existing = _already_posted(draft)
    if existing is not None:
        return existing
    enforce_clock(author)
    calc = calculate(draft)
    party = _resolve_party(draft)

    try:
        with transaction.atomic():
            return _write(author, draft, calc, party)
    except IntegrityError:
        existing = _already_posted(draft)
        if existing is not None:
            return existing
        raise


def _already_posted(draft):
    if draft.form_token is None:
        return None
    return Transaction.objects.filter(form_token=draft.form_token).first()


def _write(author, draft, calc, party):
    # Decide the stock item for every line, then lock them all.
    resolved = []
    for raw, line in zip(draft.in_lines, calc.lines[:len(draft.in_lines)]):
        resolved.append((_raw_item(raw.origin_id, raw.purity_id), line, 0))
    for out, line in zip(draft.out_lines, calc.lines[len(draft.in_lines):]):
        resolved.append((_ready_item(out), line, out.pieces))

    deltas = defaultdict(lambda: (ZERO, 0))
    for item, line, pieces in resolved:
        sign = 1 if line.direction == "in" else -1
        grams, count = deltas[item.pk]
        deltas[item.pk] = (grams + sign * line.gross, count + sign * pieces)
    _lock_items_and_check(deltas)

    now = timezone.now()
    txn = Transaction.objects.create(
        number=_next_number(now.astimezone(timezone.get_default_timezone()).year),
        kind=draft.kind, party=party, operation_at=draft.operation_at, recorded_at=now,
        author=author, author_name=author.display_name,
        money_received=draft.money_received, money_given=draft.money_given,
        facon_total=calc.facon_total, money_difference=calc.money_difference,
        form_token=draft.form_token, note=draft.note,
    )
    for item, line, pieces in resolved:
        sign = 1 if line.direction == "in" else -1
        TransactionLine.objects.create(
            transaction=txn, direction=line.direction, stock_item=item, gross_grams=line.gross,
            fineness=line.fineness, fine_grams=line.fine, pieces=pieces, facon_rate=line.facon_rate)
        StockMovement.objects.create(transaction=txn, stock_item=item, grams=sign * line.gross, pieces=sign * pieces)
    for origin_id, fine in calc.gold.items():
        PartyLedgerEntry.objects.create(transaction=txn, party=party, asset=PartyLedgerEntry.GOLD,
                                        origin_id=origin_id, fine_grams=fine)
    if calc.money_difference != ZERO:
        PartyLedgerEntry.objects.create(transaction=txn, party=party, asset=PartyLedgerEntry.MONEY_ASSET,
                                        amount_da=calc.money_difference)
    cash = draft.money_received - draft.money_given
    if cash != ZERO:
        CashMovement.objects.create(transaction=txn, amount_da=cash)

    record_event(f"transaction.{draft.kind}", user=author, obj=txn, party_id=party.pk, details={
        "number": txn.number,
        "operation_at": draft.operation_at,
        "lines": [{"direction": line.direction, "item": item.pk, "gross": line.gross,
                   "fineness": line.fineness, "pieces": pieces, "facon_rate": line.facon_rate}
                  for item, line, pieces in resolved],
        "money_received": draft.money_received,
        "money_given": draft.money_given,
        "facon_total": calc.facon_total,
        "money_difference": calc.money_difference,
        "gold_difference": {str(k): v for k, v in calc.gold.items()},
    })
    if draft.date_changed:
        record_event("transaction.date_changed", user=author, obj=txn, party_id=party.pk,
                     details={"entered": draft.operation_at, "real": now})
    return txn


def reverse_transaction(actor, txn_id, reason):
    """Void by mirror entry. The original stays visible and unchanged."""
    reason = (reason or "").strip()
    if not reason:
        raise OperationError(_("A written reason is required."))
    original = Transaction.objects.filter(pk=txn_id).first()
    if original is None:
        raise OperationError(_("Operation not found."))
    if original.kind == Transaction.REVERSAL:
        raise OperationError(_("A reversal cannot be reversed."))
    if Transaction.objects.filter(reversal_of=original).exists():
        raise OperationError(_("This operation has already been voided."))
    try:
        with transaction.atomic():
            return _write_reversal(actor, original, reason)
    except IntegrityError:
        raise OperationError(_("This operation has already been voided.")) from None


def _write_reversal(actor, original, reason):
    movements = list(original.stock_movements.all())
    deltas = defaultdict(lambda: (ZERO, 0))
    for m in movements:
        grams, pieces = deltas[m.stock_item_id]
        deltas[m.stock_item_id] = (grams - m.grams, pieces - m.pieces)
    _lock_items_and_check(deltas)

    now = timezone.now()
    txn = Transaction.objects.create(
        number=_next_number(now.astimezone(timezone.get_default_timezone()).year),
        kind=Transaction.REVERSAL, party=original.party, operation_at=now, recorded_at=now,
        author=actor, author_name=actor.display_name, reversal_of=original,
        money_received=original.money_given, money_given=original.money_received,
        facon_total=-original.facon_total, money_difference=-original.money_difference, note=reason,
    )
    for line in original.lines.all():
        TransactionLine.objects.create(
            transaction=txn, direction="in" if line.direction == "out" else "out", stock_item=line.stock_item,
            gross_grams=line.gross_grams, fineness=line.fineness, fine_grams=line.fine_grams,
            pieces=line.pieces, facon_rate=line.facon_rate)
    for m in movements:
        StockMovement.objects.create(transaction=txn, stock_item=m.stock_item, grams=-m.grams, pieces=-m.pieces)
    for e in original.ledger_entries.all():
        PartyLedgerEntry.objects.create(
            transaction=txn, party=e.party, asset=e.asset, origin=e.origin,
            amount_da=None if e.amount_da is None else -e.amount_da,
            fine_grams=None if e.fine_grams is None else -e.fine_grams)
    for c in original.cash_movements.all():
        CashMovement.objects.create(transaction=txn, amount_da=-c.amount_da)
    record_event("transaction.reversal", user=actor, obj=txn, party_id=original.party_id,
                 details={"number": txn.number, "reverses": original.number, "reason": reason})
    return txn


def post_adjustment(actor, item, grams_delta, pieces_delta, reason, operation_at=None):
    """Owner-only stock change, also used to enter opening stock."""
    reason = (reason or "").strip()
    if not reason:
        raise OperationError(_("A written reason is required."))
    if grams_delta == ZERO and pieces_delta == 0:
        raise OperationError(_("Enter a weight or a number of pieces."))
    with transaction.atomic():
        _lock_items_and_check({item.pk: (grams_delta, pieces_delta)})
        now = timezone.now()
        txn = Transaction.objects.create(
            number=_next_number(now.astimezone(timezone.get_default_timezone()).year),
            kind=Transaction.ADJUSTMENT, operation_at=operation_at or now, recorded_at=now,
            author=actor, author_name=actor.display_name, note=reason)
        StockMovement.objects.create(transaction=txn, stock_item=item, grams=grams_delta, pieces=pieces_delta)
        record_event("transaction.adjustment", user=actor, obj=txn, details={
            "number": txn.number, "item": item.pk, "grams": grams_delta, "pieces": pieces_delta, "reason": reason})
    return txn


def party_balances(party):
    """{'money': Decimal, 'gold': [(origin, fine_grams), ...]}, non-zero gold only."""
    entries = PartyLedgerEntry.objects.filter(party=party)
    money = entries.filter(asset=PartyLedgerEntry.MONEY_ASSET).aggregate(s=Sum("amount_da"))["s"] or ZERO
    gold_rows = (entries.filter(asset=PartyLedgerEntry.GOLD).values("origin_id").annotate(s=Sum("fine_grams")))
    origins = Origin.objects.in_bulk([r["origin_id"] for r in gold_rows])
    gold = [(origins[r["origin_id"]], r["s"]) for r in gold_rows if r["s"] != ZERO]
    return {"money": money, "gold": gold}
