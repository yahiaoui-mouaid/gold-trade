"""Settings and the PC clock check (A8)."""
from datetime import timedelta

from django.apps import apps
from django.utils import timezone
from django.utils.translation import gettext as _

from audit.services import record_event

from .models import AppSetting

MAX_JUMP = timedelta(days=1)
CLOCK_KEY = "clock_confirmed_for_transaction"


class ClockBlocked(Exception):
    pass


def get_setting(key, default=None):
    row = AppSetting.objects.filter(key=key).first()
    return row.value if row else default


def set_setting(key, value):
    AppSetting.objects.update_or_create(key=key, defaults={"value": str(value)})


def _last_transaction():
    model = apps.get_model("ledger", "Transaction")
    return model.objects.order_by("-recorded_at", "-id").only("id", "recorded_at").first()


def clock_status():
    """'ok', 'backwards' or 'jumped', compared with the last posted transaction."""
    last = _last_transaction()
    if last is None or get_setting(CLOCK_KEY) == str(last.pk):
        return "ok"
    now = timezone.now()
    if now < last.recorded_at:
        return "backwards"
    if now - last.recorded_at > MAX_JUMP:
        return "jumped"
    return "ok"


def enforce_clock(user):
    """A salesman cannot post while the clock looks wrong. The warning is logged
    whoever posts."""
    status = clock_status()
    if status == "ok":
        return
    record_event("clock.warning", user=user, details={"status": status})
    if not user.is_owner:
        raise ClockBlocked(_("The computer's time needs to be confirmed by the admin."))


def confirm_clock(user):
    last = _last_transaction()
    status = clock_status()
    if last is not None:
        set_setting(CLOCK_KEY, last.pk)
    record_event("clock.confirmed", user=user, details={"status": status})
