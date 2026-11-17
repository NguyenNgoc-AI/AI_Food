"""G1 integration tests against Uvicorn and a fresh SQLite database."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.db import migrate, transaction
from live_server import LiveServer


class Foundation(LiveServer):
    def call(self, path, method="GET", cookie="", data=None, csrf=True):
        headers = {"Cookie": cookie, "Content-Type": "application/json"}
        if csrf:
            headers["X-SmartFood"] = "1"
        req = Request(self.url + "/api" + path, method=method, headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
        try:
            res = urlopen(req, timeout=15)
        except HTTPError as error:
            res = error
        with res:
            return res.status, json.load(res), res.headers

    def ok(self, path, method="GET", cookie="", data=None):
        status, body, _ = self.call(path, method, cookie, data)
        self.assertIn(status, (200, 201), body)
        return body

    def account(self, suffix):
        username = self._testMethodName[5:24] + "_" + suffix
        data = {"username":username, "password":"integration-only-pass"}
        self.ok("/auth/register", "POST", data=data)
        status, _, headers = self.call("/auth/login", "POST", data=data)
        self.assertEqual(status, 200)
        cookie = SimpleCookie(headers["Set-Cookie"])["smartfood_session"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"].lower(), "strict")
        return "smartfood_session=" + cookie.value

    def home(self, cookie):
        h = self.ok("/households", "POST", cookie, {"name":"Nhà thử nghiệm"})["id"]
        return f"/households/{h}"

    def invite(self, home, owner):
        return self.ok(home + "/invitations", "POST", owner)

    def enroll(self, home, owner, member):
        code = self.invite(home, owner)["code"]
        self.ok("/households/join", "POST", member, {"code":code})
        return self.ok("/me", cookie=member)["id"]

    def race(self, *operations):
        barrier = threading.Barrier(len(operations))
        def start(fn):
            barrier.wait(timeout=8)
            return fn()[0]
        with ThreadPoolExecutor(len(operations)) as pool:
            return sorted(pool.map(start, operations))

    def test_login_logout_csrf(self):
        self.assertEqual(self.call("/me")[0], 401)
        cookie = self.account("one")
        self.assertEqual(self.call("/auth/logout", "POST", cookie, csrf=False)[0], 403)
        self.assertIsNone(self.ok("/me", cookie=cookie)["household_id"])
        self.assertEqual(self.call("/auth/login","POST",data={
            "username":self.ok("/me",cookie=cookie)["username"], "password":"incorrect-password"})[0],401)
        self.ok("/auth/logout","POST",cookie)
        self.assertEqual(self.call("/me",cookie=cookie)[0],401)

    def test_schema_rollback(self):
        migrate()
        cookie = self.account("aa")
        self.home(cookie)
        me = self.ok("/me", cookie=cookie)
        with self.assertRaises(sqlite3.IntegrityError), transaction(write=True) as conn:
            conn.execute("INSERT INTO households(name,owner_id) VALUES ('orphan',?)",(me["id"],))
        with self.assertRaises(sqlite3.IntegrityError), transaction(write=True) as conn:
            conn.execute("DELETE FROM memberships WHERE user_id=?", (me["id"],))
        with self.assertRaises(sqlite3.IntegrityError), transaction(write=True) as conn:
            conn.execute("INSERT INTO memberships VALUES (?,?)",(me["id"], me["household_id"]))
        with transaction() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],2)
            self.assertFalse(conn.execute("PRAGMA foreign_key_check").fetchall())
            self.assertFalse(conn.execute("SELECT 1 FROM households WHERE name='orphan'").fetchone())
        self.assertEqual(self.ok("/me",cookie=cookie),me)

    def test_existing_database_upgrade(self):
        from backend.db import ROOT
        with TemporaryDirectory() as directory:
            path = Path(directory) / "v1.sqlite3"
            with sqlite3.connect(path) as db:
                db.executescript((ROOT / "migrations/001_foundation.sql").read_text(encoding="utf-8"))
                db.execute("INSERT INTO users VALUES (1,'existing','fixture')")
                db.execute("PRAGMA user_version=1")
            db.close()
            with patch.dict("os.environ", SMARTFOOD_DB=str(path)):
                migrate()
                migrate()
                with transaction() as db:
                    self.assertEqual(db.execute("SELECT username FROM users").fetchone()[0], "existing")
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0], 0)

    def test_login_throttle_window_and_concurrency(self):
        cookie = self.account("rate")
        username = self.ok("/me", cookie=cookie)["username"]
        def attempt(password):
            return self.call("/auth/login", "POST", data={"username":username.upper(), "password":password})
        for _ in range(9):
            self.assertEqual(attempt("incorrect-password")[0], 401)
        self.assertEqual(self.race(lambda:attempt("bad-password"),lambda:attempt("bad-password")), [401,429])
        code, _, headers = attempt("integration-only-pass")
        self.assertEqual(code, 429)
        self.assertGreater(int(headers["Retry-After"]), 0)
        with transaction(write=True) as db:
            db.execute("UPDATE login_attempts SET started=0 WHERE bucket=?", ("user:" + username,))
        self.assertEqual(attempt("integration-only-pass")[0], 200)

    def test_invitation_expires_waiting_for_lock(self):
        owner, guest = self.account("owner"), self.account("guest")
        home = self.home(owner)
        invite = self.invite(home, owner)
        entered = threading.Event()
        clock = 100
        @contextmanager
        def observed(write=False):
            entered.set()
            with transaction(write=write) as conn:
                yield conn
        with ThreadPoolExecutor(1) as pool, patch("backend.households.transaction", observed), \
             patch("backend.households.time") as local_clock:
            local_clock.time.side_effect = lambda: clock
            with transaction(write=True) as db:
                db.execute("UPDATE invitations SET expires_at=101 WHERE id=?", (invite["id"],))
                result = pool.submit(self.call, "/households/join", "POST", guest, {"code":invite["code"]})
                self.assertTrue(entered.wait(4))
                clock = 101
            self.assertEqual(result.result()[0], 400)
        self.assertIsNone(self.ok("/me", cookie=guest)["household_id"])

    def test_client_throttle_applies_across_names(self):
        import time
        with transaction(write=True) as db:
            db.execute("INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)",
                       ("client:127.0.0.1", int(time.time()), 49))
        try:
            for name, expected in [("absent_one",401), ("absent_two",429)]:
                code, _, _ = self.call("/auth/login", "POST", data={"username":name, "password":"wrong-password"})
                self.assertEqual(code, expected)
        finally:
            with transaction(write=True) as db:
                db.execute("DELETE FROM login_attempts WHERE bucket='client:127.0.0.1'")

    def ordered_writes(self, first, second):
        locked, contender = threading.Event(), threading.Event()
        @contextmanager
        def observed(write=False):
            if locked.is_set():
                contender.set()
            with transaction(write=write) as db:
                if not locked.is_set():
                    locked.set()
                    self.assertTrue(contender.wait(5))
                yield db
        with patch("backend.households.transaction", observed), ThreadPoolExecutor(2) as pool:
            one = pool.submit(first)
            self.assertTrue(locked.wait(5))
            two = pool.submit(second)
            return one.result()[0], two.result()[0]

    def test_revoke_join_orderings(self):
        owner, guest = self.account("owner"), self.account("guest")
        home = self.home(owner)
        for revoke_first in (True, False):
            invite = self.invite(home, owner)
            def revoke():
                return self.call(home+"/invitations/"+str(invite["id"]), "DELETE", owner)
            def join():
                return self.call("/households/join", "POST", guest, {"code":invite["code"]})
            if revoke_first:
                self.assertEqual(self.ordered_writes(revoke, join), (200,400))
                self.assertIsNone(self.ok("/me", cookie=guest)["household_id"])
            else:
                self.assertEqual(self.ordered_writes(join, revoke), (200,404))
                self.assertEqual(len(self.ok(home,cookie=owner)["members"]), 2)

    def test_transfer_remove_orderings(self):
        owner, member = self.account("owner"), self.account("member")
        home = self.home(owner)
        for remove_first in (True, False):
            uid = self.enroll(home, owner, member)
            def transfer():
                return self.call(home+"/owner/"+str(uid), "POST", owner)
            def remove():
                return self.call(home+"/members/"+str(uid), "DELETE", owner)
            if remove_first:
                self.assertEqual(self.ordered_writes(remove, transfer), (200,404))
                self.assertIsNone(self.ok("/me", cookie=member)["household_id"])
            else:
                self.assertEqual(self.ordered_writes(transfer, remove), (200,409))
                self.assertEqual(self.ok(home,cookie=member)["owner_id"], uid)

    def test_transfer_rolls_back_if_audit_fails(self):
        from backend import households
        from starlette.requests import Request as ServerRequest
        owner, member = self.account("owner"), self.account("member")
        home = self.home(owner)
        uid = self.enroll(home,owner,member)
        before = self.ok(home,cookie=owner)
        req = ServerRequest({"type":"http", "headers":[(b"cookie",owner.encode())]})
        with patch.object(households,"audit",side_effect=RuntimeError("audit fixture")):
            with self.assertRaisesRegex(RuntimeError,"audit fixture"):
                households.transfer(before["id"],uid,req)
        self.assertEqual(self.ok(home,cookie=owner),before)

    def test_expired_session_and_duplicate_user(self):
        cookie = self.account("owner")
        me = self.ok("/me", cookie=cookie)
        credentials = {"username": me["username"].upper(), "password": "different-password"}
        self.assertEqual(self.call("/auth/register", "POST", data=credentials)[0], 409)
        with transaction(write=True) as conn:
            conn.execute("UPDATE sessions SET expires_at=0 WHERE user_id=?", (me["id"],))
            stored = conn.execute("SELECT token_hash FROM sessions WHERE user_id=?", (me["id"],)).fetchone()[0]
            self.assertNotEqual(stored, cookie.split("=", 1)[1])
        self.assertEqual(self.call("/me", cookie=cookie)[0], 401)

    def test_cross_household_and_revoke(self):
        owner, other, member = [self.account(k) for k in ("aa","bb","cc")]
        a, b = self.home(owner), self.home(other)
        uid = self.enroll(a,owner,member)
        self.assertEqual(self.call(b,cookie=member)[0],404)
        self.assertEqual(self.call(b+"/invitations","POST",member)[0],404)
        self.assertEqual(self.call(a+"/invitations","POST",member)[0],403)
        self.assertEqual(self.call(a+"/owner/"+str(uid),"POST",member)[0],403)
        self.assertEqual(self.call("/households","POST",member,{"name":"another"})[0],409)
        self.ok(a+"/members/"+str(uid),"DELETE",owner)
        self.assertEqual(self.call(a,cookie=member)[0],404)
        self.assertIsNone(self.ok("/me",cookie=member)["household_id"])

    def test_owner_transfer_and_leave(self):
        owner, member = self.account("a"), self.account("b")
        home = self.home(owner)
        first = self.ok("/me",cookie=owner)["id"]
        next_owner = self.enroll(home,owner,member)
        self.assertEqual(self.call(home+"/members/"+str(first),"DELETE",owner)[0],409)
        self.ok(home+"/owner/"+str(next_owner),"POST",owner)
        self.assertEqual(self.call(home+"/invitations","POST",owner)[0],403)
        self.assertEqual(self.ok(home,cookie=member)["owner_id"],next_owner)
        self.ok(home+"/members/"+str(first),"DELETE",owner)
        self.assertEqual(self.call(home,cookie=owner)[0],404)
        with transaction() as conn:
            row = conn.execute("SELECT * FROM audit_events WHERE action='transfer_owner' AND actor_id=?",(first,)).fetchone()
            self.assertEqual((row["target_id"],row["outcome"]),(next_owner,"success"))

    def test_invite_limits(self):
        owner, guest = self.account("a"), self.account("b")
        home = self.home(owner)
        revoked, expired = self.invite(home,owner), self.invite(home,owner)
        self.ok(home+"/invitations/"+str(revoked["id"]),"DELETE",owner)
        with transaction(write=True) as conn:
            conn.execute("UPDATE invitations SET expires_at=0 WHERE id=?",(expired["id"],))
            value = conn.execute("SELECT code_hash FROM invitations WHERE id=?",(expired["id"],)).fetchone()[0]
            self.assertNotEqual(value,expired["code"])
        for code in [revoked["code"],expired["code"]] + ["invalid"]*8:
            self.assertEqual(self.call("/households/join","POST",guest,{"code":code})[0],400)
        self.assertEqual(self.call("/households/join","POST",guest,{"code":"invalid"})[0],429)

    def test_single_use_race(self):
        owner, x, y = [self.account(k) for k in ("a","b","c")]
        home = self.home(owner)
        code = self.invite(home,owner)["code"]
        def join(who):
            return self.call("/households/join","POST",who,{"code":code})
        self.assertEqual(self.race(lambda:join(x),lambda:join(y)),[200,400])
        self.assertEqual(len(self.ok(home,cookie=owner)["members"]),2)

    def test_transfer_race(self):
        owner, x, y = [self.account(k) for k in ("a","b","c")]
        home = self.home(owner)
        a,b = [self.enroll(home,owner,who) for who in (x,y)]
        def move(uid):
            return self.call(home+"/owner/"+str(uid),"POST",owner)
        self.assertEqual(self.race(lambda:move(a),lambda:move(b)),[200,403])
        details = self.ok(home,cookie=owner)
        self.assertIn(details["owner_id"],(a,b))
        with transaction() as conn:
            count = conn.execute("SELECT count(*) FROM audit_events WHERE household_id=? AND action='transfer_owner'",
                                 (details["id"],)).fetchone()[0]
            self.assertEqual(count,1)
