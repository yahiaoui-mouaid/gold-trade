"""The activity log and its SHA-256 hash chain."""
import hashlib
import json
from dataclasses import dataclass
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from .models import GENESIS_HASH, AuditEvent, AuditHead


def _canonical(seq, at, user_id, username, role, action, object_type, object_id, party_id, details):
    payload = {
        "seq": seq,
        "at": at.astimezone(dt_timezone.utc).isoformat(),
        "user_id": user_id,
        "username": username,
        "role": role,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "party_id": party_id,
        "details": details,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(prev_hash, canonical):
    return hashlib.sha256(prev_hash.encode("ascii") + canonical.encode("utf-8")).hexdigest()


def record_event(action, user=None, username=None, obj=None, party_id=None, details=None):
    """Append one event. Joins the caller's database transaction, so an event
    and the action it describes are saved together or not at all."""
    details = json.loads(json.dumps(details or {}, default=str))
    is_real_user = user is not None and getattr(user, "pk", None) is not None
    user_id = user.pk if is_real_user else None
    name = user.username if is_real_user else (username or "")
    role = user.role if is_real_user else ""
    object_type = obj.__class__.__name__ if obj is not None else ""
    object_id = str(obj.pk) if obj is not None else ""

    with transaction.atomic():
        head = AuditHead.objects.select_for_update().get(pk=1)
        seq = head.seq + 1
        at = timezone.now()
        digest = _hash(head.hash, _canonical(seq, at, user_id, name, role, action,
                                             object_type, object_id, party_id, details))
        event = AuditEvent.objects.create(
            seq=seq, at=at, user_id=user_id, username=name, role=role, action=action,
            object_type=object_type, object_id=object_id, party_id=party_id,
            details=details, prev_hash=head.hash, hash=digest,
        )
        head.seq = seq
        head.hash = digest
        head.save(update_fields=["seq", "hash"])
    return event


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    checked: int
    first_bad_seq: int | None


def verify_chain():
    """Recompute the whole chain and compare it with the stored head."""
    prev = GENESIS_HASH
    expected_seq = 0
    for e in AuditEvent.objects.order_by("seq").iterator():
        expected_seq += 1
        digest = _hash(prev, _canonical(e.seq, e.at, e.user_id, e.username, e.role, e.action,
                                        e.object_type, e.object_id, e.party_id, e.details))
        if e.seq != expected_seq or e.prev_hash != prev or e.hash != digest:
            return ChainReport(False, expected_seq - 1, e.seq)
        prev = digest
    head = AuditHead.objects.get(pk=1)
    if head.seq != expected_seq or head.hash != prev:
        return ChainReport(False, expected_seq, expected_seq + 1)
    return ChainReport(True, expected_seq, None)
