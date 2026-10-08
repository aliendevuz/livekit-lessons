import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import config, demo
from .db import fmt, get_db, now
from .security import (
    bind_telegram,
    create_session,
    current_user,
    hash_pincode,
    telegram_id_from_init_data,
    verify_pincode,
)

router = APIRouter(tags=["auth"])

USERNAME_RE = re.compile(r"[a-z0-9_]{3,32}")
PINCODE_PATTERN = r"^\d{4,6}$"


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("username 3-32 belgi: a-z, 0-9, _")
    return value


def user_out(user: sqlite3.Row) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "full_name": user["full_name"],
        "is_active": bool(user["is_active"]),
        "telegram_linked": user["telegram_id"] is not None,
    }


class TelegramIn(BaseModel):
    init_data: str


class LoginIn(BaseModel):
    username: str
    pincode: str = Field(pattern=PINCODE_PATTERN)
    init_data: str | None = None

    _username = field_validator("username")(normalize_username)


class RegisterIn(LoginIn):
    full_name: str = Field(min_length=1, max_length=64)


@router.post("/auth/telegram")
def login_with_telegram(body: TelegramIn, conn: sqlite3.Connection = Depends(get_db)):
    """Mini app ochilganda: telegram_id ulangan bo'lsa pincode so'ramasdan kiritadi."""
    telegram_id = telegram_id_from_init_data(body.init_data)
    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ? AND is_active = 1", (telegram_id,)
    ).fetchone()
    if user is None:
        raise HTTPException(404, "bu Telegram akkaunt hech bir userga ulanmagan")
    return {"token": create_session(conn, user["id"]), "user": user_out(user)}


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, conn: sqlite3.Connection = Depends(get_db)):
    telegram_id = telegram_id_from_init_data(body.init_data) if body.init_data else None
    try:
        user_id = conn.execute(
            "INSERT INTO users (username, pincode_hash, full_name, created_at) VALUES (?, ?, ?, ?)",
            (body.username, hash_pincode(body.pincode), body.full_name, fmt(now())),
        ).lastrowid
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "username band") from exc
    if telegram_id is not None:
        bind_telegram(conn, user_id, telegram_id)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"token": create_session(conn, user_id), "user": user_out(user)}


@router.post("/auth/login")
def login(body: LoginIn, conn: sqlite3.Connection = Depends(get_db)):
    user = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    if user is None or not verify_pincode(body.pincode, user["pincode_hash"]):
        raise HTTPException(401, "username yoki pincode noto'g'ri")
    if not user["is_active"]:
        raise HTTPException(403, "user bloklangan")
    if body.init_data:
        bind_telegram(conn, user["id"], telegram_id_from_init_data(body.init_data))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return {"token": create_session(conn, user["id"]), "user": user_out(user)}


class DemoLoginIn(BaseModel):
    username: str
    init_data: str | None = None


@router.get("/auth/demo")
def demo_users(conn: sqlite3.Connection = Depends(get_db)):
    """Sinov rejimidagi tayyor userlar. Rejim o'chiq bo'lsa ro'yxat bo'sh."""
    if not config.DEMO_MODE:
        return []
    return [{**user_out(user), "groups": demo.groups_of(conn, user["id"])} for user in demo.list_users(conn)]


@router.post("/auth/demo")
def demo_login(body: DemoLoginIn, conn: sqlite3.Connection = Depends(get_db)):
    """Tayyor user nomidan pincode'siz kiradi. Faqat sinov rejimida."""
    # Ikki kishi bitta hisobni bir vaqtda bossa, faqat birinchisi kiradi: tekshiruv va kirish bitta navbatda
    conn.execute("BEGIN IMMEDIATE")
    user = None
    if config.DEMO_MODE and body.username in demo.DEMO_USERNAMES:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1", (body.username,)
        ).fetchone()
    if user is None:
        raise HTTPException(404, "bunday demo user yo'q")
    if demo.is_busy(conn, user["id"]):
        raise HTTPException(409, "Bu hisobni hozirgina boshqa kishi tanladi. Boshqasini tanlang.")
    # eski, tashlab ketilgan sessiyalar yopiladi: hisob bir vaqtda faqat bitta qurilmada ishlaydi
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    if body.init_data:
        bind_telegram(conn, user["id"], telegram_id_from_init_data(body.init_data))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return {"token": create_session(conn, user["id"]), "user": user_out(user)}


@router.post("/auth/logout", status_code=204)
def logout(user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM sessions WHERE id = ?", (user["session_id"],))
    # aks holda mini app qayta ochilganda avtomatik kirib ketadi
    conn.execute("UPDATE users SET telegram_id = NULL WHERE id = ?", (user["id"],))


@router.get("/me")
def me(user: sqlite3.Row = Depends(current_user)):
    return user_out(user)
