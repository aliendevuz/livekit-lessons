"""Dars bilan bog'liq umumiy amallar: jadvaldan yaratish, havola yuborish, tugatish, recording."""

import logging
import secrets
import sqlite3
from datetime import datetime, timedelta

import httpx

from . import config, rooms
from .db import TZ, fmt, now, parse
from .security import media_token

log = logging.getLogger(__name__)

GENERATE_DAYS = 7


def new_room_name() -> str:
    return secrets.token_urlsafe(12)


def generate_lessons(conn: sqlite3.Connection, schedule_id: int | None = None) -> None:
    """Jadval bo'yicha keyingi 7 kunlik darslarni yaratadi. Mavjudlari qayta yaratilmaydi."""
    if schedule_id is None:
        schedules = conn.execute("SELECT * FROM schedules").fetchall()
    else:
        schedules = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchall()
    current = now()
    today = current.astimezone(TZ).date()
    for schedule in schedules:
        hour, minute = map(int, schedule["start_time"].split(":"))
        for offset in range(GENERATE_DAYS):
            day = today + timedelta(days=offset)
            if day.isoweekday() != schedule["weekday"]:
                continue
            starts_at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)
            if starts_at < current:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO lessons
                   (group_id, schedule_id, starts_at, duration_min, room_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (schedule["group_id"], schedule["id"], fmt(starts_at), schedule["duration_min"],
                 new_room_name(), fmt(current)),
            )


def delete_pending_lessons(conn: sqlite3.Connection, schedule_id: int) -> None:
    """Hali boshlanmagan va havolasi yuborilmagan darslarni o'chiradi."""
    conn.execute(
        "DELETE FROM lessons WHERE schedule_id = ? AND status = 'scheduled' AND link_sent_at IS NULL",
        (schedule_id,),
    )


async def send_links(conn: sqlite3.Connection) -> None:
    current = now()
    candidates = conn.execute(
        """SELECT l.*, g.name AS group_name, g.teacher_id
           FROM lessons l JOIN groups g ON g.id = l.group_id
           WHERE l.status = 'scheduled' AND l.link_sent_at IS NULL AND l.starts_at <= ?""",
        (fmt(current + timedelta(minutes=config.LINK_BEFORE_MIN)),),
    ).fetchall()
    async with httpx.AsyncClient(timeout=10) as http:
        for lesson in candidates:
            if parse(lesson["starts_at"]) + timedelta(minutes=lesson["duration_min"]) <= current:
                continue
            recipients = conn.execute(
                """SELECT telegram_id FROM users
                   WHERE is_active = 1 AND telegram_id IS NOT NULL
                     AND (id = ? OR id IN (SELECT student_id FROM group_members WHERE group_id = ?))""",
                (lesson["teacher_id"], lesson["group_id"]),
            ).fetchall()
            url = f"{config.WEBAPP_URL}/?lesson={lesson['room_name']}"
            for recipient in recipients:
                await _send_link(http, recipient["telegram_id"], lesson["group_name"], url)
            conn.execute("UPDATE lessons SET link_sent_at = ? WHERE id = ?", (fmt(current), lesson["id"]))
            conn.commit()


async def _send_link(http: httpx.AsyncClient, telegram_id: int, group_name: str, url: str) -> None:
    if not config.BOT_TOKEN:
        log.info("havola (BOT_TOKEN yo'q, yuborilmadi): telegram_id=%s %s", telegram_id, url)
        return
    try:
        response = await http.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
            json={
                "chat_id": telegram_id,
                "text": f"«{group_name}» darsi boshlanmoqda",
                "reply_markup": {"inline_keyboard": [[{"text": "Darsga kirish", "web_app": {"url": url}}]]},
            },
        )
    except httpx.HTTPError as exc:
        log.warning("telegram_id=%s ga havola yuborilmadi: %s", telegram_id, exc)
        return
    if response.status_code != 200:
        # masalan, user botni bloklagan
        log.warning("telegram_id=%s ga havola yuborilmadi: %s", telegram_id, response.text)


async def end_lesson(conn: sqlite3.Connection, lesson: sqlite3.Row) -> None:
    conn.execute("UPDATE lessons SET status = 'ended' WHERE id = ?", (lesson["id"],))
    conn.commit()
    await rooms.delete_room(lesson["room_name"])
    await finalize_recording(conn, lesson["id"])


async def end_overdue_lessons(conn: sqlite3.Connection) -> None:
    """Zaxira: teacher tugatmagan darslarni rejadagi vaqtdan 30 daqiqa o'tgach yopadi."""
    current = now()
    for lesson in conn.execute("SELECT * FROM lessons WHERE status IN ('scheduled', 'live')").fetchall():
        deadline = parse(lesson["starts_at"]) + timedelta(
            minutes=lesson["duration_min"] + config.AUTO_END_AFTER_MIN
        )
        if deadline <= current:
            await end_lesson(conn, lesson)


async def finalize_recording(conn: sqlite3.Connection, lesson_id: int) -> dict | None:
    """Media backend'ga yozuvni yopishni aytadi. MP4 tayyor bo'lgach recording_ready ni belgilaydi.

    Media backend javobini qaytaradi: {"state": none | processing | ready, "progress": 0-99}.
    """
    lesson = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    if not lesson["recording_key"] or lesson["recording_ready"]:
        return None
    room = lesson["room_name"]
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(
                f"{config.MEDIA_INTERNAL_URL}/internal/recordings/{room}/finish",
                headers={"Authorization": f"Bearer {media_token(room, 'finish', 60)}"},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        # cron keyingi daqiqada qayta urinadi
        log.warning("media backend javob bermadi, %s recording'i yakunlanmadi: %s", room, exc)
        return None
    result = response.json()
    if result["state"] == "ready":
        conn.execute(
            "UPDATE lessons SET recording_ready = 1, recording_key = ? WHERE id = ?", (result["file"], lesson_id)
        )
    elif result["state"] == "none":
        conn.execute("UPDATE lessons SET recording_key = NULL WHERE id = ?", (lesson_id,))
    # "processing": MP4 ga o'tkazilmoqda — cron yoki sahifa yana so'raydi
    conn.commit()
    return result


async def finalize_pending_recordings(conn: sqlite3.Connection) -> None:
    pending = conn.execute(
        "SELECT id FROM lessons WHERE status = 'ended' AND recording_key IS NOT NULL AND recording_ready = 0"
    ).fetchall()
    for lesson in pending:
        await finalize_recording(conn, lesson["id"])
