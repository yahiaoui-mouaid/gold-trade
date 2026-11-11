from django.db import migrations

CREATE = """
CREATE FUNCTION audit_event_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'The activity log cannot be changed or deleted.';
END
$$;
CREATE TRIGGER audit_event_no_change BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_event_immutable();
CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_immutable();
"""


def create_head(apps, schema_editor):
    apps.get_model("audit", "AuditHead").objects.create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        migrations.RunSQL(CREATE),
        migrations.RunPython(create_head, migrations.RunPython.noop),
    ]
