"""Turns raw form text into exact values. Floats are never involved."""
import re
import uuid
from datetime import datetime
from decimal import Decimal
from itertools import zip_longest

from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Transaction
from .services import Draft, InLine, OutLine
from .settlement import ZERO

_WEIGHT = re.compile(r"^\d{1,9}(\.\d{1,3})?$")
_MONEY = re.compile(r"^\d{1,12}(\.\d{1,2})?$")
_FINENESS = re.compile(r"^\d{1,4}(\.\d)?$")
_SIGNED_WEIGHT = re.compile(r"^-?\d{1,9}(\.\d{1,3})?$")


class FormError(Exception):
    pass


def _decimal(raw, pattern):
    text = (raw or "").strip().replace(",", ".")
    if not pattern.match(text):
        raise FormError(_("Check the numbers you entered."))
    return Decimal(text)


def weight(raw):
    return _decimal(raw, _WEIGHT)


def signed_weight(raw):
    return _decimal(raw, _SIGNED_WEIGHT)


def money(raw):
    return ZERO if not (raw or "").strip() else _decimal(raw, _MONEY)


def _pk(raw, message):
    text = (raw or "").strip()
    if not text.isdigit():
        raise FormError(message)
    return int(text)


def pieces(raw):
    text = (raw or "").strip()
    if not text.isdigit():
        raise FormError(_("Enter the number of pieces given."))
    return int(text)


def in_rows(post):
    return [
        {"origin": o, "purity": p, "grams": g, "fineness": f}
        for o, p, g, f in zip_longest(post.getlist("in_origin"), post.getlist("in_purity"),
                                      post.getlist("in_grams"), post.getlist("in_fineness"), fillvalue="")
    ]


def out_rows(post):
    return [
        {"category": c, "origin": o, "purity": p, "grams": g, "pieces": n, "facon": f}
        for c, o, p, g, n, f in zip_longest(
            post.getlist("out_category"), post.getlist("out_origin"), post.getlist("out_purity"),
            post.getlist("out_grams"), post.getlist("out_pieces"), post.getlist("out_facon"), fillvalue="")
    ]


def _in_line(origin, purity, grams, fineness):
    return InLine(
        origin_id=_pk(origin, _("Choose a valid origin.")),
        purity_id=_pk(purity, _("Choose a valid purity.")),
        gross=weight(grams),
        fineness=_decimal(fineness, _FINENESS) if (fineness or "").strip() else None,
    )


def _out_line(category, origin, purity, grams, count, facon_rate):
    return OutLine(
        category_id=_pk(category, _("Choose a valid category.")),
        origin_id=_pk(origin, _("Choose a valid origin.")),
        purity_id=_pk(purity, _("Choose a valid purity.")),
        gross=weight(grams),
        pieces=pieces(count),
        facon_rate=facon_rate,
    )


def read_operation_at(post):
    """Returns (when, date_changed). Blank means right now."""
    raw = (post.get("operation_at") or "").strip()
    if not raw:
        return timezone.now(), False
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise FormError(_("Check the date.")) from None
    return timezone.make_aware(parsed), raw != (post.get("operation_at_default") or "").strip()


def _token(post):
    try:
        return uuid.UUID(post.get("form_token", ""))
    except ValueError:
        return None


def _party(post):
    raw = (post.get("party") or "").strip()
    return int(raw) if raw.isdigit() else None


def read_draft(post, kind):
    """A sale or purchase, from the operation screen."""
    when, changed = read_operation_at(post)
    lines_in = [_in_line(r["origin"], r["purity"], r["grams"], r["fineness"])
                for r in in_rows(post) if r["grams"].strip()]
    lines_out = []
    if kind == Transaction.SALE:
        for r in out_rows(post):
            if r["grams"].strip():
                rate = money(r["facon"]) if r["facon"].strip() else None
                lines_out.append(_out_line(r["category"], r["origin"], r["purity"], r["grams"], r["pieces"], rate))
    return Draft(kind=kind, party_id=_party(post), operation_at=when, in_lines=lines_in, out_lines=lines_out,
                 money_received=money(post.get("money_received")), money_given=money(post.get("money_given")),
                 form_token=_token(post), note=(post.get("note") or "").strip()[:500], date_changed=changed)


def read_payment(post):
    """One amount of money or one gold entry, in either direction."""
    when, changed = read_operation_at(post)
    direction = post.get("direction")
    asset = post.get("asset")
    if direction not in ("in", "out") or asset not in ("money", "gold"):
        raise FormError(_("Choose the direction and the type of payment."))
    draft = Draft(kind=Transaction.PAYMENT, party_id=_party(post), operation_at=when, form_token=_token(post),
                  note=(post.get("note") or "").strip()[:500], date_changed=changed)
    if asset == "money":
        amount = money(post.get("amount"))
        if amount <= ZERO:
            raise FormError(_("Enter the amount."))
        if direction == "in":
            draft.money_received = amount
        else:
            draft.money_given = amount
    elif direction == "in":
        draft.in_lines = [_in_line(post.get("origin"), post.get("purity"), post.get("grams"), post.get("fineness"))]
    else:
        draft.out_lines = [_out_line(post.get("category"), post.get("origin"), post.get("purity"),
                                     post.get("grams"), post.get("pieces"), None)]
    return draft
