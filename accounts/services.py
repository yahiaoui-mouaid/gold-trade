"""Login, lockout, TOTP, backup codes and the password reset token."""
import hashlib
import secrets
from datetime import timedelta
from enum import Enum

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import CommonPasswordValidator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django_otp.plugins.otp_totp.models import TOTPDevice

from audit.services import record_event

from .models import BackupCode, PasswordResetToken, User

FREE_ATTEMPTS = 5
MAX_LOCK_MINUTES = 60
BACKUP_CODE_COUNT = 10
MIN_LENGTH = {User.OWNER: 12, User.SALESMAN: 8}
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_DUMMY_HASH = None


class AuthError(Exception):
    pass


class LoginStatus(Enum):
    OK = "ok"
    BAD = "bad"
    LOCKED = "locked"


def owner_exists():
    return User.objects.filter(role=User.OWNER).exists()


def get_owner():
    return User.objects.filter(role=User.OWNER).first()


def validate_new_password(role, password):
    if len(password) < MIN_LENGTH[role]:
        raise AuthError(_("The password must have at least %(n)d characters.") % {"n": MIN_LENGTH[role]})
    try:
        CommonPasswordValidator().validate(password)
    except ValidationError:
        raise AuthError(_("This password is too common.")) from None


def _random_code(length, group):
    raw = "".join(secrets.choice(ALPHABET) for _i in range(length))
    return "-".join(raw[i:i + group] for i in range(0, length, group))


def _digest(code):
    cleaned = code.upper().replace("-", "").replace(" ", "").strip()
    return hashlib.sha256(cleaned.encode("ascii", "ignore")).hexdigest()


# Login -----------------------------------------------------------------------

def _register_failure(user, stage):
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        locked.failed_attempts += 1
        minutes = None
        if locked.failed_attempts >= FREE_ATTEMPTS:
            minutes = min(MAX_LOCK_MINUTES, 2 ** (locked.failed_attempts - FREE_ATTEMPTS))
            locked.locked_until = timezone.now() + timedelta(minutes=minutes)
        locked.save(update_fields=["failed_attempts", "locked_until"])
        record_event("login.failed", user=locked, details={"stage": stage})
        if minutes:
            record_event("login.locked", user=locked, details={"minutes": minutes})


def _is_locked(user):
    return user.locked_until is not None and user.locked_until > timezone.now()


def _clear_failures(user):
    User.objects.filter(pk=user.pk).update(failed_attempts=0, locked_until=None)


def check_credentials(username, password):
    """Returns (status, user). Failed attempts are committed immediately."""
    global _DUMMY_HASH
    user = User.objects.filter(username=username, is_active=True).first()
    if user is None:
        if _DUMMY_HASH is None:
            _DUMMY_HASH = make_password("gold-volt-dummy")
        check_password(password, _DUMMY_HASH)  # same work as a real check
        record_event("login.failed", username=username[:150], details={"stage": "password", "unknown_user": True})
        return LoginStatus.BAD, None
    if _is_locked(user):
        record_event("login.refused_locked", user=user)
        return LoginStatus.LOCKED, user
    if not user.check_password(password):
        _register_failure(user, "password")
        return LoginStatus.BAD, None
    return LoginStatus.OK, user


def complete_login(user, method):
    _clear_failures(user)
    record_event("login.ok", user=user, details={"method": method})


def confirmed_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def verify_second_factor(user, code):
    """Returns 'totp', 'backup', or None. A backup code is used up at once."""
    if _is_locked(user):
        record_event("login.refused_locked", user=user)
        return None
    cleaned = code.replace(" ", "").strip()
    if cleaned.isdigit() and len(cleaned) == 6:
        device = confirmed_device(user)
        if device is not None and device.verify_token(cleaned):
            return "totp"
    else:
        with transaction.atomic():
            backup = (BackupCode.objects.select_for_update()
                      .filter(user=user, code_hash=_digest(cleaned),
                              used_at__isnull=True, revoked_at__isnull=True)
                      .first())
            if backup is not None:
                backup.used_at = timezone.now()
                backup.save(update_fields=["used_at"])
                record_event("totp.backup_code_used", user=user)
                return "backup"
    _register_failure(user, "second_factor")
    return None


# Owner setup and recovery ----------------------------------------------------

def create_owner(username, display_name, password):
    validate_new_password(User.OWNER, password)
    with transaction.atomic():
        if owner_exists():
            raise AuthError(_("The owner account already exists."))
        user = User.objects.create_user(username, password, User.OWNER, display_name)
        record_event("user.created", user=user, obj=user, details={"role": User.OWNER})
    return user


def enrollment_device(user):
    """The not-yet-confirmed device for this user, created when missing."""
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    return device or TOTPDevice.objects.create(user=user, name="gold-volt", confirmed=False)


def confirm_enrollment(user, code):
    """Confirms the new device, replaces the old one and issues new backup
    codes. Returns the codes in plain text; they are never stored that way."""
    device = enrollment_device(user)
    if not device.verify_token(code.replace(" ", "").strip()):
        raise AuthError(_("That code is not correct. Check the phone's time and try again."))
    with transaction.atomic():
        TOTPDevice.objects.filter(user=user, confirmed=True).delete()
        device.confirmed = True
        device.save(update_fields=["confirmed"])
        codes = issue_backup_codes(user)
        record_event("totp.enrolled", user=user)
    return codes


def issue_backup_codes(user):
    now = timezone.now()
    with transaction.atomic():
        BackupCode.objects.filter(user=user, revoked_at__isnull=True, used_at__isnull=True).update(revoked_at=now)
        codes = [_random_code(20, 5) for _i in range(BACKUP_CODE_COUNT)]
        BackupCode.objects.bulk_create(BackupCode(user=user, code_hash=_digest(c)) for c in codes)
        record_event("totp.backup_codes_issued", user=user, details={"count": BACKUP_CODE_COUNT})
    return codes


def has_active_reset_token(user):
    return PasswordResetToken.objects.filter(user=user, revoked_at__isnull=True).exists()


def issue_reset_token(user):
    with transaction.atomic():
        PasswordResetToken.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
        token = _random_code(32, 4)
        PasswordResetToken.objects.create(user=user, token_hash=_digest(token))
        record_event("password.reset_token_issued", user=user)
    return token


def reset_password_with_token(token, new_password):
    """Resets the owner's password only: the second factor is still needed to
    log in. Returns a new token; the one just used stops working."""
    owner = get_owner()
    if owner is None:
        raise AuthError(_("The token is not valid."))
    with transaction.atomic():
        row = (PasswordResetToken.objects.select_for_update()
               .filter(user=owner, token_hash=_digest(token), revoked_at__isnull=True).first())
        if row is not None:
            validate_new_password(owner.role, new_password)
            owner.set_password(new_password)
            owner.failed_attempts = 0
            owner.locked_until = None
            owner.save(update_fields=["password", "failed_attempts", "locked_until"])
            record_event("password.reset_token_used", user=owner)
            return issue_reset_token(owner)
    record_event("password.reset_token_rejected", username=owner.username)
    raise AuthError(_("The token is not valid."))


# Passwords and salesman accounts ---------------------------------------------

def change_own_password(user, current, new):
    if not user.check_password(current):
        record_event("password.change_rejected", user=user)
        raise AuthError(_("The current password is not correct."))
    validate_new_password(user.role, new)
    with transaction.atomic():
        user.set_password(new)
        user.save(update_fields=["password"])
        record_event("password.changed", user=user)


def create_salesman(actor, username, display_name, password):
    validate_new_password(User.SALESMAN, password)
    if not username or User.objects.filter(username=username).exists():
        raise AuthError(_("This username is empty or already used."))
    with transaction.atomic():
        user = User.objects.create_user(username, password, User.SALESMAN, display_name)
        record_event("user.created", user=actor, obj=user, details={"username": username, "role": User.SALESMAN})
    return user


def reset_salesman_password(actor, target, new_password):
    if target.role != User.SALESMAN:
        raise AuthError(_("Only non-admin passwords can be reset here."))
    validate_new_password(target.role, new_password)
    with transaction.atomic():
        target.set_password(new_password)
        target.failed_attempts = 0
        target.locked_until = None
        target.save(update_fields=["password", "failed_attempts", "locked_until"])
        record_event("user.password_reset", user=actor, obj=target, details={"username": target.username})


def set_salesman_active(actor, target, active):
    if target.role != User.SALESMAN:
        raise AuthError(_("Only non-admin accounts can be disabled."))
    with transaction.atomic():
        target.is_active = active
        target.save(update_fields=["is_active"])
        record_event("user.enabled" if active else "user.disabled", user=actor, obj=target,
                     details={"username": target.username})
