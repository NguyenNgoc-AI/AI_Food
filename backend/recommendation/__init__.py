from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field

from ..audit_config import today
from ..catalog import ID, Input
from ..db import transaction
from ..dietary_recipes import eligible, ingredients, profiles
from ..households import authorize
from ..inventory import batches, usable

router = APIRouter(prefix="/api/households/{hid}/recommendations", tags=["Recommendation"])


class Eaters(Input):
    participants: list[ID] = Field(min_length=1, max_length=40)
    servings: int = Field(ge=1, le=100)


class Query(Eaters):
    method: Literal["content", "multi"] = "content"


@router.post("")
def recommend(hid: ID, data: Query, request: Request):
    with transaction() as db:
        authorize(db, request, hid)
        settings = profiles(db, hid, data.participants)
        available, urgent = {}, {}
        day = today()
        for b in batches(db, hid):
            if usable(b, day.isoformat()):
                p = b["product_id"]
                available[p] = available.get(p, 0) + b["ticks"]
                if b["expiry"] <= (day + timedelta(days=3)).isoformat():
                    urgent[p] = urgent.get(p, 0) + b["ticks"]
        likes = set().union(*(p["liked_products"] for p in settings))
        result = []
        for r in db.execute("SELECT * FROM recipes ORDER BY id"):
            if not eligible(r, settings):
                continue
            parts = ingredients(db, r["id"])
            if not parts:
                continue
            coverage = soon = liked = 0
            missing = []
            for item in parts:
                p = item["product_id"]
                need = item["ticks_per_serving"] * data.servings
                have = available.get(p, 0)
                coverage += min(have, need) / need
                soon += min(urgent.get(p, 0), need) / need
                liked += p in likes
                if need > have:
                    missing.append({"product_id": p, "unit": item["base_unit"], "ticks": str(need - have)})
            size = len(parts)
            base = (coverage * 0.8 + liked * 0.2) / size
            score = (
                base
                if data.method == "content"
                else 0.6 * base + 0.25 * soon / size + 0.15 * (1 - len(missing) / size)
            )
            result.append(
                {
                    "recipe_id": r["id"],
                    "name": r["name"],
                    "score": round(score, 6),
                    "coverage": coverage / size,
                    "soon_coverage": soon / size,
                    "missing": missing,
                }
            )
        result.sort(key=lambda item: (-item["score"], item["recipe_id"]))
        return {
            "method": data.method,
            "recipes": result,
            "reason": None if result else "Chưa có món đủ điều kiện cho nhóm.",
        }
