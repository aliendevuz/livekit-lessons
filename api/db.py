import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY,
    username     TEXT    NOT NULL UNIQUE,
    pincode_hash TEXT    NOT NULL,
    role         TEXT    NOT NULL DEFAULT 'student'
                         CHECK (role IN ('admin', 'teacher', 'student')),
    full_name    TEXT    NOT NULL,
    telegram_id  INTEGER UNIQUE,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT    NOT NULL UNIQUE,
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY,
    teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id   INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at  TEXT    NOT NULL,
    PRIMARY KEY (group_id, student_id)
);

CREATE TABLE IF NOT EXISTS schedules (
    id           INTEGER PRIMARY KEY,
    group_id     INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    weekday      INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    start_time   TEXT    NOT NULL,
    duration_min INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY,
    group_id        INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    schedule_id     INTEGER REFERENCES schedules(id) ON DELETE SET NULL,
    starts_at       TEXT    NOT NULL,
    duration_min    INTEGER NOT NULL,
    room_name       TEXT    NOT NULL UNIQUE,
    status          TEXT    NOT NULL DEFAULT 'scheduled'
                            CHECK (status IN ('scheduled', 'live', 'ended', 'cancelled')),
    link_sent_at    TEXT,
    recording_key   TEXT,
    recording_ready INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    UNIQUE (schedule_id, starts_at)
);
"""

# Asia/Tashkent: UTC+5, yozgi vaqt yo'q
TZ = timezone(timedelta(hours=5))
FMT = "%Y-%m-%d %H:%M:%S"


def now() -> datetime:
    return datetime.now(timezone.utc)


def fmt(dt: datetime) -> str:
    """Bazada barcha vaqtlar UTC, bir xil formatda turadi (satr sifatida solishtirsa bo'ladi)."""
    return dt.astimezone(timezone.utc).strftime(FMT)


def parse(value: str) -> datetime:
    return datetime.strptime(value, FMT).replace(tzinfo=timezone.utc)


def iso(value: str | None) -> str | None:
    return value.replace(" ", "T") + "Z" if value else None


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def one(conn: sqlite3.Connection, sql: str, *args, what: str = "topilmadi") -> sqlite3.Row:
    row = conn.execute(sql, args).fetchone()
    if row is None:
        raise HTTPException(404, what)
    return row
