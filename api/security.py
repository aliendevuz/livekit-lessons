import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from datetime import timedelta
from urllib.parse import parse_qsl

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException

from . import config
from .db import fmt, get_db, now

INIT_DATA_MAX_AGE = 24 * 3600


def hash_pincode(pincode: str) -> str:
    return bcrypt.hashpw(pincode.encode(), bcrypt.gensalt()).decode()


def verify_pincode(pincode: str, pincode_hash: str) -> bool:
    return bcrypt.checkpw(pincode.encode(), pincode_hash.encode())


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (user_id, _token_hash(token), fmt(now()), fmt(now() + timedelta(days=config.SESSION_DAYS))),
    )
    return token


def current_user(
    authorization: str | None = Header(None),
    conn: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "login qilinmagan")
    row = conn.execute(
        """SELECT u.*, s.id AS session_id
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1""",
        (_token_hash(authorization[7:]), fmt(now())),
    ).fetchone()
    if row is None:
        raise HTTPException(401, "session yaroqsiz")
    return row


def require_role(*roles: str):
    def dependency(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
        if user["role"] not in roles:
            raise HTTPException(403, "ruxsat yo'q")
        return user

    return dependency


def telegram_id_from_init_data(init_data: str) -> int:
    """Mini app bergan initData imzosini bot token bilan tekshiradi va telegram_id ni qaytaradi."""
    if not config.BOT_TOKEN:
        raise HTTPException(503, "BOT_TOKEN sozlanmagan")
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", "")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(401, "initData imzosi noto'g'ri")
    try:
        auth_date = int(fields["auth_date"])
        telegram_id = int(json.loads(fields["user"])["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "initData noto'g'ri") from exc
    if time.time() - auth_date > INIT_DATA_MAX_AGE:
        raise HTTPException(401, "initData eskirgan")
    return telegram_id


def bind_telegram(conn: sqlite3.Connection, user_id: int, telegram_id: int) -> None:
    conn.execute("UPDATE users SET telegram_id = NULL WHERE telegram_id = ? AND id != ?", (telegram_id, user_id))
    conn.execute("UPDATE users SET telegram_id = ? WHERE id = ?", (telegram_id, user_id))


def media_token(room: str, act: str, ttl_seconds: int) -> str:
    """Media backend uchun qisqa muddatli ruxsat. act: upload | view | finish"""
    payload = {"room": room, "act": act, "exp": int(time.time()) + ttl_seconds}
    return jwt.encode(payload, config.MEDIA_SECRET, algorithm="HS256")
