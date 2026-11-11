"""Sets exactly what the app's daily database role may do (A3)."""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection

APP_ROLE = "goldvolt_app"
APPEND_ONLY = [
    ("ledger", "Transaction"),
    ("ledger", "TransactionLine"),
    ("ledger", "StockMovement"),
    ("ledger", "PartyLedgerEntry"),
    ("ledger", "CashMovement"),
    ("audit", "AuditEvent"),
]
READ_ONLY_TABLES = {"django_migrations", "django_content_type", "auth_permission", "auth_group",
                    "auth_group_permissions", "django_otp_devices"}
DELETE_ALLOWED = {"catalog_category", "django_session", "otp_totp_totpdevice"}


class Command(BaseCommand):
    help = "Apply database permissions for the goldvolt_app role."

    def handle(self, *args, **options):
        append_only = {apps.get_model(a, m)._meta.db_table for a, m in APPEND_ONLY}
        quote = connection.ops.quote_name
        role = quote(APP_ROLE)
        with connection.cursor() as cursor:
            cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            for table in connection.introspection.table_names(cursor):
                name = quote(table)
                cursor.execute(f"REVOKE ALL ON {name} FROM {role}")
                if table in append_only:
                    allowed = "SELECT, INSERT"
                elif table in READ_ONLY_TABLES:
                    allowed = "SELECT"
                elif table in DELETE_ALLOWED:
                    allowed = "SELECT, INSERT, UPDATE, DELETE"
                else:
                    allowed = "SELECT, INSERT, UPDATE"
                cursor.execute(f"GRANT {allowed} ON {name} TO {role}")
            cursor.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
        self.stdout.write("Grants applied.")
