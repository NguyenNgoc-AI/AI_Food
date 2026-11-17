import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ..audit_config import once
from ..catalog import ID, Input, Key, lookup
from ..db import transaction
from ..households import authorize
from ..inventory import BatchInput, receive

router = APIRouter(prefix="/api/households/{hid}/receipts", tags=["Receipt"])
OCR_SLOTS = threading.BoundedSemaphore(2)
LIMIT = 5 * 1024 * 1024
LINE = re.compile(r"^(.+?)\s+(\d+(?:[.,]\d+)?)\s*(kg|ml|g|l|quả|gói|hộp|bó)(?:\s|$)", re.IGNORECASE)


def recognize(image):
    if os.name != "nt":
        raise HTTPException(503, "OCR local cần Windows. Có thể nhập tay qua API kho.")
    if not OCR_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "OCR đang bận. Vui lòng thử lại.")
    try:
        run = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).with_name("windows_ocr.ps1")),
            ],
            input=base64.b64encode(image),
            capture_output=True,
            timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
        )
        return json.loads(run.stdout.decode("utf-8-sig"))
    except (OSError, ValueError, subprocess.SubprocessError):
        raise HTTPException(503, "OCR chưa sẵn sàng. Bạn vẫn có thể nhập tay.") from None
    finally:
        OCR_SLOTS.release()


@router.post("", status_code=201)
async def upload(hid: ID, request: Request):
    with transaction() as db:
        actor, _ = authorize(db, request, hid)
    media = request.headers.get("content-type", "").split(";")[0].lower()
    if media not in ("image/jpeg", "image/png"):
        raise HTTPException(415, "Cần ảnh PNG hoặc JPEG.")
    image = bytearray()
    async for chunk in request.stream():
        if len(image) + len(chunk) > LIMIT:
            raise HTTPException(413, "Ảnh vượt 5 MiB.")
        image.extend(chunk)
    signature = b"\x89PNG\r\n\x1a\n" if media == "image/png" else b"\xff\xd8\xff"
    if not image.startswith(signature):
        raise HTTPException(422, "Nội dung không khớp loại ảnh.")
    fingerprint = hashlib.sha256(image).hexdigest()
    result = await asyncio.to_thread(recognize, image)
    if result["status"] == "invalid_image":
        raise HTTPException(422, "Ảnh hỏng hoặc vượt giới hạn kích thước.")
    with transaction(write=True) as db:
        uid, _ = authorize(db, request, hid)
        if uid != actor:
            raise HTTPException(409, "Phiên đã thay đổi.")
        previous = [
            r[0]
            for r in db.execute(
                "SELECT id FROM receipts WHERE household_id=? AND fingerprint=?", (hid, fingerprint)
            )
        ]
        suggestions = []
        for line in result["lines"]:
            match = LINE.search(line)
            if match:
                name, amount, unit = match.groups()
                suggestions.append(
                    {
                        "name": name,
                        "quantity": amount.replace(",", "."),
                        "unit": unit.lower(),
                        **lookup(db, name),
                    }
                )
        draft = {**result, "suggestions": suggestions, "items": [], "version": 1}
        rid = db.execute(
            "INSERT INTO receipts(household_id,actor,fingerprint,draft) VALUES (?,?,?,?)",
            (hid, uid, fingerprint, json.dumps(draft, ensure_ascii=False)),
        ).lastrowid
        return {"id": rid, "possible_duplicates": previous, **draft}


class Edit(Input):
    version: ID
    items: list[BatchInput] = Field(min_length=1, max_length=150)


class Confirm(Input):
    version: ID
    request_key: Key


def receipt(db, hid, rid):
    row = db.execute("SELECT * FROM receipts WHERE household_id=? AND id=?", (hid, rid)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy hóa đơn.")
    return row


@router.get("/{rid}")
def view(hid: ID, rid: ID, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        r = receipt(db, hid, rid)
        return {
            "id": rid,
            **json.loads(r["draft"]),
            "confirmed": json.loads(r["confirmed"]) if r["confirmed"] else None,
        }


def editable(db, hid, rid, version):
    row = receipt(db, hid, rid)
    draft = json.loads(row["draft"])
    if row["confirmed"] or draft["version"] != version:
        raise HTTPException(409, "Hóa đơn đã thay đổi hoặc đã nhập kho.")
    return draft


@router.put("/{rid}")
def edit(hid: ID, rid: ID, data: Edit, request: Request):
    with transaction(write=True) as db:
        authorize(db, request, hid)
        draft = editable(db, hid, rid, data.version)
        draft.update(items=data.model_dump(mode="json")["items"], version=data.version + 1)
        db.execute("UPDATE receipts SET draft=? WHERE id=?", (json.dumps(draft), rid))
        return draft


@router.post("/{rid}/confirm")
def confirm(hid: ID, rid: ID, data: Confirm, request: Request):
    with transaction(write=True) as db:
        uid, _ = authorize(db, request, hid)

        def apply():
            draft = editable(db, hid, rid, data.version)
            if not draft["items"]:
                raise HTTPException(422, "Hãy kiểm tra và xác nhận từng dòng đã sửa.")
            imported = [receive(db, hid, uid, BatchInput.model_validate(item)) for item in draft["items"]]
            result = {"receipt_id": rid, "batches": imported}
            db.execute("UPDATE receipts SET confirmed=? WHERE id=?", (json.dumps(result), rid))
            return result

        return once(db, hid, uid, data.request_key, f"receipt:{rid}", data, apply)
