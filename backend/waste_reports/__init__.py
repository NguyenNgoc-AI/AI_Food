"""Sổ loại bỏ là các biến động waste đã xác nhận. Không cộng lô chỉ quá hạn."""

from datetime import date

from fastapi import APIRouter, HTTPException, Request

from ..catalog import ID
from ..db import transaction
from ..households import authorize
from ..inventory import batches
from ..monitoring import state

router = APIRouter(prefix="/api/households/{hid}/reports", tags=["Waste & reports"])


@router.get("")
def report(hid: ID, request: Request, start: date | None = None, end: date | None = None):
    if start and end and start > end:
        raise HTTPException(422, "Khoảng ngày không hợp lệ.")
    with transaction() as db:
        authorize(db, request, hid)
        rows = db.execute(
            "SELECT b.product_id,p.name,b.base_unit,m.kind,m.delta,m.reason FROM movements m "
            "JOIN batches b ON b.id=m.batch_id JOIN food_products p ON p.id=b.product_id "
            "WHERE household_id=? AND date(m.occurred,'+7 hours') BETWEEN ? AND ? ORDER BY m.id",
            (hid, str(start or date.min), str(end or date.max)),
        )
        totals, reasons = {}, {}
        for r in rows:
            pid = r["product_id"]
            item = totals.setdefault(
                pid,
                {
                    "product_id": pid,
                    "name": r["name"],
                    "unit": r["base_unit"],
                    "received": 0,
                    "consumed": 0,
                    "wasted": 0,
                    "adjustment": 0,
                },
            )
            key = {"receive": "received", "consume": "consumed", "waste": "wasted", "adjust": "adjustment"}[
                r["kind"]
            ]
            item[key] += -r["delta"] if r["kind"] in ("consume", "waste") else r["delta"]
            if r["kind"] == "waste":
                group = (pid, r["reason"])
                reasons[group] = reasons.get(group, 0) - r["delta"]
        return {
            "start": start,
            "end": end,
            "by_product": [
                {**r, **{k: str(r[k]) for k in ("received", "consumed", "wasted", "adjustment")}}
                for r in totals.values()
            ],
            "waste_reasons": [
                {"product_id": p, "reason": r, "ticks": str(n)} for (p, r), n in reasons.items()
            ],
            "active_alerts_now": sum(bool(state(b)) for b in batches(db, hid)),
        }
