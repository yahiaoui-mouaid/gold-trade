import re
import unicodedata

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from audit.services import record_event

from .models import Party

_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
_AR_MARKS = re.compile("[ً-ْٰ]")
SEARCH_LIMIT = 20
EDITABLE = ("kind", "name", "phone", "id_number", "address", "notes", "alert_days")


class PartyError(Exception):
    def __init__(self, message, existing=None):
        super().__init__(message)
        self.existing = existing


def normalize_name(text):
    text = unicodedata.normalize("NFKC", text or "")
    text = _AR_MARKS.sub("", text).translate(_AR_MAP).lower()
    return " ".join(text.split())


def normalize_phone(text):
    return re.sub(r"\D", "", text or "")


def search_parties(query, kinds=None, include_archived=False):
    """Partial search on name or phone."""
    name = normalize_name(query)
    digits = normalize_phone(query)
    if len(name) < 2:
        return Party.objects.none()
    condition = Q(name_search__contains=name)
    if len(digits) >= 2:
        condition |= Q(phone__contains=digits)
    rows = Party.objects.filter(condition)
    if kinds:
        rows = rows.filter(kind__in=kinds)
    if not include_archived:
        rows = rows.filter(archived=False)
    return rows


def create_party(actor, kind, name, phone, require_phone=False, **extra):
    name = " ".join((name or "").split())
    phone = normalize_phone(phone)
    if not name:
        raise PartyError(_("The name is required."))
    if require_phone and not phone:
        raise PartyError(_("The phone number is required."))
    if kind not in dict(Party.KINDS):
        raise PartyError(_("Choose client or supplier."))
    if phone:
        existing = Party.objects.filter(phone=phone).first()
        if existing is not None:
            raise PartyError(_("This phone number already belongs to %(name)s.") % {"name": existing.name}, existing)
    try:
        with transaction.atomic():
            party = Party.objects.create(kind=kind, name=name, name_search=normalize_name(name),
                                         phone=phone or None, created_by=actor, **extra)
            record_event("party.created", user=actor, obj=party, party_id=party.pk,
                         details={"kind": kind, "name": name, "phone": phone})
    except IntegrityError:
        raise PartyError(_("This phone number is already used.")) from None
    return party


def update_party(actor, party, **fields):
    fields["name"] = " ".join((fields.get("name") or "").split())
    fields["phone"] = normalize_phone(fields.get("phone")) or None
    if not fields["name"]:
        raise PartyError(_("The name is required."))
    before = {k: getattr(party, k) for k in EDITABLE}
    try:
        with transaction.atomic():
            for key, value in fields.items():
                setattr(party, key, value)
            party.name_search = normalize_name(party.name)
            party.save()
            after = {k: getattr(party, k) for k in EDITABLE}
            changed = {k: {"before": before[k], "after": after[k]} for k in EDITABLE if before[k] != after[k]}
            record_event("party.edited", user=actor, obj=party, party_id=party.pk, details=changed)
    except IntegrityError:
        raise PartyError(_("This phone number is already used.")) from None


def set_archived(actor, party, archived):
    with transaction.atomic():
        party.archived = archived
        party.save(update_fields=["archived"])
        record_event("party.archived" if archived else "party.restored", user=actor, obj=party, party_id=party.pk)
