"""Debts and alerts, always computed from the ledger when asked for."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Max, Sum
from django.utils import timezone

from catalog.models import Origin
from ledger.models import CashMovement, PartyLedgerEntry, Transaction
from parties.models import Party

DEFAULT_ALERT_DAYS = 15


def debt_rows():
    """One row per party, asset and origin, non-zero only."""
    grouped = (PartyLedgerEntry.objects
               .values("party_id", "party__name", "party__phone", "party__kind", "asset", "origin_id")
               .annotate(money=Sum("amount_da"), gold=Sum("fine_grams")))
    origins = Origin.objects.in_bulk()
    rows = []
    for row in grouped:
        value = row["money"] if row["asset"] == "money" else row["gold"]
        if value:
            rows.append({
                "party_id": row["party_id"], "name": row["party__name"], "phone": row["party__phone"] or "",
                "kind": row["party__kind"], "asset": row["asset"], "origin_id": row["origin_id"],
                "origin": origins[row["origin_id"]].name if row["origin_id"] else "",
                "value": value, "to_me": value > 0,
            })
    rows.sort(key=lambda r: (r["name"], r["asset"], r["origin"]))
    return rows


def totals(rows):
    money = {"to_me": Decimal(0), "by_me": Decimal(0)}
    gold = defaultdict(lambda: {"to_me": Decimal(0), "by_me": Decimal(0)})
    for row in rows:
        side = "to_me" if row["to_me"] else "by_me"
        if row["asset"] == "money":
            money[side] += abs(row["value"])
        else:
            gold[row["origin"]][side] += abs(row["value"])
    return {"money": money, "gold": dict(gold)}


def alerts():
    """Debts with no recent payment, and clients with no recent operation."""
    now = timezone.now()
    last_any = dict(Transaction.objects.exclude(party=None).values_list("party_id").annotate(m=Max("operation_at")))
    last_paid = dict(Transaction.objects.filter(kind=Transaction.PAYMENT).values_list("party_id")
                     .annotate(m=Max("operation_at")))
    in_debt = {row["party_id"] for row in debt_rows()}
    debts, inactive = [], []
    for party in Party.objects.filter(archived=False, pk__in=set(last_any)):
        days = party.alert_days or DEFAULT_ALERT_DAYS
        limit = timedelta(days=days)
        if party.pk in in_debt:
            since = last_paid.get(party.pk) or last_any[party.pk]
            if now - since > limit:
                debts.append({"party": party, "days": (now - since).days})
        if now - last_any[party.pk] > limit:
            inactive.append({"party": party, "days": (now - last_any[party.pk]).days})
    return {"debts": debts, "inactive": inactive}


def drawer():
    return CashMovement.objects.aggregate(s=Sum("amount_da"))["s"] or Decimal(0)
