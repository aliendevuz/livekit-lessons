import sqlite3
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import lessons
from .db import TZ, fmt, get_db, iso, now, one
from .routes_auth import PINCODE_PATTERN, normalize_username, user_out
from .security import hash_pincode, require_role

router = APIRouter(prefix="/admin", tags=["admin"])

admin = require_role("admin")
Role = Literal["admin", "teacher", "student"]


# ---------- userlar ----------

class UserCreate(BaseModel):
    username: str
    pincode: str = Field(pattern=PINCODE_PATTERN)
    full_name: str = Field(min_length=1, max_length=64)
    role: Role = "student"

    _username = field_validator("username")(normalize_username)


class UserPatch(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=64)
    role: Role | None = None
    is_active: bool | None = None
    pincode: str | None = Field(None, pattern=PINCODE_PATTERN)


def _in_any_group(conn: sqlite3.Connection, user_id: int) -> bool:
    return conn.execute(
        """SELECT 1 FROM groups WHERE teacher_id = ?
           UNION ALL SELECT 1 FROM group_members WHERE student_id = ?""",
        (user_id, user_id),
    ).fetchone() is not None


@router.get("/users")
def list_users(q: str = "", role: Role | None = None,
               conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    sql = "SELECT * FROM users WHERE (username LIKE ? OR full_name LIKE ?)"
    args: list = [f"%{q}%", f"%{q}%"]
    if role:
        sql += " AND role = ?"
        args.append(role)
    return [user_out(u) for u in conn.execute(sql + " ORDER BY id", args)]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    try:
        user_id = conn.execute(
            "INSERT INTO users (username, pincode_hash, full_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (body.username, hash_pincode(body.pincode), body.full_name, body.role, fmt(now())),
        ).lastrowid
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "username band") from exc
    return user_out(one(conn, "SELECT * FROM users WHERE id = ?", user_id))


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch,
                conn: sqlite3.Connection = Depends(get_db), me: sqlite3.Row = Depends(admin)):
    user = one(conn, "SELECT * FROM users WHERE id = ?", user_id, what="user topilmadi")
    role_changes = body.role is not None and body.role != user["role"]
    if user_id == me["id"] and (role_changes or body.is_active is False):
        raise HTTPException(400, "admin o'zini bloklay yoki rolini o'zgartira olmaydi")
    if role_changes and _in_any_group(conn, user_id):
        raise HTTPException(409, "rolni o'zgartirishdan oldin userni guruhlardan chiqaring")

    if body.full_name is not None:
        conn.execute("UPDATE users SET full_name = ? WHERE id = ?", (body.full_name, user_id))
    if body.role is not None:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, user_id))
    if body.is_active is not None:
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (body.is_active, user_id))
    if body.pincode is not None:
        conn.execute("UPDATE users SET pincode_hash = ? WHERE id = ?", (hash_pincode(body.pincode), user_id))
    if body.pincode is not None or body.is_active is False:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return user_out(one(conn, "SELECT * FROM users WHERE id = ?", user_id))


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, conn: sqlite3.Connection = Depends(get_db), me: sqlite3.Row = Depends(admin)):
    one(conn, "SELECT id FROM users WHERE id = ?", user_id, what="user topilmadi")
    if user_id == me["id"]:
        raise HTTPException(400, "admin o'zini o'chira olmaydi")
    if conn.execute("SELECT 1 FROM groups WHERE teacher_id = ?", (user_id,)).fetchone():
        raise HTTPException(409, "guruhi bor teacher o'chirilmaydi")
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ---------- guruhlar ----------

class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    teacher_id: int


class GroupPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    teacher_id: int | None = None


def _require_user_with_role(conn: sqlite3.Connection, user_id: int, role: str) -> None:
    user = one(conn, "SELECT * FROM users WHERE id = ?", user_id, what="user topilmadi")
    if user["role"] != role or not user["is_active"]:
        raise HTTPException(400, f"user aktiv {role} emas")


def _lesson_out(lesson: sqlite3.Row) -> dict:
    return {
        "id": lesson["id"],
        "schedule_id": lesson["schedule_id"],
        "starts_at": iso(lesson["starts_at"]),
        "duration_min": lesson["duration_min"],
        "room_name": lesson["room_name"],
        "status": lesson["status"],
        "link_sent_at": iso(lesson["link_sent_at"]),
    }


def _group_out(conn: sqlite3.Connection, group_id: int) -> dict:
    group = one(conn, "SELECT * FROM groups WHERE id = ?", group_id, what="guruh topilmadi")
    members = conn.execute(
        """SELECT u.* FROM group_members m JOIN users u ON u.id = m.student_id
           WHERE m.group_id = ? ORDER BY u.id""",
        (group_id,),
    )
    upcoming = conn.execute(
        "SELECT * FROM lessons WHERE group_id = ? AND status IN ('scheduled', 'live') ORDER BY starts_at",
        (group_id,),
    )
    return {
        "id": group["id"],
        "name": group["name"],
        "teacher": user_out(one(conn, "SELECT * FROM users WHERE id = ?", group["teacher_id"])),
        "members": [user_out(u) for u in members],
        "schedules": [dict(s) for s in conn.execute(
            "SELECT * FROM schedules WHERE group_id = ? ORDER BY weekday, start_time", (group_id,))],
        "lessons": [_lesson_out(lesson) for lesson in upcoming],
    }


@router.get("/groups")
def list_groups(conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    rows = conn.execute(
        """SELECT g.id, g.name, g.teacher_id, u.full_name AS teacher_name,
                  (SELECT COUNT(*) FROM group_members m WHERE m.group_id = g.id) AS member_count
           FROM groups g JOIN users u ON u.id = g.teacher_id ORDER BY g.id"""
    )
    return [dict(row) for row in rows]


@router.post("/groups", status_code=201)
def create_group(body: GroupCreate, conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    _require_user_with_role(conn, body.teacher_id, "teacher")
    group_id = conn.execute(
        "INSERT INTO groups (teacher_id, name, created_at) VALUES (?, ?, ?)",
        (body.teacher_id, body.name, fmt(now())),
    ).lastrowid
    return _group_out(conn, group_id)


@router.get("/groups/{group_id}")
def get_group(group_id: int, conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    return _group_out(conn, group_id)


@router.patch("/groups/{group_id}")
def update_group(group_id: int, body: GroupPatch,
                 conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    one(conn, "SELECT id FROM groups WHERE id = ?", group_id, what="guruh topilmadi")
    if body.name is not None:
        conn.execute("UPDATE groups SET name = ? WHERE id = ?", (body.name, group_id))
    if body.teacher_id is not None:
        _require_user_with_role(conn, body.teacher_id, "teacher")
        conn.execute("UPDATE groups SET teacher_id = ? WHERE id = ?", (body.teacher_id, group_id))
    return _group_out(conn, group_id)


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: int, conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    one(conn, "SELECT id FROM groups WHERE id = ?", group_id, what="guruh topilmadi")
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))


@router.put("/groups/{group_id}/members/{student_id}", status_code=204)
def add_member(group_id: int, student_id: int,
               conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    one(conn, "SELECT id FROM groups WHERE id = ?", group_id, what="guruh topilmadi")
    _require_user_with_role(conn, student_id, "student")
    conn.execute(
        "INSERT OR IGNORE INTO group_members (group_id, student_id, joined_at) VALUES (?, ?, ?)",
        (group_id, student_id, fmt(now())),
    )


@router.delete("/groups/{group_id}/members/{student_id}", status_code=204)
def remove_member(group_id: int, student_id: int,
                  conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    conn.execute("DELETE FROM group_members WHERE group_id = ? AND student_id = ?", (group_id, student_id))


# ---------- dars jadvali ----------

class ScheduleIn(BaseModel):
    weekday: int = Field(ge=1, le=7, description="1 = dushanba")
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="HH:MM, Toshkent vaqti")
    duration_min: int = Field(gt=0, le=600)


class LessonCreate(BaseModel):
    starts_at: datetime = Field(description="vaqt zonasi ko'rsatilmasa Toshkent vaqti deb olinadi")
    duration_min: int = Field(gt=0, le=600)


def _minutes(start_time: str) -> int:
    hour, minute = map(int, start_time.split(":"))
    return hour * 60 + minute


def _check_teacher_is_free(conn: sqlite3.Connection, group_id: int, body: ScheduleIn,
                           exclude_id: int | None = None) -> None:
    """Bitta teacher'ning (barcha guruhlari bo'yicha) jadvali ustma-ust tushmasligi kerak."""
    others = conn.execute(
        """SELECT s.* FROM schedules s JOIN groups g ON g.id = s.group_id
           WHERE s.weekday = ? AND g.teacher_id = (SELECT teacher_id FROM groups WHERE id = ?)""",
        (body.weekday, group_id),
    )
    start = _minutes(body.start_time)
    end = start + body.duration_min
    for other in others:
        if other["id"] == exclude_id:
            continue
        other_start = _minutes(other["start_time"])
        if start < other_start + other["duration_min"] and other_start < end:
            raise HTTPException(409, "teacher'ning shu vaqtda boshqa darsi bor")


@router.post("/groups/{group_id}/schedules", status_code=201)
def add_schedule(group_id: int, body: ScheduleIn,
                 conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    one(conn, "SELECT id FROM groups WHERE id = ?", group_id, what="guruh topilmadi")
    _check_teacher_is_free(conn, group_id, body)
    schedule_id = conn.execute(
        "INSERT INTO schedules (group_id, weekday, start_time, duration_min) VALUES (?, ?, ?, ?)",
        (group_id, body.weekday, body.start_time, body.duration_min),
    ).lastrowid
    lessons.generate_lessons(conn, schedule_id)
    return _group_out(conn, group_id)


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleIn,
                    conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    schedule = one(conn, "SELECT * FROM schedules WHERE id = ?", schedule_id, what="jadval topilmadi")
    _check_teacher_is_free(conn, schedule["group_id"], body, exclude_id=schedule_id)
    conn.execute(
        "UPDATE schedules SET weekday = ?, start_time = ?, duration_min = ? WHERE id = ?",
        (body.weekday, body.start_time, body.duration_min, schedule_id),
    )
    lessons.delete_pending_lessons(conn, schedule_id)
    lessons.generate_lessons(conn, schedule_id)
    return _group_out(conn, schedule["group_id"])


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    one(conn, "SELECT id FROM schedules WHERE id = ?", schedule_id, what="jadval topilmadi")
    lessons.delete_pending_lessons(conn, schedule_id)
    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))


@router.post("/groups/{group_id}/lessons", status_code=201)
def create_lesson(group_id: int, body: LessonCreate,
                  conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    """Jadvaldan tashqari bir martalik dars."""
    one(conn, "SELECT id FROM groups WHERE id = ?", group_id, what="guruh topilmadi")
    starts_at = body.starts_at if body.starts_at.tzinfo else body.starts_at.replace(tzinfo=TZ)
    lesson_id = conn.execute(
        "INSERT INTO lessons (group_id, starts_at, duration_min, room_name, created_at) VALUES (?, ?, ?, ?, ?)",
        (group_id, fmt(starts_at), body.duration_min, lessons.new_room_name(), fmt(now())),
    ).lastrowid
    return _lesson_out(one(conn, "SELECT * FROM lessons WHERE id = ?", lesson_id))


@router.post("/lessons/{lesson_id}/cancel")
def cancel_lesson(lesson_id: int, conn: sqlite3.Connection = Depends(get_db), _: sqlite3.Row = Depends(admin)):
    lesson = one(conn, "SELECT * FROM lessons WHERE id = ?", lesson_id, what="dars topilmadi")
    if lesson["status"] != "scheduled":
        raise HTTPException(409, "faqat hali boshlanmagan darsni bekor qilish mumkin")
    conn.execute("UPDATE lessons SET status = 'cancelled' WHERE id = ?", (lesson_id,))
    return _lesson_out(one(conn, "SELECT * FROM lessons WHERE id = ?", lesson_id))
