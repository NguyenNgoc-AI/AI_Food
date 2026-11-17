"""Đồng hồ nghiệp vụ và chống gửi lặp trong cùng giao dịch ghi."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


def today():
    return datetime.now(timezone(timedelta(hours=7))).date()


def once(db, hid, actor, key, operation, data, apply):
    signature = hashlib.sha256(
        json.dumps(
            [actor, operation, data.model_dump(mode="json")], sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()
    old = db.execute(
        "SELECT signature,result FROM operation_keys WHERE household_id=? AND key=?", (hid, key)
    ).fetchone()
    if old:
        if old["signature"] != signature:
            raise HTTPException(409, "Khóa yêu cầu đã dùng cho thao tác khác.")
        return json.loads(old["result"])
    result = apply()
    db.execute("INSERT INTO operation_keys VALUES (?,?,?,?)", (hid, key, signature, json.dumps(result)))
    target = next((result[k] for k in ("movement_id", "receipt_id", "batch_id", "id") if k in result), None)
    db.execute(
        "INSERT INTO audit_events(household_id,actor_id,action,reason,target_id,occurred_at) "
        "VALUES (?,?,?,?,?,unixepoch())",
        (hid, actor, operation, "confirmed", target),
    )
    return result
