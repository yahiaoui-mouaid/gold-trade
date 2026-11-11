"""The real screens, through the real form fields."""
import uuid

import pytest
from django.test import Client
from django.utils import timezone

from audit.models import AuditEvent
from ledger.models import Transaction
from ledger.services import party_balances
from parties.models import Party

pytestmark = pytest.mark.django_db


@pytest.fixture
def sam(world):
    client = Client()
    client.force_login(world.salesman, backend="django.contrib.auth.backends.ModelBackend")
    return client


def sale_form(w, **over):
    data = {
        "kind": "sale", "party": w.client.pk, "form_token": str(uuid.uuid4()),
        "operation_at": "", "operation_at_default": "",
        "in_origin": w.origin_a.pk, "in_purity": w.p24.pk, "in_grams": "200.000", "in_fineness": "",
        "out_category": w.rings.pk, "out_origin": w.origin_b.pk, "out_purity": w.p18.pk,
        "out_grams": "250.000", "out_pieces": "10", "out_facon": "900",
        "money_received": "200000", "money_given": "",
    }
    data.update(over)
    return data


def test_preview_shows_each_origin_and_saves_nothing(sam, world):
    before = Transaction.objects.count()
    page = sam.post("/operations/preview/", sale_form(world), headers={"HX-Request": "true"})
    body = page.content.decode()
    assert "199.98" in body and "187.5" in body and "225,000" in body and "25,000" in body
    assert Transaction.objects.count() == before


def test_post_from_the_form_then_receipt(sam, world):
    response = sam.post("/operations/new/sale/", sale_form(world))
    assert response.status_code == 302
    receipt = sam.get(response.headers["Location"])
    assert receipt.status_code == 200
    assert party_balances(world.client)["money"] == 25000


def test_browser_totals_are_ignored(sam, world):
    sam.post("/operations/new/sale/", sale_form(world, facon_total="1", money_difference="0"))
    assert party_balances(world.client)["money"] == 25000


def test_salesman_stock_refusal_shows_no_quantity_and_is_logged(sam, world):
    page = sam.post("/operations/new/sale/", sale_form(world, out_grams="5000"))
    body = page.content.decode()
    assert page.status_code == 200 and "1000" not in body.split("role=\"alert\"")[1].split("</p>")[0]
    assert AuditEvent.objects.filter(action="operation.refused").exists()


def test_date_change_is_detected_from_the_form(sam, world):
    sam.post("/operations/new/sale/", sale_form(
        world, operation_at="2026-01-05T10:00", operation_at_default="2026-11-10T09:00"))
    txn = Transaction.objects.get(kind="sale")
    assert timezone.localtime(txn.operation_at).strftime("%Y-%m-%d %H:%M") == "2026-01-05 10:00"
    assert AuditEvent.objects.filter(action="transaction.date_changed").exists()


def test_quick_add_new_person_with_name_and_phone(sam):
    page = sam.post("/parties/quick-add/", {"purpose": "sale", "quick_name": "Karim", "quick_phone": "0661 22 33 44"})
    assert "Karim" in page.content.decode()
    assert Party.objects.get(phone="0661223344").kind == Party.CLIENT


def test_quick_add_requires_a_phone(sam):
    sam.post("/parties/quick-add/", {"purpose": "sale", "quick_name": "Karim", "quick_phone": ""})
    assert not Party.objects.filter(name="Karim").exists()


def test_quick_add_existing_phone_selects_that_person(sam, world):
    before = Party.objects.count()
    page = sam.post("/parties/quick-add/", {"purpose": "sale", "quick_name": "Other", "quick_phone": world.client.phone})
    body = page.content.decode()
    assert Party.objects.count() == before
    assert "checked" in body and world.client.name in body


def test_gold_payment_form(sam, world):
    response = sam.post("/operations/new/payment/", {
        "party": world.client.pk, "direction": "out", "asset": "gold", "origin": world.origin_b.pk,
        "purity": world.p18.pk, "category": world.rings.pk, "grams": "10", "pieces": "2",
        "form_token": str(uuid.uuid4()), "operation_at": "", "operation_at_default": ""})
    assert response.status_code == 302
    assert party_balances(world.client)["gold"][0][1] == 7.5
