"""python -m backend.catalog.import_reviewed products.json — curated local operator input."""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..db import migrate, transaction
from . import ID, Input, name_key


class Product(Input):
    id: ID
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    category: str = Field(min_length=1, max_length=100, pattern=r"\S")
    base_unit: Literal["g", "ml", "quả"]
    source: str = Field(min_length=1, max_length=200, pattern=r"\S")
    approved_aliases: list[str] = Field(default_factory=list, max_length=100)


def import_products(records):
    products = [Product.model_validate(r) for r in records]
    with transaction(write=True) as db:
        for p in products:
            db.execute(
                "INSERT INTO food_products VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name,name_key=excluded.name_key,category=excluded.category,base_unit=excluded.base_unit",
                (p.id, p.name.strip(), name_key(p.name), p.category.strip(), p.base_unit),
            )
            db.execute("DELETE FROM food_aliases WHERE product_id=?", (p.id,))
            for alias in {name_key(s) for s in p.approved_aliases}:
                if not alias or len(alias) > 120:
                    raise ValueError("Bí danh trống hoặc quá dài.")
                db.execute("INSERT INTO food_aliases VALUES (?,?,?,'approved')", (p.id, alias, p.source))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("path", type=Path)
    args = cli.parse_args()
    migrate()
    import_products(json.loads(args.path.read_text(encoding="utf-8")))
