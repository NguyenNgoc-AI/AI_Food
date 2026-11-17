import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ..auth import current_user
from ..catalog import ID, Input, name_key
from ..db import transaction

router = APIRouter(prefix="/api", tags=["Dietary & recipes"])
Label = Annotated[str, Field(min_length=1, max_length=80, pattern=r"\S")]


class Profile(Input):
    allergens: list[Label] = Field(max_length=30)
    required_tags: list[Label] = Field(max_length=30)
    liked_products: list[ID] = Field(max_length=100)


@router.put("/me/dietary")
def save_profile(data: Profile, request: Request):
    with transaction(write=True) as db:
        uid = current_user(db, request)["id"]
        for field in ("allergens", "required_tags"):
            setattr(data, field, sorted({name_key(value) for value in getattr(data, field)}))
        db.execute(
            "INSERT INTO dietary_profiles VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET settings=excluded.settings",
            (uid, data.model_dump_json()),
        )
        return data


@router.get("/me/dietary")
def profile(request: Request):
    with transaction() as db:
        uid = current_user(db, request)["id"]
        row = db.execute("SELECT settings FROM dietary_profiles WHERE user_id=?", (uid,)).fetchone()
        return json.loads(row[0]) if row else None


@router.get("/recipes")
def recipes(request: Request):
    with transaction() as db:
        current_user(db, request)
        return [
            {
                **dict(r),
                "tags": json.loads(r["tags"]),
                "allergens": json.loads(r["allergens"]),
                "ingredients": ingredients(db, r["id"]),
            }
            for r in db.execute("SELECT * FROM recipes ORDER BY id")
        ]


def ingredients(db, rid):
    return [
        dict(r)
        for r in db.execute(
            "SELECT product_id,p.name,p.base_unit,ticks_per_serving FROM ingredients i "
            "JOIN food_products p ON p.id=i.product_id WHERE recipe_id=? ORDER BY product_id",
            (rid,),
        )
    ]


def profiles(db, hid, participants):
    settings = []
    for uid in set(participants):
        row = db.execute(
            "SELECT p.settings FROM memberships m LEFT JOIN dietary_profiles p ON p.user_id=m.user_id "
            "WHERE m.household_id=? AND m.user_id=?",
            (hid, uid),
        ).fetchone()
        if not row:
            raise HTTPException(422, "Người tham gia phải thuộc hộ hiện tại.")
        if not row[0]:
            raise HTTPException(409, "Chưa đủ thông tin ăn uống của người tham gia.")
        settings.append(json.loads(row[0]))
    return settings


def eligible(recipe, settings):
    # The local reference catalog declares only these allergen classes verified.
    verified = {"trứng", "sữa", "đậu phộng", "đậu nành", "lúa mì", "hải sản", "mè", "hạt cây"}
    allergens, tags = set(json.loads(recipe["allergens"])), set(json.loads(recipe["tags"]))
    return all(
        (not p["allergens"] or recipe["complete"] and set(p["allergens"]) <= verified)
        and not allergens.intersection(p["allergens"])
        and set(p["required_tags"]) <= tags
        for p in settings
    )
