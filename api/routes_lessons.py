import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from . import config, lessons, rooms
from .db import fmt, get_db, iso, now
from .security import current_user, media_token

router = APIRouter(prefix="/lessons", tags=["lessons"])

UPLOAD_TOKEN_TTL = 12 * 3600
INSTANT_LESSON_MIN = 60
# Shuncha daqiqa ichida boshlanadigan rejali dars bo'lsa, yangisi yaratilmaydi — o'sha ochiladi
REUSE_SCHEDULED_WITHIN_MIN = 15
VIEW_TOKEN_TTL = 3600

_MINE = """
    FROM lessons l JOIN groups g ON g.id = l.group_id JOIN users t ON t.id = g.teacher_id
    WHERE (g.teacher_id = :uid
           OR EXISTS (SELECT 1 FROM group_members m WHERE m.group_id = g.id AND m.student_id = :uid))
"""


def _recording_state(lesson: sqlite3.Row) -> str:
    if lesson["recording_ready"]:
        return "ready"
    # yozuv bor, lekin dars hali tugamagan yoki MP4 ga o'tkazilmoqda
    return "processing" if lesson["recording_key"] else "none"


def _lesson_out(lesson: sqlite3.Row, user: sqlite3.Row) -> dict:
    return {
        "id": lesson["id"],
        "group_id": lesson["group_id"],
        "group_name": lesson["group_name"],
        "teacher_name": lesson["teacher_name"],
        "starts_at": iso(lesson["starts_at"]),
        "duration_min": lesson["duration_min"],
        "room_name": lesson["room_name"],
        "status": lesson["status"],
        "recording": _recording_state(lesson),
        "is_teacher": lesson["teacher_id"] == user["id"],
    }


def _my_lesson(conn: sqlite3.Connection, room_name: str, user: sqlite3.Row) -> sqlite3.Row:
    """Darsni topadi va user shu guruhning teacher'i yoki a'zosi ekanini tekshiradi."""
    lesson = conn.execute(
        """SELECT l.*, g.name AS group_name, g.teacher_id, t.full_name AS teacher_name
           FROM lessons l JOIN groups g ON g.id = l.group_id JOIN users t ON t.id = g.teacher_id
           WHERE l.room_name = ?""",
        (room_name,),
    ).fetchone()
    if lesson is None:
        raise HTTPException(404, "dars topilmadi")
    is_member = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND student_id = ?",
        (lesson["group_id"], user["id"]),
    ).fetchone()
    if lesson["teacher_id"] != user["id"] and not is_member:
        raise HTTPException(403, "siz bu guruh a'zosi emassiz")
    return lesson


def _my_lesson_as_teacher(conn: sqlite3.Connection, room_name: str, user: sqlite3.Row) -> sqlite3.Row:
    lesson = _my_lesson(conn, room_name, user)
    if lesson["teacher_id"] != user["id"]:
        raise HTTPException(403, "faqat dars o'qituvchisi uchun")
    return lesson


def _require_open(lesson: sqlite3.Row) -> None:
    if lesson["status"] == "cancelled":
        raise HTTPException(409, "dars bekor qilingan")
    if lesson["status"] == "ended":
        raise HTTPException(409, "dars tugagan")


@router.get("")
def my_lessons(user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    select = "SELECT l.*, g.name AS group_name, g.teacher_id, t.full_name AS teacher_name" + _MINE
    upcoming = conn.execute(
        select + " AND l.status IN ('scheduled', 'live') ORDER BY l.starts_at", {"uid": user["id"]}
    )
    past = conn.execute(
        select + " AND l.status = 'ended' ORDER BY l.starts_at DESC LIMIT 50", {"uid": user["id"]}
    )
    return {
        "upcoming": [_lesson_out(lesson, user) for lesson in upcoming],
        "past": [_lesson_out(lesson, user) for lesson in past],
    }


@router.get("/groups")
def my_groups(user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """O'qituvchining o'z guruhlari — bosh sahifadagi "Dars boshlash" tugmalari uchun."""
    rows = conn.execute(
        """SELECT g.id, g.name, (SELECT COUNT(*) FROM group_members m WHERE m.group_id = g.id) AS member_count
           FROM groups g WHERE g.teacher_id = ? ORDER BY g.id""",
        (user["id"],),
    )
    return [dict(row) for row in rows]


@router.post("/groups/{group_id}/start")
def start_now(group_id: int, user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """O'qituvchi o'z guruhida darsni hozir boshlaydi. Ochiq yoki boshlanish arafasidagi dars bo'lsa — o'sha qaytadi."""
    group = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    if group is None:
        raise HTTPException(404, "guruh topilmadi")
    if group["teacher_id"] != user["id"]:
        raise HTTPException(403, "faqat guruh o'qituvchisi dars boshlay oladi")
    existing = conn.execute(
        """SELECT room_name FROM lessons
           WHERE group_id = ? AND (status = 'live' OR (status = 'scheduled' AND starts_at <= ?))
           ORDER BY status = 'live' DESC, starts_at LIMIT 1""",
        (group_id, fmt(now() + timedelta(minutes=REUSE_SCHEDULED_WITHIN_MIN))),
    ).fetchone()
    if existing:
        return {"room_name": existing["room_name"]}
    room_name = lessons.new_room_name()
    conn.execute(
        "INSERT INTO lessons (group_id, starts_at, duration_min, room_name, created_at) VALUES (?, ?, ?, ?, ?)",
        (group_id, fmt(now()), INSTANT_LESSON_MIN, room_name, fmt(now())),
    )
    return {"room_name": room_name}


@router.post("/{room_name}/join")
def join(room_name: str, user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """LiveKit room token beradi. Video bu serverdan o'tmaydi."""
    lesson = _my_lesson(conn, room_name, user)
    _require_open(lesson)
    is_teacher = lesson["teacher_id"] == user["id"]
    if is_teacher and lesson["status"] == "scheduled":
        conn.execute("UPDATE lessons SET status = 'live' WHERE id = ?", (lesson["id"],))
    return {
        "livekit_url": config.LIVEKIT_URL,
        "token": rooms.join_token(user, room_name, is_teacher),
        "is_teacher": is_teacher,
        "group_name": lesson["group_name"],
    }


@router.post("/{room_name}/end", status_code=204)
async def end(room_name: str, user: sqlite3.Row = Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    lesson = _my_lesson_as_teacher(conn, room_name, user)
    _require_open(lesson)
    await lessons.end_lesson(conn, lesson)


@router.post("/{room_name}/recording/start")
def start_recording(room_name: str, user: sqlite3.Row = Depends(current_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    """Teacher brauzeri bo'laklarni to'g'ridan-to'g'ri media backend'ga yuklashi uchun ruxsat beradi."""
    lesson = _my_lesson_as_teacher(conn, room_name, user)
    _require_open(lesson)
    conn.execute("UPDATE lessons SET recording_key = ? WHERE id = ?", (f"{room_name}.webm", lesson["id"]))
    return {
        "upload_url": f"{config.MEDIA_URL}/recordings/{room_name}/chunks",
        "token": media_token(room_name, "upload", UPLOAD_TOKEN_TTL),
    }


@router.get("/{room_name}/recording/status")
async def recording_status(room_name: str, user: sqlite3.Row = Depends(current_user),
                           conn: sqlite3.Connection = Depends(get_db)):
    """Yozuv MP4 ga o'tkazilayotganda necha foiz bo'lganini qaytaradi. Sahifa buni har 2 soniyada so'raydi."""
    lesson = _my_lesson(conn, room_name, user)
    state = _recording_state(lesson)
    if state != "processing" or lesson["status"] != "ended":
        return {"state": state, "progress": None}
    result = await lessons.finalize_recording(conn, lesson["id"])
    if result is None:
        # media backend javob bermadi — sahifa keyinroq yana so'raydi
        return {"state": "processing", "progress": None}
    return {"state": result["state"], "progress": result.get("progress")}


@router.get("/{room_name}/recording")
def get_recording(room_name: str, user: sqlite3.Row = Depends(current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    lesson = _my_lesson(conn, room_name, user)
    if not lesson["recording_ready"]:
        raise HTTPException(404, "recording yo'q yoki hali tayyor emas")
    token = media_token(room_name, "view", VIEW_TOKEN_TTL)
    return {"url": f"{config.MEDIA_URL}/recordings/{room_name}?token={token}"}
