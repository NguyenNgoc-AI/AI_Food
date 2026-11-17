import secrets
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from .auth import current_user, digest
from .db import transaction

router = APIRouter(prefix="/api/households")
INVITE_SECONDS = 86400
ResourceID = Annotated[int, Path(ge=1, le=2**63 - 1)]


class NewHousehold(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class JoinCode(BaseModel):
    code: str = Field(min_length=1, max_length=128)


def audit(conn, hid, actor, action, target=None):
    reasons = {"create": "household_created", "join": "valid_invitation", "invite": "owner_issued",
               "revoke_invite": "owner_revoked", "transfer_owner": "owner_transferred",
               "leave": "member_left", "remove_member": "owner_removed"}
    conn.execute("INSERT INTO audit_events(household_id,actor_id,action,target_id,occurred_at,reason) "
                 "VALUES (?,?,?,?,?,?)", (hid, actor, action, target, int(time.time()), reasons[action]))


def authorize(conn, request, hid, *, owner=False):
    user = current_user(conn, request)
    home = conn.execute(
        "SELECT h.* FROM households h JOIN memberships m ON m.household_id=h.id "
        "WHERE h.id=? AND m.user_id=?", (hid, user["id"])
    ).fetchone()
    if not home:
        raise HTTPException(404, "Không tìm thấy hộ hoặc bạn đã mất quyền truy cập.")
    if owner and home["owner_id"] != user["id"]:
        raise HTTPException(403, "Thao tác này cần quyền chủ hộ.")
    return user["id"], home


def require_no_household(conn, uid):
    if conn.execute("SELECT 1 FROM memberships WHERE user_id=?", (uid,)).fetchone():
        raise HTTPException(409, "Bạn đã thuộc một hộ gia đình.")


@router.post("", status_code=201)
def create(data: NewHousehold, request: Request):
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Vui lòng nhập tên hộ.")
    with transaction(write=True) as conn:
        uid = current_user(conn, request)["id"]
        require_no_household(conn, uid)
        hid = conn.execute("INSERT INTO households(name,owner_id) VALUES (?,?)", (name, uid)).lastrowid
        conn.execute("INSERT INTO memberships VALUES (?,?)", (uid, hid))
        audit(conn, hid, uid, "create", uid)
    return {"id": hid}


@router.post("/join")
def join(data: JoinCode, request: Request):
    now = int(time.time())
    with transaction(write=True) as conn:
        uid = current_user(conn, request)["id"]
        require_no_household(conn, uid)
        attempts = conn.execute("SELECT * FROM invite_attempts WHERE user_id=?", (uid,)).fetchone()
        recent = attempts and attempts["started"] > now - 300
        if recent and attempts["failures"] >= 10:
            raise HTTPException(429, "Đã thử quá nhiều mã. Hãy thử lại sau 5 phút.")
        invite = conn.execute(
            "SELECT id,household_id FROM invitations WHERE code_hash=? AND expires_at>? AND revoked=0 AND used_by IS NULL",
            (digest(data.code.strip()), now)
        ).fetchone()
        if invite:
            hid = invite["household_id"]
            conn.execute("INSERT INTO memberships VALUES (?,?)", (uid, hid))
            conn.execute("UPDATE invitations SET used_by=? WHERE id=?", (uid, invite["id"]))
            conn.execute("DELETE FROM invite_attempts WHERE user_id=?", (uid,))
            audit(conn, hid, uid, "join", invite["id"])
            return {"id": hid}
        conn.execute("INSERT OR REPLACE INTO invite_attempts VALUES (?,?,?)",
                     (uid, attempts["started"] if recent else now, attempts["failures"] + 1 if recent else 1))
    raise HTTPException(400, "Mã mời sai, đã dùng, hết hạn hoặc đã bị thu hồi.")


@router.get("/{hid}")
def details(hid: ResourceID, request: Request):
    with transaction() as conn:
        uid, home = authorize(conn, request, hid)
        members = conn.execute("SELECT u.id,u.username FROM users u JOIN memberships m ON m.user_id=u.id "
                               "WHERE m.household_id=? ORDER BY u.username", (hid,)).fetchall()
        result = {**dict(home), "members": [dict(m) for m in members]}
        if uid == home["owner_id"]:
            rows = conn.execute("SELECT id,expires_at FROM invitations WHERE household_id=? AND used_by IS NULL "
                                "AND revoked=0 AND expires_at>? ORDER BY id DESC", (hid, int(time.time())))
            result["invitations"] = [dict(row) for row in rows]
        return result


@router.post("/{hid}/invitations", status_code=201)
def issue(hid: ResourceID, request: Request):
    with transaction(write=True) as conn:
        uid, _ = authorize(conn, request, hid, owner=True)
        code = secrets.token_urlsafe(18)
        expires = int(time.time()) + INVITE_SECONDS
        iid = conn.execute("INSERT INTO invitations(household_id,code_hash,expires_at) VALUES (?,?,?)",
                           (hid, digest(code), expires)).lastrowid
        audit(conn, hid, uid, "invite", iid)
    return {"id": iid, "code": code, "expires_at": expires}


@router.delete("/{hid}/invitations/{iid}")
def revoke(hid: ResourceID, iid: ResourceID, request: Request):
    with transaction(write=True) as conn:
        uid, _ = authorize(conn, request, hid, owner=True)
        changed = conn.execute("UPDATE invitations SET revoked=1 WHERE id=? AND household_id=? "
                               "AND revoked=0 AND used_by IS NULL", (iid, hid))
        if not changed.rowcount:
            raise HTTPException(404, "Không tìm thấy mã mời đang chờ.")
        audit(conn, hid, uid, "revoke_invite", iid)
    return {"ok": True}


@router.post("/{hid}/owner/{member}")
def transfer(hid: ResourceID, member: ResourceID, request: Request):
    with transaction(write=True) as conn:
        uid, _ = authorize(conn, request, hid, owner=True)
        if member == uid:
            raise HTTPException(409, "Bạn đang là chủ hộ.")
        if not conn.execute("SELECT 1 FROM memberships WHERE household_id=? AND user_id=?", (hid, member)).fetchone():
            raise HTTPException(404, "Người nhận cần là thành viên của hộ.")
        conn.execute("UPDATE households SET owner_id=? WHERE id=?", (member, hid))
        audit(conn, hid, uid, "transfer_owner", member)
    return {"ok": True}


@router.delete("/{hid}/members/{member}")
def remove(hid: ResourceID, member: ResourceID, request: Request):
    with transaction(write=True) as conn:
        uid, home = authorize(conn, request, hid)
        if member == home["owner_id"]:
            raise HTTPException(409, "Chủ hộ cần chuyển quyền trước khi rời hộ.")
        if member != uid and uid != home["owner_id"]:
            raise HTTPException(403, "Bạn chỉ có thể rời hộ bằng tài khoản của mình.")
        changed = conn.execute("DELETE FROM memberships WHERE household_id=? AND user_id=?", (hid, member))
        if not changed.rowcount:
            raise HTTPException(404, "Không tìm thấy thành viên trong hộ.")
        audit(conn, hid, uid, "leave" if member == uid else "remove_member", member)
    return {"ok": True}
