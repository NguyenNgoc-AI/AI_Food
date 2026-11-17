import hashlib
import hmac
import re
import secrets
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .db import transaction

router = APIRouter(prefix="/api")
COOKIE = "smartfood_session"
SESSION_SECONDS = 7 * 86400
LOGIN_WINDOW = 300


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,40}", value):
            raise ValueError("Tên đăng nhập gồm 3–40 chữ cái a–z, số, dấu chấm, gạch ngang hoặc gạch dưới.")
        return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def derive(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=3, maxmem=64 << 20).hex()


def current_user(conn, request):
    token = request.cookies.get(COOKIE, "")
    row = conn.execute(
        "SELECT u.id, u.username FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.expires_at>?", (digest(token), int(time.time()))
    ).fetchone()
    if not row:
        raise HTTPException(401, "Vui lòng đăng nhập.")
    expected_actor = request.headers.get("X-SmartFood-Actor")
    if expected_actor is not None and expected_actor != str(row["id"]):
        raise HTTPException(409, "Tài khoản đã thay đổi. Hãy kiểm tra lại thao tác.")
    return row


@router.post("/auth/register", status_code=201)
def register(data: Credentials):
    salt = secrets.token_bytes(16)
    stored = salt.hex() + ":" + derive(data.password, salt)
    with transaction(write=True) as conn:
        try:
            conn.execute("INSERT INTO users(username,password_hash) VALUES (?,?)", (data.username, stored))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Tên đăng nhập đã được sử dụng.") from None
    return {"username": data.username}


@router.post("/auth/login")
def login(data: Credentials, request: Request, response: Response):
    buckets = {f"user:{data.username}": 10, f"client:{request.client.host}": 50}
    reservations = {}
    with transaction(write=True) as conn:
        now = int(time.time())
        conn.execute("DELETE FROM login_attempts WHERE started<=?", (now - LOGIN_WINDOW,))
        for key, limit in buckets.items():
            row = conn.execute("SELECT started, attempts FROM login_attempts WHERE bucket=?", (key,)).fetchone()
            if row and row["attempts"] >= limit:
                wait = row["started"] + LOGIN_WINDOW - now
                raise HTTPException(429, "Đã thử đăng nhập quá nhiều lần. Vui lòng thử lại sau.",
                                    headers={"Retry-After": str(wait)})
            reservations[key] = row["started"] if row else now
            conn.execute("INSERT INTO login_attempts VALUES (?,?,1) ON CONFLICT(bucket) "
                         "DO UPDATE SET attempts=attempts+1", (key, now))
        user = conn.execute("SELECT * FROM users WHERE username=?", (data.username,)).fetchone()
    salt, expected = user["password_hash"].split(":") if user else ("00" * 16, "00" * 64)
    if not hmac.compare_digest(derive(data.password, bytes.fromhex(salt)), expected) or not user:
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng.")
    token = secrets.token_urlsafe(32)
    with transaction(write=True) as conn:
        now = int(time.time())
        conn.executemany("UPDATE login_attempts SET attempts=attempts-1 WHERE bucket=? AND started=?",
                         reservations.items())
        conn.execute("DELETE FROM sessions WHERE expires_at<=? OR token_hash=?",
                     (now, digest(request.cookies.get(COOKIE, ""))))
        conn.execute("INSERT INTO sessions VALUES (?,?,?)", (digest(token), user["id"], now + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=SESSION_SECONDS)
    return {"username": user["username"]}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    with transaction(write=True) as conn:
        if "X-SmartFood-Actor" in request.headers:
            current_user(conn, request)
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (digest(request.cookies.get(COOKIE, "")),))
    response.delete_cookie(COOKIE, httponly=True, samesite="strict")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    with transaction() as conn:
        user = current_user(conn, request)
        home = conn.execute("SELECT household_id FROM memberships WHERE user_id=?", (user["id"],)).fetchone()
        return {**dict(user), "household_id": home[0] if home else None}
