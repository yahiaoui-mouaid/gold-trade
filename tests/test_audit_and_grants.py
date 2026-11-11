"""F0: the log cannot be changed, and the app role cannot rewrite history."""
import pytest
from django.db import DatabaseError, connection, transaction

from audit.models import AuditEvent, AuditHead
from audit.services import record_event, verify_chain
from catalog.services import CatalogError, delete_category
from ledger.models import PartyLedgerEntry, StockMovement, Transaction

pytestmark = pytest.mark.django_db


def _raises_db_error(sql):
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)


def test_chain_verifies(world):
    record_event("test.one", user=world.owner, details={"a": "مرحبا"})
    assert verify_chain().ok


def test_app_role_cannot_change_or_delete_the_log(world):
    record_event("test.one", user=world.owner)
    _raises_db_error("UPDATE audit_auditevent SET action = 'x'")
    _raises_db_error("DELETE FROM audit_auditevent")
    _raises_db_error("TRUNCATE audit_auditevent")


def test_even_the_owner_role_cannot_change_the_log(world):
    record_event("test.one", user=world.owner)
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
    _raises_db_error("UPDATE audit_auditevent SET action = 'x'")
    _raises_db_error("DELETE FROM audit_auditevent")
    _raises_db_error("TRUNCATE audit_auditevent")


@pytest.mark.parametrize("model", [Transaction, StockMovement, PartyLedgerEntry])
def test_app_role_cannot_rewrite_history(world, model):
    table = model._meta.db_table
    _raises_db_error(f"DELETE FROM {table}")
    _raises_db_error(f"UPDATE {table} SET id = id")


def test_tampering_is_detected(world):
    record_event("test.one", user=world.owner)
    event = record_event("test.two", user=world.owner)
    record_event("test.three", user=world.owner)
    assert verify_chain().ok
    # Simulate someone with full access editing a row behind the app's back.
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER audit_event_no_change")
        cursor.execute("UPDATE audit_auditevent SET action = 'edited' WHERE id = %s", [event.pk])
        cursor.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER audit_event_no_change")
    report = verify_chain()
    assert not report.ok
    assert report.first_bad_seq == event.seq


def test_head_tracks_last_event(world):
    event = record_event("test.one", user=world.owner)
    head = AuditHead.objects.get(pk=1)
    assert head.seq == event.seq
    assert head.hash == event.hash
    assert AuditEvent.objects.order_by("-seq").first().pk == event.pk


def test_category_with_items_cannot_be_deleted(world):
    with pytest.raises(CatalogError):
        delete_category(world.owner, world.rings)


def test_empty_category_can_be_deleted_and_is_logged(world):
    delete_category(world.owner, world.chains)
    assert AuditEvent.objects.filter(action="category.deleted").exists()
