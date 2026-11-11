from decimal import Decimal

from django.db import migrations

DEFAULTS = [("24k", "999.9"), ("21k", "875.0"), ("18k", "750.0")]


def seed(apps, schema_editor):
    purity = apps.get_model("catalog", "Purity")
    for label, fineness in DEFAULTS:
        purity.objects.create(label=label, fineness=Decimal(fineness))


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
