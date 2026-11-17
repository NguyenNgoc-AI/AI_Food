"""HTTP acceptance for local backend, isolated SQLite and a real Windows OCR example."""

import json
import os
import sqlite3
import subprocess
import unicodedata
from datetime import timedelta
from unittest import skipUnless
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import test_foundation as g1
from live_server import LiveServer

from backend.audit_config import today
from backend.catalog.import_reviewed import import_products
from backend.db import transaction


class Backend(LiveServer):
    call = g1.Foundation.call
    ok = g1.Foundation.ok
    account = g1.Foundation.account
    home = g1.Foundation.home
    enroll = g1.Foundation.enroll
    invite = g1.Foundation.invite
    race = g1.Foundation.race

    def setUp(self):
        self.cookie = self.account("main")
        self.h = self.home(self.cookie)
        self.date = str(today())
        self.later = str(today() + timedelta(days=12))

    def post(self, path, data, method="POST"):
        return self.ok(self.h + path, method, self.cookie, data)

    def get(self, path):
        return self.ok(self.h + path, cookie=self.cookie)

    def batch(self, q="1", unit="kg", key="rice", **rest):
        return self.post(
            "/inventory/batches",
            {
                "product_id": 1,
                "quantity": q,
                "unit": unit,
                "request_key": key,
                "received": self.date,
                "expiry": self.later,
                "expiry_source": "label",
            }
            | rest,
        )["batch_id"]

    def movement(self, path, key, amount, **rest):
        return self.call(
            self.h + path,
            "POST",
            self.cookie,
            {
                "request_key": key,
                "product_id": 1,
                "quantity": amount,
                "unit": "g",
                "kind": "consume",
                "reason": "bữa trưa",
            }
            | rest,
        )

    def test_catalog_aliases_and_units(self):
        import_products(
            [
                {
                    "id": 55,
                    "name": "Sữa tươi",
                    "category": "Ví dụ",
                    "base_unit": "ml",
                    "source": "fixture",
                    "approved_aliases": ["Sữa tươi"],
                }
            ]
        )
        from urllib.parse import quote

        query = quote(unicodedata.normalize("NFD", "  SỮA   TƯƠI "))
        matches = self.ok("/catalog/products?q=" + query, cookie=self.cookie)["matches"]
        self.assertEqual({m["id"] for m in matches}, {3, 55})
        for qty, unit, product in [
            ("0", "g", 1),
            ("0.0011", "g", 1),
            ("0.5", "quả", 2),
            ("1", "l", 1),
            ("1", "hộp", 3),
            ("9223372036854775808", "g", 1),
        ]:
            self.assertEqual(
                self.call(
                    "/catalog/preview",
                    "POST",
                    self.cookie,
                    {"product_id": product, "quantity": qty, "unit": unit},
                )[0],
                422,
            )
        self.assertEqual(
            self.ok(
                "/catalog/preview",
                "POST",
                self.cookie,
                {"product_id": 3, "quantity": "2", "unit": "hộp", "pack": {"quantity": "180", "unit": "ml"}},
            )["ticks"],
            "360000",
        )
        self.batch()
        with self.assertRaises(sqlite3.IntegrityError), transaction(write=True) as db:
            db.execute("UPDATE food_products SET base_unit='ml' WHERE id=1")
        with self.assertRaises(sqlite3.IntegrityError), transaction(write=True) as db:
            db.execute("UPDATE catalog_units SET ticks=2 WHERE code='g'")

    def test_inventory_race_retry_reconcile(self):
        member = self.account("other")
        self.enroll(self.h, self.cookie, member)
        bid = self.batch()
        path = f"/inventory/batches/{bid}/movements"

        def consume(cookie, key, amount):
            return self.call(
                self.h + path,
                "POST",
                cookie,
                {
                    "request_key": key,
                    "kind": "consume",
                    "reason": "bữa ăn",
                    "product_id": 1,
                    "quantity": amount,
                    "unit": "g",
                },
            )

        self.assertEqual(
            self.race(lambda: consume(self.cookie, "a", "600"), lambda: consume(member, "b", "500")),
            [200, 409],
        )
        state = self.get(f"/inventory/batches/{bid}/ledger")
        self.assertEqual(len(state["movements"]), 2)
        self.assertEqual(state["ticks"], state["ledger_ticks"])
        key, cookie, amount = (
            ("a", self.cookie, "600") if state["ticks"] == "400000" else ("b", member, "500")
        )
        self.assertEqual(consume(cookie, key, amount)[1]["ticks"], state["ticks"])
        self.assertEqual(consume(cookie, key, "1")[0], 409)
        count = self.post(
            f"/inventory/batches/{bid}/count-preview", {"product_id": 1, "quantity": "0", "unit": "g"}
        )
        self.assertEqual(int(count["difference_ticks"]), -int(state["ticks"]))
        self.assertEqual(self.movement(path, "adjust", "0", kind="adjust", expected_version=1)[0], 409)
        self.assertEqual(
            self.movement(path, "adjust", "0", kind="adjust", expected_version=2)[1]["ticks"], "0"
        )

    def test_alert_fifo_and_waste(self):
        first = self.batch(received=str(today() - timedelta(days=2)))
        near = self.batch(key="near", expiry=self.date)
        expired = self.batch(key="expired", expiry=str(today() - timedelta(days=1)))
        fifo = self.get("/inventory/fifo/1")
        self.assertEqual(fifo, {"batch_ids": [first, near], "earlier_expiry_ids": [near]})
        self.assertEqual({a["reason"] for a in self.get("/alerts")}, {"due_soon", "past_date"})
        self.post(f"/alerts/{expired}/past_date/read", None, "PUT")
        self.assertTrue(next(a["read"] for a in self.get("/alerts") if a["batch_id"] == expired))
        self.assertEqual(self.get("/reports")["by_product"][0]["wasted"], "0")
        path = f"/inventory/batches/{expired}/movements"
        self.assertEqual(self.movement(path, "c", "1")[0], 409)
        self.assertEqual(self.movement(path, "w", "20", kind="waste")[0], 200)
        self.assertEqual(self.get("/reports")["by_product"][0]["wasted"], "20000")
        self.assertIn("last_synced_at", self.get("/inventory/snapshot"))

    def test_restrictions_meals_groceries(self):
        self.batch("30", "g")
        uid = self.ok("/me", cookie=self.cookie)["id"]
        query = {"participants": [uid], "servings": 1}
        self.assertEqual(self.call(self.h + "/recommendations", "POST", self.cookie, query)[0], 409)
        self.ok(
            "/me/dietary",
            "PUT",
            self.cookie,
            {"allergens": ["trứng"], "required_tags": [], "liked_products": [4]},
        )
        for method in ("content", "multi"):
            ranked = self.post("/recommendations", query | {"method": method})["recipes"]
            self.assertEqual([r["recipe_id"] for r in ranked], [1])
        with transaction(write=True) as db:
            db.execute("UPDATE recipes SET complete=0 WHERE id=1")
        try:
            self.assertFalse(self.post("/recommendations", query)["recipes"])
        finally:
            with transaction(write=True) as db:
                db.execute("UPDATE recipes SET complete=1 WHERE id=1")
        self.post("/meals", query | {"recipe_id": 1, "day": self.date, "meal": "trưa", "request_key": "meal"})
        items = self.get(f"/groceries?start={self.date}&end={self.date}")
        self.assertEqual({i["product_id"]: i["ticks"] for i in items}, {1: "20000", 4: "30000"})
        lid = self.post(
            "/grocery-lists", {"request_key": "shop", "start": self.date, "end": self.date, "items": items}
        )["id"]
        self.post(f"/grocery-lists/{lid}/items/4", {"purchased": True}, "PUT")
        self.assertEqual(self.get("/inventory/batches")[0]["ticks"], "30000")
        self.assertTrue(
            next(i["purchased"] for i in self.get("/grocery-lists")[0]["items"] if i["product_id"] == 4)
        )

    def test_review_lot_and_curated_recipe_import(self):
        from backend.dietary_recipes.import_reviewed import import_recipes

        bid = self.batch(expiry=None, expiry_source="unknown")
        self.assertEqual(self.get("/inventory/fifo/1")["batch_ids"], [])
        command = {
            "request_key": "verify",
            "expected_version": 1,
            "expiry": self.later,
            "expiry_source": "user",
            "flagged": False,
            "reason": "Kiểm tra nhãn lô",
        }
        self.post(f"/inventory/batches/{bid}/review", command, "PUT")
        self.assertEqual(self.get("/inventory/fifo/1")["batch_ids"], [bid])
        import_recipes(
            [
                {
                    "name": "Công thức kiểm thử",
                    "source": "fixture",
                    "allergens": [],
                    "tags": [],
                    "complete": False,
                    "per_serving": [{"product_id": 3, "quantity": "0.2", "unit": "l"}],
                }
            ]
        )
        recipes = self.ok("/recipes", cookie=self.cookie)
        self.assertTrue(
            any(
                r["source"] == "fixture" and r["ingredients"][0]["ticks_per_serving"] == 200000
                for r in recipes
            )
        )

    def test_two_households_and_revocation(self):
        bid = self.batch()
        outsider = self.account("visitor")
        self.home(outsider)
        for part in (
            "/inventory/batches",
            f"/inventory/batches/{bid}/ledger",
            "/meals",
            "/alerts",
            "/reports",
            "/receipts/1",
            "/grocery-lists",
        ):
            self.assertEqual(self.call(self.h + part, cookie=outsider)[0], 404)
        member = self.account("member")
        uid = self.enroll(self.h, self.cookie, member)
        self.ok(self.h + f"/members/{uid}", "DELETE", self.cookie)
        self.assertEqual(self.call(self.h + "/inventory/snapshot", cookie=member)[0], 404)

    def upload(self, raw):
        req = Request(
            self.url + "/api" + self.h + "/receipts",
            method="POST",
            data=raw,
            headers={"Content-Type": "image/png", "X-SmartFood": "1", "Cookie": self.cookie},
        )
        try:
            response = urlopen(req, timeout=35)
        except HTTPError as e:
            response = e
        with response:
            return response.status, json.load(response)

    @skipUnless(os.name == "nt", "OCR adapter is Windows local")
    def test_ocr_confirm_retries_and_atomicity(self):
        script = """Add-Type -AssemblyName System.Drawing
$b=[Drawing.Bitmap]::new(700,140)
$g=[Drawing.Graphics]::FromImage($b)
$g.Clear([Drawing.Color]::White)
$g.DrawString('Rice 2 kg',[Drawing.Font]::new('Arial',27),[Drawing.Brushes]::Black,20,30)
$m=[IO.MemoryStream]::new()
$b.Save($m,[Drawing.Imaging.ImageFormat]::Png)
[Convert]::ToBase64String($m.ToArray())"""
        import base64

        raw = base64.b64decode(subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", script]))
        self.assertEqual(self.upload(b"invalid")[0], 422)
        self.assertEqual(self.upload(b"\x89PNG\r\n\x1a\ninvalid")[0], 422)
        code, draft = self.upload(raw)
        self.assertEqual(code, 201, draft)
        self.assertTrue(any(s["quantity"] == "2" for s in draft["suggestions"]), draft)
        rid = draft["id"]
        self.assertIn(rid, self.upload(raw)[1]["possible_duplicates"])
        path = f"/receipts/{rid}"
        item = {"product_id": 1, "quantity": "1.5", "unit": "kg", "received": self.date}
        self.post(path, {"version": 1, "items": [item, item | {"unit": "ml"}]}, "PUT")
        self.assertEqual(
            self.call(
                self.h + path + "/confirm", "POST", self.cookie, {"version": 2, "request_key": "import"}
            )[0],
            422,
        )
        self.assertFalse(self.get("/inventory/batches"))
        self.post(path, {"version": 2, "items": [item]}, "PUT")
        payload = {"request_key": "import", "version": 3}
        got = self.post(path + "/confirm", payload)
        self.assertEqual(got, self.post(path + "/confirm", payload))
        self.assertEqual(self.get("/inventory/batches")[0]["ticks"], "1500000")
        self.assertEqual(
            self.call(self.h + path + "/confirm", "POST", self.cookie, payload | {"request_key": "again"})[0],
            409,
        )
