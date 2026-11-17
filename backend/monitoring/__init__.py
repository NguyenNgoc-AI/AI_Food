"""Cảnh báo trong ứng dụng và trạng thái đã đọc riêng từng người."""

from datetime import date

from fastapi import APIRouter, HTTPException, Request

from ..audit_config import today
from ..catalog import ID
from ..db import transaction
from ..households import authorize
from ..inventory import batches, get_batch

router = APIRouter(prefix="/api/households/{hid}/alerts", tags=["Monitoring"])


def state(batch):
    if not batch["ticks"]:
        return None
    if batch["flagged"]:
        return "flagged"
    if batch["expiry_source"] not in ("label", "user"):
        return "verify_expiry"
    days = (date.fromisoformat(batch["expiry"]) - today()).days
    if days < 0:
        return "past_date"
    if days <= 3:
        return "due_soon"
    return None


@router.get("")
def inbox(hid: ID, request: Request):
    with transaction() as db:
        actor, _ = authorize(db, request, hid)
        read = set(map(tuple, db.execute("SELECT batch_id,state FROM alert_reads WHERE user_id=?", (actor,))))
        return [
            {
                "batch_id": b["id"],
                "product": b["name"],
                "reason": reason,
                "expiry": b["expiry"],
                "source": b["expiry_source"],
                "read": (b["id"], reason) in read,
            }
            for b in batches(db, hid)
            if (reason := state(b))
        ]


@router.put("/{bid}/{reason}/read")
def mark(hid: ID, bid: ID, reason: str, request: Request):
    with transaction(write=True) as db:
        actor, _ = authorize(db, request, hid)
        if state(get_batch(db, hid, bid)) != reason:
            raise HTTPException(404, "Cảnh báo đã thay đổi.")
        db.execute("INSERT OR IGNORE INTO alert_reads VALUES (?,?,?)", (bid, actor, reason))
        return {"read": True}
