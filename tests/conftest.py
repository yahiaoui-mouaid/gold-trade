"""All database tests run on real PostgreSQL as the goldvolt_app role, so a
missing or excessive grant shows up as a test failure."""
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import connection

from accounts.models import User
from catalog.models import Category, Origin, Purity, StockItem
from ledger.services import post_adjustment
from parties.models import Party
from parties.services import normalize_name


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("apply_grants", verbosity=0)


@pytest.fixture(autouse=True)
def _run_as_app_role(request):
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    request.getfixturevalue("db")
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE goldvolt_app")
    yield


class World:
    pass


@pytest.fixture
def world(db):
    w = World()
    w.owner = User.objects.create_user("owner", "correct-horse-battery", User.OWNER, "The Owner")
    w.salesman = User.objects.create_user("sam", "salesman-pass", User.SALESMAN, "Sam")
    w.origin_a = Origin.objects.create(name_ar="إيطاليا", name_fr="Italie")
    w.origin_b = Origin.objects.create(name_ar="تركيا", name_fr="Turquie")
    w.rings = Category.objects.create(name_ar="خواتم", name_fr="Bagues")
    w.chains = Category.objects.create(name_ar="سلاسل", name_fr="Chaînes")
    w.p24 = Purity.objects.get(label="24k")
    w.p18 = Purity.objects.get(label="18k")
    w.client = Party.objects.create(kind=Party.CLIENT, name="أحمد", name_search=normalize_name("أحمد"),
                                    phone="0550000001", created_by=w.owner)
    w.supplier = Party.objects.create(kind=Party.SUPPLIER, name="Fournisseur", name_search="fournisseur",
                                      phone="0550000002", created_by=w.owner)
    w.rings_b = StockItem.objects.create(kind=StockItem.READY, category=w.rings, origin=w.origin_b, purity=w.p18)
    post_adjustment(w.owner, w.rings_b, Decimal("1000.000"), 100, "opening stock")
    return w
