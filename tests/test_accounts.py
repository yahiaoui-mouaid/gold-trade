"""F9 and B7: first run, TOTP, backup codes, reset token, lockout."""
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import services
from accounts.models import BackupCode, User
from audit.models import AuditEvent

pytestmark = pytest.mark.django_db
PASSWORD = "correct-horse-battery"


def code_for(device):
    return f"{totp(device.bin_key, step=device.step, digits=device.digits):06d}"


def _reset_otp_guard(device):
    TOTPDevice.objects.filter(pk=device.pk).update(last_t=-1, throttling_failure_count=0,
                                                   throttling_failure_timestamp=None)


def first_run(client):
    assert client.get("/").headers["Location"] == "/setup/"
    response = client.post("/setup/", {"username": "boss", "display_name": "Boss", "password": PASSWORD, "password2": PASSWORD})
    assert response.headers["Location"] == "/account/enroll/"
    assert client.get("/account/enroll/").status_code == 200
    device = TOTPDevice.objects.get(user__username="boss", confirmed=False)
    response = client.post("/account/enroll/", {"code": code_for(device)})
    assert response.headers["Location"] == "/account/recovery/"
    return device


def test_first_run_shows_token_and_ten_codes_once():
    client = Client()
    first_run(client)
    page = client.get("/account/recovery/")
    display = page.context["display"]
    assert len(display["codes"]) == 10 and display["token"]
    assert client.get("/dashboard/").headers["Location"] == "/account/recovery/"
    response = client.post("/account/recovery/", {"saved": "1"})
    assert response.status_code == 302
    assert client.get("/account/recovery/").status_code == 302
    assert client.get("/dashboard/").status_code == 200


def test_codes_are_stored_hashed():
    client = Client()
    first_run(client)
    codes = client.get("/account/recovery/").context["display"]["codes"]
    stored = set(BackupCode.objects.values_list("code_hash", flat=True))
    assert len(stored) == 10 and not stored & set(codes)


def test_second_setup_is_refused():
    client = Client()
    first_run(client)
    assert Client().get("/setup/").headers["Location"] == "/login/"


def test_owner_needs_the_second_factor(world):
    device = TOTPDevice.objects.create(user=world.owner, name="x", confirmed=True)
    client = Client()
    response = client.post("/login/", {"username": "owner", "password": PASSWORD})
    assert response.headers["Location"] == "/login/code/"
    assert client.get("/dashboard/").headers["Location"] == "/login/"
    response = client.post("/login/code/", {"code": code_for(device)})
    assert response.headers["Location"] == "/"
    assert client.get("/dashboard/").status_code == 200


def test_salesman_has_no_second_factor(world):
    client = Client()
    response = client.post("/login/", {"username": "sam", "password": "salesman-pass"})
    assert response.status_code == 302
    assert client.get("/operations/new/sale/").status_code == 200


def test_backup_code_works_once_and_forces_reconnect(world):
    TOTPDevice.objects.create(user=world.owner, name="x", confirmed=True)
    codes = services.issue_backup_codes(world.owner)
    client = Client()
    client.post("/login/", {"username": "owner", "password": PASSWORD})
    response = client.post("/login/code/", {"code": codes[0]})
    assert response.headers["Location"] == "/account/enroll/"
    assert client.get("/dashboard/").headers["Location"] == "/account/enroll/"
    assert AuditEvent.objects.filter(action="totp.backup_code_used").exists()

    other = Client()
    other.post("/login/", {"username": "owner", "password": PASSWORD})
    assert other.post("/login/code/", {"code": codes[0]}).status_code == 200  # refused, same page


def test_reconnecting_cancels_old_codes(world):
    old_device = TOTPDevice.objects.create(user=world.owner, name="old", confirmed=True)
    old_codes = services.issue_backup_codes(world.owner)
    new = services.enrollment_device(world.owner)
    new_codes = services.confirm_enrollment(world.owner, code_for(new))
    assert not TOTPDevice.objects.filter(pk=old_device.pk).exists()
    assert len(new_codes) == 10
    assert services.verify_second_factor(world.owner, old_codes[1]) is None
    assert services.verify_second_factor(world.owner, new_codes[1]) == "backup"


def test_reset_token_rotates_and_needs_no_login(world):
    token = services.issue_reset_token(world.owner)
    new_token = services.reset_password_with_token(token, "another-long-password")
    assert new_token != token
    world.owner.refresh_from_db()
    assert world.owner.check_password("another-long-password")
    with pytest.raises(services.AuthError):
        services.reset_password_with_token(token, "third-long-password!")
    services.reset_password_with_token(new_token, "third-long-password!")


def test_reset_page_shows_the_new_token_once(world):
    token = services.issue_reset_token(world.owner)
    client = Client()
    response = client.post("/login/forgot/", {"token": token, "password": "another-long-password", "password2": "another-long-password"})
    assert response.headers["Location"] == "/account/recovery/"
    assert client.get("/account/recovery/").context["display"]["token"]


def test_salesman_cannot_use_the_token_route_to_reach_a_session(world):
    token = services.issue_reset_token(world.owner)
    client = Client()
    client.post("/login/forgot/", {"token": token, "password": "another-long-password", "password2": "another-long-password"})
    client.post("/account/recovery/", {"saved": "1"})
    assert client.get("/dashboard/").headers["Location"] == "/login/"


def test_lockout_after_five_failures_and_each_is_logged(world):
    client = Client()
    for _i in range(5):
        client.post("/login/", {"username": "sam", "password": "wrong"})
    world.salesman.refresh_from_db()
    assert world.salesman.locked_until > timezone.now()
    assert AuditEvent.objects.filter(action="login.failed").count() == 5
    assert AuditEvent.objects.filter(action="login.locked").count() == 1
    assert client.post("/login/", {"username": "sam", "password": "salesman-pass"}).status_code == 200
    User.objects.filter(pk=world.salesman.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
    assert client.post("/login/", {"username": "sam", "password": "salesman-pass"}).status_code == 302


def test_lock_doubles_up_to_one_hour(world):
    for _i in range(20):
        User.objects.filter(pk=world.salesman.pk).update(locked_until=None)
        services.check_credentials("sam", "wrong")
    world.salesman.refresh_from_db()
    assert world.salesman.locked_until - timezone.now() <= timedelta(minutes=60)
    assert world.salesman.locked_until - timezone.now() > timedelta(minutes=59)


def test_failed_login_for_unknown_user_is_logged(world):
    Client().post("/login/", {"username": "ghost", "password": "x"})
    event = AuditEvent.objects.get(action="login.failed")
    assert event.username == "ghost"


def test_passwords_are_argon2(world):
    assert world.owner.password.startswith("argon2id$") or world.owner.password.startswith("argon2$")


def test_idle_session_locks(world):
    client = Client()
    client.force_login(world.salesman, backend="django.contrib.auth.backends.ModelBackend")
    session = client.session
    session["last_seen"] = 0
    session.save()
    assert client.get("/operations/new/sale/").headers["Location"] == "/login/"
    assert AuditEvent.objects.filter(action="session.idle_lock").exists()


def test_owner_cannot_be_duplicated(world):
    with pytest.raises(services.AuthError):
        services.create_owner("second", "x", PASSWORD)
