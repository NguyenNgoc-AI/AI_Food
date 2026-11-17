"""Import a human-reviewed, immutable recipe version. Run as a local operator."""

import argparse
import json
from pathlib import Path

from pydantic import Field

from ..catalog import Input, Quantity, convert, name_key
from ..db import migrate, transaction
from . import Label


class ReviewedRecipe(Input):
    name: Label
    source: Label
    allergens: list[Label] = Field(max_length=30)
    tags: list[Label] = Field(max_length=30)
    complete: bool
    per_serving: list[Quantity] = Field(min_length=1, max_length=100)


def import_recipes(records):
    recipes = [ReviewedRecipe.model_validate(r) for r in records]
    with transaction(write=True) as db:
        for r in recipes:
            rid = db.execute(
                "INSERT INTO recipes(name,allergens,tags,complete,source) VALUES (?,?,?,?,?)",
                (
                    r.name,
                    json.dumps(sorted({name_key(s) for s in r.allergens})),
                    json.dumps(sorted({name_key(s) for s in r.tags})),
                    r.complete,
                    r.source,
                ),
            ).lastrowid
            db.executemany(
                "INSERT INTO ingredients VALUES (?,?,?)",
                [(rid, i.product_id, convert(db, i)) for i in r.per_serving],
            )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("path", type=Path)
    args = cli.parse_args()
    migrate()
    import_recipes(json.loads(args.path.read_text(encoding="utf-8")))
