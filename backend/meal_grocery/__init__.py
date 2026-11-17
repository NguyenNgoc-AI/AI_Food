import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from ..audit_config import once, today
from ..catalog import ID, Input, Key
from ..db import transaction
from ..dietary_recipes import eligible, profiles
from ..households import authorize
from ..inventory import batches, usable
from ..recommendation import Eaters

router = APIRouter(prefix="/api/households/{hid}", tags=["Meal & grocery"])


class Plan(Eaters):
    request_key: Key
    recipe_id: ID
    day: date
    meal: Literal["sáng", "trưa", "tối", "phụ"]


def save(db, hid, data, mid=None):
    settings = profiles(db, hid, data.participants)
    recipe = db.execute("SELECT * FROM recipes WHERE id=?", (data.recipe_id,)).fetchone()
    if not recipe or not eligible(recipe, settings):
        raise HTTPException(422, "Món chưa đáp ứng điều kiện của nhóm.")
    params = (
        data.recipe_id,
        data.day.isoformat(),
        data.meal,
        data.servings,
        json.dumps(sorted(set(data.participants))),
    )
    if mid is None:
        mid = db.execute(
            "INSERT INTO meal_plans(recipe_id,day,meal,servings,participants,household_id) VALUES (?,?,?,?,?,?)",
            (*params, hid),
        ).lastrowid
    elif not db.execute(
        "UPDATE meal_plans SET recipe_id=?,day=?,meal=?,servings=?,participants=? WHERE id=? AND household_id=?",
        (*params, mid, hid),
    ).rowcount:
        raise HTTPException(404, "Không tìm thấy bữa ăn.")
    return {"id": mid}


@router.post("/meals", status_code=201)
def add(hid: ID, data: Plan, request: Request):
    with transaction(write=True) as db:
        uid, _ = authorize(db, request, hid)
        return once(db, hid, uid, data.request_key, "meal", data, lambda: save(db, hid, data))


@router.put("/meals/{mid}")
def edit(hid: ID, mid: ID, data: Plan, request: Request):
    with transaction(write=True) as db:
        uid, _ = authorize(db, request, hid)
        return once(db, hid, uid, data.request_key, f"meal:{mid}", data, lambda: save(db, hid, data, mid))


@router.delete("/meals/{mid}")
def remove(hid: ID, mid: ID, request: Request):
    with transaction(write=True) as db:
        authorize(db, request, hid)
        if not db.execute("DELETE FROM meal_plans WHERE household_id=? AND id=?", (hid, mid)).rowcount:
            raise HTTPException(404, "Không tìm thấy bữa ăn.")
        return {"ok": True}


@router.get("/meals")
def meals(hid: ID, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        return [
            {**dict(row), "participants": json.loads(row["participants"])}
            for row in db.execute("SELECT * FROM meal_plans WHERE household_id=? ORDER BY day,id", (hid,))
        ]


@router.get("/groceries")
def groceries(hid: ID, start: date, end: date, request: Request):
    if start > end:
        raise HTTPException(422, "Khoảng ngày không hợp lệ.")
    with transaction() as db:
        authorize(db, request, hid)
        return shortage(db, hid, start, end)


def shortage(db, hid, start, end):
    stock = [dict(b) for b in batches(db, hid)]
    demand = db.execute(
        "SELECT m.day,i.product_id,p.name,p.base_unit,m.servings,i.ticks_per_serving FROM meal_plans m "
        "JOIN ingredients i ON i.recipe_id=m.recipe_id JOIN food_products p ON p.id=i.product_id "
        "WHERE household_id=? AND m.day BETWEEN ? AND ? ORDER BY m.day,m.id",
        (hid, str(start), str(end)),
    )
    missing = {}
    for row in demand:
        need = row["servings"] * row["ticks_per_serving"]
        p = row["product_id"]
        for b in stock:
            if b["product_id"] == p and usable(b, max(row["day"], str(today()))):
                used = min(b["ticks"], need)
                need -= used
                b["ticks"] -= used
        if need:
            item = missing.setdefault(
                p, {"product_id": p, "name": row["name"], "unit": row["base_unit"], "ticks": 0}
            )
            item["ticks"] += need
    return [{**v, "ticks": str(v["ticks"])} for v in missing.values()]


class Shopping(Input):
    items: list[dict[str, str | int]]
    request_key: Key
    start: date
    end: date


@router.post("/grocery-lists", status_code=201)
def confirm_list(hid: ID, data: Shopping, request: Request):
    if data.start > data.end:
        raise HTTPException(422, "Khoảng ngày không hợp lệ.")
    with transaction(write=True) as db:
        uid, _ = authorize(db, request, hid)

        def apply():
            items = shortage(db, hid, data.start, data.end)
            if items != data.items:
                raise HTTPException(409, "Nhu cầu mua đã thay đổi, xem lại danh sách.")
            lid = db.execute(
                "INSERT INTO grocery_lists(household_id,start,end) VALUES (?,?,?)",
                (hid, str(data.start), str(data.end)),
            ).lastrowid
            db.executemany(
                "INSERT INTO grocery_items(list_id,product_id,ticks) VALUES (?,?,?)",
                [(lid, i["product_id"], i["ticks"]) for i in items],
            )
            return {"id": lid, "items": items}

        return once(db, hid, uid, data.request_key, "shopping_list", data, apply)


@router.get("/grocery-lists")
def saved_lists(hid: ID, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        return [
            {
                **dict(row),
                "items": [
                    dict(i)
                    for i in db.execute(
                        "SELECT product_id,ticks,purchased FROM grocery_items WHERE list_id=?", (row["id"],)
                    )
                ],
            }
            for row in db.execute(
                "SELECT id,start,end FROM grocery_lists WHERE household_id=? ORDER BY id DESC", (hid,)
            )
        ]


class Purchased(Input):
    purchased: bool


@router.put("/grocery-lists/{lid}/items/{pid}")
def purchased(hid: ID, lid: ID, pid: ID, data: Purchased, request: Request):
    with transaction(write=True) as db:
        authorize(db, request, hid)
        changed = db.execute(
            "UPDATE grocery_items SET purchased=? WHERE product_id=? AND list_id=? AND EXISTS "
            "(SELECT 1 FROM grocery_lists WHERE id=? AND household_id=?)",
            (data.purchased, pid, lid, lid, hid),
        )
        if not changed.rowcount:
            raise HTTPException(404, "Không tìm thấy mục mua sắm.")
        return {"purchased": data.purchased}
