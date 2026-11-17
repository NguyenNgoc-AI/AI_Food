"""Danh mục và quy đổi chính xác cho luồng nhập tay, OCR và kho."""

import unicodedata
from difflib import SequenceMatcher
from fractions import Fraction
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import current_user
from ..db import transaction

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])
ID = Annotated[int, Field(gt=0, le=2**63 - 1)]
Amount = Annotated[str, Field(max_length=32, pattern=r"^[0-9]+(?:\.[0-9]+)?$")]
Key = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Unit = Literal["g", "kg", "ml", "l", "quả"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pack(Input):
    quantity: Amount
    unit: Unit


class Quantity(Input):
    product_id: ID
    quantity: Amount
    unit: Literal["g", "kg", "ml", "l", "quả", "hộp", "bó", "gói"]
    pack: Pack | None = None


def name_key(name):
    return unicodedata.normalize("NFC", " ".join(name.split()).casefold())


def convert(db, data, *, allow_zero=False):
    product = db.execute("SELECT * FROM food_products WHERE id=?", (data.product_id,)).fetchone()
    if not product:
        raise HTTPException(404, "Không tìm thấy thực phẩm.")
    amount = Fraction(data.quantity)
    unit = data.unit
    packaged = unit in {"hộp", "bó", "gói"}
    if packaged != bool(data.pack):
        raise HTTPException(422, "Hãy kiểm tra quy cách của dòng nhập.")
    if packaged:
        if Fraction(data.pack.quantity) <= 0:
            raise HTTPException(422, "Quy cách phải dương.")
        amount *= Fraction(data.pack.quantity)
        unit = data.pack.unit
    factor = db.execute(
        "SELECT ticks FROM catalog_units WHERE code=? AND base=?", (unit, product["base_unit"])
    ).fetchone()
    if not factor:
        raise HTTPException(422, "Đơn vị khác nhóm.")
    ticks = amount * factor[0]
    if ticks.denominator != 1 or not (0 if allow_zero else 1) <= ticks <= 2**63 - 1:
        raise HTTPException(422, "Lượng ngoài giới hạn hoặc không chia hết cho bước lưu.")
    return int(ticks)


def lookup(db, text):
    key = name_key(text)
    rows = db.execute(
        "SELECT p.*, p.name_key term FROM food_products p UNION ALL "
        "SELECT p.*, a.alias_key FROM food_products p JOIN food_aliases a ON p.id=a.product_id "
        "WHERE a.review_status='approved'"
    ).fetchall()
    exact, suggested = {}, {}
    for row in rows:
        info = {k: row[k] for k in ("id", "name", "category", "base_unit")}
        if not key or row["term"] == key:
            exact[row["id"]] = info
        elif key in row["term"] or SequenceMatcher(None, key, row["term"]).ratio() >= 0.72:
            suggested[row["id"]] = info
    return {"matches": list(exact.values()), "suggestions": [] if exact else list(suggested.values())[:20]}


@router.get("/products")
def products(request: Request, q: Annotated[str, Field(max_length=120)] = ""):
    with transaction() as db:
        current_user(db, request)
        return lookup(db, q)


@router.post("/preview")
def preview(data: Quantity, request: Request):
    with transaction() as db:
        current_user(db, request)
        return {"ticks": str(convert(db, data))}
