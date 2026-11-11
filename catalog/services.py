from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from audit.services import record_event

from .models import Category, Origin, Purity, StockItem


class CatalogError(Exception):
    pass


def create_named(actor, model, name_ar, name_fr):
    name_ar, name_fr = name_ar.strip(), name_fr.strip()
    if not name_ar or not name_fr:
        raise CatalogError(_("Both the Arabic and French names are required."))
    try:
        with transaction.atomic():
            row = model.objects.create(name_ar=name_ar, name_fr=name_fr)
            record_event(f"{model.__name__.lower()}.created", user=actor, obj=row,
                         details={"name_ar": name_ar, "name_fr": name_fr})
    except IntegrityError:
        raise CatalogError(_("This name already exists.")) from None
    return row


def create_purity(actor, label, fineness):
    label = label.strip()
    try:
        value = Decimal(fineness.strip().replace(",", "."))
    except InvalidOperation:
        raise CatalogError(_("Fineness must be a number between 0 and 1000.")) from None
    if not label or not (0 < value <= 1000) or value != value.quantize(Decimal("0.1")):
        raise CatalogError(_("Fineness must be a number between 0 and 1000."))
    try:
        with transaction.atomic():
            row = Purity.objects.create(label=label, fineness=value)
            record_event("purity.created", user=actor, obj=row, details={"label": label, "fineness": value})
    except IntegrityError:
        raise CatalogError(_("This name already exists.")) from None
    return row


def set_disabled(actor, row, disabled):
    with transaction.atomic():
        row.disabled = disabled
        row.save(update_fields=["disabled"])
        action = "disabled" if disabled else "enabled"
        record_event(f"{row.__class__.__name__.lower()}.{action}", user=actor, obj=row, details={"name": str(row)})


def delete_category(actor, category):
    """F8: a category that has any item in it can never be deleted."""
    if StockItem.objects.filter(category=category).exists():
        raise CatalogError(_("This category has items in it and cannot be deleted."))
    with transaction.atomic():
        details = {"name_ar": category.name_ar, "name_fr": category.name_fr, "id": category.pk}
        Category.objects.filter(pk=category.pk).delete()
        record_event("category.deleted", user=actor, details=details)


__all__ = ["CatalogError", "Category", "Origin", "Purity", "create_named", "create_purity",
           "delete_category", "set_disabled"]
