"""Every URL, tried as owner, salesman and logged-out visitor (B8, B13)."""
import time

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver

from accounts.permissions import PUBLIC, SALESMAN_PERMISSIONS, AUTHENTICATED

pytestmark = pytest.mark.django_db

FILL = {"pk": 1, "kind": "category"}


def all_urls():
    def walk(patterns, prefix=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                yield prefix + str(pattern.pattern), pattern.callback
    for route, view in walk(get_resolver().url_patterns):
        path = "/" + route
        for name, value in FILL.items():
            path = path.replace(f"<int:{name}>", str(value)).replace(f"<str:{name}>", str(value))
        yield path, view


ALL = list(all_urls())


@pytest.fixture
def owner_client(world):
    client = Client()
    client.force_login(world.owner, backend="django.contrib.auth.backends.ModelBackend")
    session = client.session
    session["confirmed_at"] = time.time()
    session["last_seen"] = time.time()
    session.save()
    return client


@pytest.fixture
def salesman_client(world):
    client = Client()
    client.force_login(world.salesman, backend="django.contrib.auth.backends.ModelBackend")
    return client


def test_every_view_declares_a_permission():
    undeclared = [path for path, view in ALL if not getattr(view, "gv_permission", None)]
    assert not undeclared, undeclared


@pytest.mark.parametrize("path,view", ALL, ids=[p for p, _v in ALL])
def test_logged_out_visitor_never_reaches_a_protected_page(world, path, view):
    if view.gv_permission == PUBLIC:
        return
    response = Client().get(path)
    assert response.status_code == 302 and response["Location"] == "/login/"


@pytest.mark.parametrize("path,view", ALL, ids=[p for p, _v in ALL])
def test_salesman_only_reaches_what_is_allowed(salesman_client, path, view):
    permission = view.gv_permission
    if permission == PUBLIC or permission == AUTHENTICATED or permission in SALESMAN_PERMISSIONS:
        return
    assert salesman_client.get(path).status_code == 403
    assert salesman_client.post(path, {}).status_code == 403


def test_salesman_permissions_are_exactly_the_agreed_list():
    assert SALESMAN_PERMISSIONS == {"operation.post", "operation.receipt", "party.search", "party.add_basic"}


@pytest.mark.parametrize("path", ["/dashboard/", "/debts/", "/stock/", "/stock/movements/", "/parties/", "/activity/",
                                  "/catalog/", "/operations/", "/users/"])
def test_owner_pages_open(owner_client, path):
    assert owner_client.get(path).status_code == 200


def test_salesman_search_returns_names_and_phones_only(salesman_client, world):
    body = salesman_client.get("/parties/search/", {"q": "احمد", "for": "sale"}).content.decode()
    assert "أحمد" in body and world.client.phone in body
    assert "balance" not in body.lower()
    assert body.count("<label>") == 1


def test_salesman_receipt_opens_once_and_shows_no_balance(salesman_client, world):
    from decimal import Decimal as D

    from django.utils import timezone

    from ledger.models import Transaction
    from ledger.services import Draft, InLine, post_transaction

    txn = post_transaction(world.salesman, Draft(
        kind=Transaction.PAYMENT, party_id=world.client.pk, operation_at=timezone.now(), money_received=D("10")))
    assert salesman_client.get(f"/operations/{txn.pk}/receipt/").status_code == 403
    session = salesman_client.session
    session["just_posted"] = txn.pk
    session.save()
    first = salesman_client.get(f"/operations/{txn.pk}/receipt/")
    assert first.status_code == 200
    assert first.context["balances"] is None
    assert salesman_client.get(f"/operations/{txn.pk}/receipt/").status_code == 403
    assert InLine  # imported for symmetry with other tests
