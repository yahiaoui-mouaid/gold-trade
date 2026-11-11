from django.conf import settings
from django.db import models


class Party(models.Model):
    CLIENT = "client"
    SUPPLIER = "supplier"
    WORKSHOP = "workshop"
    KINDS = [(CLIENT, "Client"), (SUPPLIER, "Supplier"), (WORKSHOP, "Workshop")]

    kind = models.CharField(max_length=10, choices=KINDS)
    name = models.CharField(max_length=150)
    name_search = models.CharField(max_length=150, db_index=True, editable=False)
    phone = models.CharField(max_length=30, unique=True, null=True, blank=True)
    id_number = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=250, blank=True)
    notes = models.TextField(blank=True)
    alert_days = models.PositiveIntegerField(null=True, blank=True)
    archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name_search"]

    def __str__(self):
        return self.name
