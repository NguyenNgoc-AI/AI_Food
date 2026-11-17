"""Lô, FIFO, sổ biến động và đối soát tồn thực tế."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator

from ..audit_config import once, today
from ..catalog import ID, Input, Key, Quantity, convert
from ..db import transaction
from ..households import authorize

router = APIRouter(prefix="/api/households/{hid}/inventory", tags=["Inventory"])
Reason = Annotated[str, Field(min_length=1, max_length=250, pattern=r"\S")]


class BatchInput(Quantity):
    received: date
    expiry: date | None = None
    expiry_source: Literal["label", "user", "estimate", "unknown"] = "unknown"
    flagged: bool = False

    @model_validator(mode="after")
    def check_dates(self):
        if self.received > today() or (self.expiry is None) != (self.expiry_source == "unknown"):
            raise ValueError("Kiểm tra ngày nhận, hạn và nguồn hạn.")
        return self


class Receive(BatchInput):
    request_key: Key


class Change(Quantity):
    request_key: Key
    kind: Literal["consume", "waste", "adjust"]
    reason: Reason
    expected_version: ID | None = None


def get_batch(db, hid, bid):
    batch = db.execute("SELECT * FROM batches WHERE id=? AND household_id=?", (bid, hid)).fetchone()
    if not batch:
        raise HTTPException(404, "Không tìm thấy lô trong hộ.")
    return batch


def usable(batch, day):
    return not batch["flagged"] and batch["expiry_source"] in ("label", "user") and batch["expiry"] >= day


def receive(db, hid, actor, data):
    ticks = convert(db, data)
    unit = db.execute("SELECT base_unit FROM food_products WHERE id=?", (data.product_id,)).fetchone()[0]
    bid = db.execute(
        "INSERT INTO batches(household_id,product_id,base_unit,received,expiry,expiry_source,flagged,ticks,original)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            hid,
            data.product_id,
            unit,
            data.received.isoformat(),
            data.expiry.isoformat() if data.expiry else None,
            data.expiry_source,
            data.flagged,
            ticks,
            data.model_dump_json(exclude={"request_key"}),
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO movements(batch_id,actor,kind,delta,reason) VALUES (?,?,'receive',?,'confirmed')",
        (bid, actor, ticks),
    )
    return {"batch_id": bid, "ticks": str(ticks), "version": 1}


@router.post("/batches", status_code=201)
def add(hid: ID, data: Receive, request: Request):
    with transaction(write=True) as db:
        actor, _ = authorize(db, request, hid)
        return once(db, hid, actor, data.request_key, "receive", data, lambda: receive(db, hid, actor, data))


def batches(db, hid):
    return db.execute(
        "SELECT b.*,p.name FROM batches b JOIN food_products p ON p.id=b.product_id "
        "WHERE household_id=? ORDER BY received,id",
        (hid,),
    ).fetchall()


@router.get("/batches")
def listing(hid: ID, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        return [{**dict(b), "ticks": str(b["ticks"])} for b in batches(db, hid)]


@router.get("/fifo/{product_id}")
def fifo(hid: ID, product_id: ID, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        rows = [
            b
            for b in batches(db, hid)
            if b["product_id"] == product_id and b["ticks"] and usable(b, today().isoformat())
        ]
        return {
            "batch_ids": [b["id"] for b in rows],
            "earlier_expiry_ids": [b["id"] for b in rows[1:] if b["expiry"] < rows[0]["expiry"]],
        }


def apply_change(db, hid, bid, actor, data):
    batch = get_batch(db, hid, bid)
    if batch["product_id"] != data.product_id:
        raise HTTPException(422, "Sai sản phẩm của lô.")
    if data.kind == "adjust" and data.expected_version is None:
        raise HTTPException(422, "Đối soát cần phiên bản lô khi kiểm kê.")
    if data.expected_version is not None and data.expected_version != batch["version"]:
        raise HTTPException(409, "Lô đã thay đổi, hãy kiểm tra lại.")
    amount = convert(db, data, allow_zero=data.kind == "adjust")
    if data.kind == "consume" and not usable(batch, today().isoformat()):
        raise HTTPException(409, "Cần kiểm tra lô trước khi dùng.")
    delta = amount - batch["ticks"] if data.kind == "adjust" else -amount
    balance = batch["ticks"] + delta
    if balance < 0:
        raise HTTPException(409, "Không đủ tồn.")
    db.execute("UPDATE batches SET ticks=?,version=version+1 WHERE id=?", (balance, bid))
    movement = db.execute(
        "INSERT INTO movements(batch_id,actor,kind,delta,reason) VALUES (?,?,?,?,?)",
        (bid, actor, data.kind, delta, data.reason),
    ).lastrowid
    return {"batch_id": bid, "movement_id": movement, "ticks": str(balance), "version": batch["version"] + 1}


@router.post("/batches/{bid}/movements")
def change(hid: ID, bid: ID, data: Change, request: Request):
    with transaction(write=True) as db:
        actor, _ = authorize(db, request, hid)
        return once(
            db,
            hid,
            actor,
            data.request_key,
            f"batch:{bid}",
            data,
            lambda: apply_change(db, hid, bid, actor, data),
        )


@router.get("/batches/{bid}/ledger")
def ledger(hid: ID, bid: ID, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        batch = get_batch(db, hid, bid)
        history = [
            dict(m) for m in db.execute("SELECT * FROM movements WHERE batch_id=? ORDER BY id", (bid,))
        ]
        total = sum(m["delta"] for m in history)
        return {
            "ticks": str(batch["ticks"]),
            "ledger_ticks": str(total),
            "version": batch["version"],
            "movements": [{**m, "delta": str(m["delta"])} for m in history],
        }


@router.post("/batches/{bid}/count-preview")
def count_preview(hid: ID, bid: ID, data: Quantity, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        batch = get_batch(db, hid, bid)
        if batch["product_id"] != data.product_id:
            raise HTTPException(422, "Sai sản phẩm.")
        counted = convert(db, data, allow_zero=True)
        return {"difference_ticks": str(counted - batch["ticks"]), "version": batch["version"]}


class BatchReview(Input):
    request_key: Key
    expected_version: ID
    expiry: date | None
    expiry_source: Literal["label", "user", "estimate", "unknown"]
    flagged: bool
    reason: Reason


@router.put("/batches/{bid}/review")
def review_batch(hid: ID, bid: ID, data: BatchReview, request: Request):
    with transaction(write=True) as db:
        uid, _ = authorize(db, request, hid)

        def apply():
            b = get_batch(db, hid, bid)
            if b["version"] != data.expected_version:
                raise HTTPException(409, "Lô đã thay đổi.")
            if (data.expiry is None) != (data.expiry_source == "unknown"):
                raise HTTPException(422, "Hạn và nguồn hạn chưa khớp.")
            db.execute(
                "UPDATE batches SET expiry=?,expiry_source=?,flagged=?,version=version+1 WHERE id=?",
                (str(data.expiry) if data.expiry else None, data.expiry_source, data.flagged, bid),
            )
            db.execute(
                "INSERT INTO audit_events(household_id,actor_id,action,target_id,reason,occurred_at) "
                "VALUES (?,?,'batch_review',?,?,unixepoch())",
                (hid, uid, bid, data.reason),
            )
            return {"id": bid, "version": b["version"] + 1}

        return once(db, hid, uid, data.request_key, f"review:{bid}", data, apply)


@router.get("/snapshot")
def snapshot(hid: ID, request: Request):
    with transaction() as db:
        uid, _ = authorize(db, request, hid)
        return {
            "user_id": uid,
            "household_id": hid,
            "last_synced_at": db.execute("SELECT strftime('%Y-%m-%dT%H:%M:%SZ','now')").fetchone()[0],
            "batches": [
                {
                    "id": b["id"],
                    "product": b["name"],
                    "unit": b["base_unit"],
                    "ticks": str(b["ticks"]),
                    "expiry": b["expiry"],
                    "expiry_source": b["expiry_source"],
                    "flagged": bool(b["flagged"]),
                }
                for b in batches(db, hid)
            ],
        }
