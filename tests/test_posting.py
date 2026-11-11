import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.utils import timezone
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from audit.models import AuditEvent
from audit.services import verify_chain
from catalog.models import StockItem
from ledger.models import CashMovement, PartyLedgerEntry, Transaction
from ledger.services import (
    Draft,
    InLine,
    InsufficientStock,
    OperationError,
    OutLine,
    party_balances,
    post_transaction,
    reverse_transaction,
    stock_totals,
)
from system.services import ClockBlocked, confirm_clock

pytestmark = pytest.mark.django_db


def sale(w, **kw):
    defaults = dict(
        kind=Transaction.SALE, party_id=w.client.pk, operation_at=timezone.now(),
        in_lines=[InLine(w.origin_a.pk, w.p24.pk, D("200.000"))],
        out_lines=[OutLine(w.origin_b.pk, w.p18.pk, w.rings.pk, D("250.000"), 10, D("900"))],
        money_received=D("200000"), form_token=uuid.uuid4(),
    )
    defaults.update(kw)
    return Draft(**defaults)


def test_sale_writes_separate_balances_per_origin(world):
    txn = post_transaction(world.salesman, sale(world))
    balances = party_balances(world.client)
    assert balances["money"] == D("25000")
    assert dict((o.pk, g) for o, g in balances["gold"]) == {world.origin_a.pk: D("-199.98"), world.origin_b.pk: D("187.5")}
    assert txn.number.startswith("GV-")
    assert txn.facon_total == D("225000")
    assert stock_totals([world.rings_b.pk])[world.rings_b.pk] == (D("750.000"), 90)
    raw = StockItem.objects.get(kind=StockItem.RAW, origin=world.origin_a, purity=world.p24)
    assert stock_totals([raw.pk])[raw.pk][0] == D("200.000")
    assert CashMovement.objects.get(transaction=txn).amount_da == D("200000")


def test_sale_requires_gold_from_the_client(world):
    with pytest.raises(OperationError):
        post_transaction(world.salesman, sale(world, in_lines=[]))


def test_supplier_purchase_keeps_two_balances(world):
    post_transaction(world.salesman, Draft(
        kind=Transaction.PURCHASE, party_id=world.supplier.pk, operation_at=timezone.now(),
        in_lines=[InLine(world.origin_a.pk, world.p24.pk, D("100.000"))], money_given=D("1000000")))
    balances = party_balances(world.supplier)
    assert balances["money"] == D("1000000")
    assert balances["gold"][0][1] == D("-99.99")


def test_facon_must_be_one_rate_per_origin_and_category(world):
    out = [OutLine(world.origin_b.pk, world.p18.pk, world.rings.pk, D("1"), 1, D("900")),
           OutLine(world.origin_b.pk, world.p18.pk, world.rings.pk, D("1"), 1, D("800"))]
    with pytest.raises(OperationError):
        post_transaction(world.owner, sale(world, out_lines=out))


def test_not_enough_stock_is_refused_and_writes_nothing(world):
    before = Transaction.objects.count()
    with pytest.raises(InsufficientStock):
        post_transaction(world.salesman, sale(world, out_lines=[
            OutLine(world.origin_b.pk, world.p18.pk, world.rings.pk, D("1000.001"), 1, D("900"))]))
    assert Transaction.objects.count() == before


def test_same_form_token_posts_once(world):
    token = uuid.uuid4()
    first = post_transaction(world.salesman, sale(world, form_token=token))
    second = post_transaction(world.salesman, sale(world, form_token=token))
    assert first.pk == second.pk
    assert Transaction.objects.filter(kind=Transaction.SALE).count() == 1


def test_receipt_numbers_have_no_gaps_after_a_refusal(world):
    first = post_transaction(world.owner, sale(world))
    with pytest.raises(InsufficientStock):
        post_transaction(world.owner, sale(world, out_lines=[
            OutLine(world.origin_b.pk, world.p18.pk, world.rings.pk, D("9999"), 1, D("0"))]))
    second = post_transaction(world.owner, sale(world))
    assert int(second.number.rsplit("-", 1)[1]) == int(first.number.rsplit("-", 1)[1]) + 1


def test_entered_date_is_separate_from_real_time_and_logged(world):
    back = timezone.now() - timedelta(days=3)
    txn = post_transaction(world.salesman, sale(world, operation_at=back, date_changed=True))
    assert txn.operation_at == back
    assert abs(txn.recorded_at - timezone.now()) < timedelta(seconds=30)
    event = AuditEvent.objects.get(action="transaction.date_changed", object_id=str(txn.pk))
    assert abs(event.at - timezone.now()) < timedelta(seconds=30)


def test_money_payment_reduces_debt(world):
    post_transaction(world.salesman, sale(world))
    post_transaction(world.salesman, Draft(kind=Transaction.PAYMENT, party_id=world.client.pk,
                                           operation_at=timezone.now(), money_received=D("50")))
    assert party_balances(world.client)["money"] == D("24950")


def test_gold_payment_changes_only_that_origin(world):
    post_transaction(world.salesman, sale(world))
    post_transaction(world.salesman, Draft(
        kind=Transaction.PAYMENT, party_id=world.client.pk, operation_at=timezone.now(),
        in_lines=[InLine(world.origin_b.pk, world.p18.pk, D("100.000"))]))
    gold = dict((o.pk, g) for o, g in party_balances(world.client)["gold"])
    assert gold == {world.origin_a.pk: D("-199.98"), world.origin_b.pk: D("112.5")}


def test_gold_given_as_payment_needs_pieces(world):
    with pytest.raises(OperationError):
        post_transaction(world.owner, Draft(
            kind=Transaction.PAYMENT, party_id=world.client.pk, operation_at=timezone.now(),
            out_lines=[OutLine(world.origin_b.pk, world.p18.pk, world.rings.pk, D("1"), 0)]))


def test_reversal_needs_a_reason_and_cannot_repeat(world):
    txn = post_transaction(world.owner, sale(world))
    with pytest.raises(OperationError):
        reverse_transaction(world.owner, txn.pk, "  ")
    reverse_transaction(world.owner, txn.pk, "wrong weight")
    with pytest.raises(OperationError):
        reverse_transaction(world.owner, txn.pk, "again")


def test_salesman_blocked_when_clock_jumped_until_owner_confirms(world):
    post_transaction(world.owner, sale(world))
    Transaction.objects.all()  # recorded_at is append-only, so move the clock instead
    later = timezone.now() + timedelta(days=2)
    import system.services as ss

    original = ss.timezone.now
    ss.timezone.now = lambda: later
    try:
        with pytest.raises(ClockBlocked):
            post_transaction(world.salesman, sale(world))
        assert AuditEvent.objects.filter(action="clock.warning").exists()
        confirm_clock(world.owner)
        post_transaction(world.salesman, sale(world))
    finally:
        ss.timezone.now = original


amounts = st.decimals(min_value=D("0.001"), max_value=D("9.999"), places=3)
rates = st.decimals(min_value=D("0"), max_value=D("5000"), places=2)
cash = st.decimals(min_value=D("0"), max_value=D("100000"), places=2)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(amounts, amounts, rates, cash)
def test_a_transaction_plus_its_reversal_sums_to_zero(world, grams_in, grams_out, rate, received):
    with transaction.atomic():
        before = stock_totals([world.rings_b.pk])[world.rings_b.pk]
        txn = post_transaction(world.owner, sale(
            world,
            in_lines=[InLine(world.origin_a.pk, world.p24.pk, grams_in)],
            out_lines=[OutLine(world.origin_b.pk, world.p18.pk, world.rings.pk, grams_out, 1, rate)],
            money_received=received))
        reverse_transaction(world.owner, txn.pk, "test")
        balances = party_balances(world.client)
        assert balances["money"] == 0
        assert balances["gold"] == []
        assert stock_totals([world.rings_b.pk])[world.rings_b.pk] == before
        assert sum(c.amount_da for c in CashMovement.objects.all()) == 0
        assert not PartyLedgerEntry.objects.filter(transaction=txn).exclude(party=world.client).exists()
        assert verify_chain().ok
        transaction.set_rollback(True)
