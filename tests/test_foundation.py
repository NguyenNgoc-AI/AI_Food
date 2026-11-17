"""G1 integration tests against Uvicorn and a fresh SQLite database."""
import json
import sqlite3
import threading
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
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],1)
            self.assertFalse(conn.execute("PRAGMA foreign_key_check").fetchall())
            self.assertFalse(conn.execute("SELECT 1 FROM households WHERE name='orphan'").fetchone())
        self.assertEqual(self.ok("/me",cookie=cookie),me)

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
