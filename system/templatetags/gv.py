from decimal import Decimal

from django import template
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

register = template.Library()

_LABELS = {
    "sale": _("Sale"), "purchase": _("Purchase"), "payment": _("Debt payment"),
    "adjustment": _("Stock adjustment"), "reversal": _("Void"),
    "client": _("Client"), "supplier": _("Supplier"), "workshop": _("Workshop"),
    "raw": _("Raw gold"), "ready": _("Ready gold"), "scrap": _("Scrap"),
    "owner": _("Admin"), "salesman": _("Non-admin"),
    "money": _("Money"), "gold": _("Gold"),
}


@register.filter
def label(value):
    return _LABELS.get(value, value)


def _trim(value):
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


@register.filter
def grams(value):
    """Western digits and a dot, never localised, with up to 4 decimals."""
    if value is None:
        return ""
    return _trim(Decimal(value).quantize(Decimal("0.0001")))


@register.filter
def absgrams(value):
    return "" if value is None else grams(abs(Decimal(value)))


@register.filter
def dinars(value):
    if value is None:
        return ""
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


@register.filter
def absdinars(value):
    return "" if value is None else dinars(abs(Decimal(value)))


@register.filter
def plain(value):
    """A decimal as form input text."""
    return "" if value is None else _trim(Decimal(value))


@register.filter
def dt(value):
    if value is None:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


@register.filter
def dtinput(value):
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")


@register.filter
def verification(txn):
    """The receipt's 8-character code, taken from the activity log."""
    from audit.models import AuditEvent

    event = (AuditEvent.objects.filter(object_type="Transaction", object_id=str(txn.pk),
                                       action=f"transaction.{txn.kind}").order_by("seq").first())
    return event.hash[:8].upper() if event else ""
