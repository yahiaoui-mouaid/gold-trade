import uuid

from django.conf import settings
from django.db import models

GENESIS_HASH = "0" * 64


class AuditEvent(models.Model):
    """Append-only activity log. A database trigger rejects any change or
    deletion, for every role including the migration role."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    seq = models.BigIntegerField(unique=True)
    at = models.DateTimeField(help_text="Real server time; never user-supplied.")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.PROTECT, related_name="+")
    username = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    party_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    details = models.JSONField(default=dict)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["-seq"]


class AuditHead(models.Model):
    """The chain's single head row. Locking this row serialises appends; the
    app role has no UPDATE on AuditEvent and so could not lock its last row."""

    seq = models.BigIntegerField(default=0)
    hash = models.CharField(max_length=64, default=GENESIS_HASH)
