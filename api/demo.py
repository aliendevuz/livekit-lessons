"""Sinov (demo) rejimi: tayyor userlar, login sahifasida bir bosishda kiriladi.

Faqat DEMO_MODE=1 bo'lganda ishlaydi. Bu rejimda havolani bilgan har kim istalgan user,
jumladan admin nomidan kira oladi — haqiqiy foydalanuvchilar bilan ishlatilmaydi.
"""

import secrets
import sqlite3

import bcrypt

from . import config
from .db import fmt, now

GROUPS = config.DEMO_GROUPS
STUDENTS = config.DEMO_STUDENTS

DEMO_USERS = [
    (config.ADMIN_USERNAME, "Admin", "admin"),
    *[(f"teacher{number}", f"Teacher {number}", "teacher") for number in range(1, GROUPS + 1)],
    *[(f"student{number}", f"Student {number}", "student") for number in range(1, STUDENTS + 1)],
]
DEMO_USERNAMES = [username for username, _, _ in DEMO_USERS]

# Har guruhga bitta teacher; o'quvchilar tartib bilan teng bo'linadi (10 ta, 2 guruh: 1-5 va 6-10).
_PER_GROUP = -(-STUDENTS // GROUPS)
# (guruh nomi, teacher, o'quvchilar)
DEMO_GROUPS = [
    (f"Group {index + 1}", f"teacher{index + 1}",
     [f"student{number}" for number in range(index * _PER_GROUP + 1, min((index + 1) * _PER_GROUP, STUDENTS) + 1)])
    for index in range(GROUPS)
]


def seed(conn: sqlite3.Connection) -> None:
    """Yo'q demo userlarni yaratadi. Mavjudlariga (masalan, o'z pincode'li admin) tegmaydi."""
    created = set()
    for username, full_name, role in DEMO_USERS:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            continue
        # Pincode tasodifiy va hech kimga ma'lum emas: bu userlarga faqat demo tugmasi orqali kiriladi.
        # Uni topib bo'lmagani uchun eng arzon hash yetadi — aks holda 50 ta user yaratish yarim daqiqa oladi.
        unusable = bcrypt.hashpw(secrets.token_hex(16).encode(), bcrypt.gensalt(rounds=4)).decode()
        conn.execute(
            "INSERT INTO users (username, pincode_hash, full_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, unusable, full_name, role, fmt(now())),
        )
        created.add(username)
    _seed_groups(conn, created)


def _seed_groups(conn: sqlite3.Connection, created: set[str]) -> None:
    """Bo'sh bazada tayyor guruhlarni yaratadi; keyin faqat yangi yaratilgan o'quvchilarni guruhiga qo'shadi.

    Admin o'zgartirgan narsalarga tegmaydi: mavjud a'zoliklar va guruhlar joyida qoladi.
    """
    no_groups_yet = conn.execute("SELECT 1 FROM groups").fetchone() is None

    def user_id(username: str) -> int:
        return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]

    for name, teacher, students in DEMO_GROUPS:
        group = conn.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
        if group is None and (no_groups_yet or teacher in created):
            group_id = conn.execute(
                "INSERT INTO groups (teacher_id, name, created_at) VALUES (?, ?, ?)",
                (user_id(teacher), name, fmt(now())),
            ).lastrowid
        elif group is None:
            continue  # admin bu guruhni o'chirgan
        else:
            group_id = group["id"]
        conn.executemany(
            "INSERT OR IGNORE INTO group_members (group_id, student_id, joined_at) VALUES (?, ?, ?)",
            [(group_id, user_id(student), fmt(now())) for student in students if student in created],
        )


def groups_of(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """User dars beradigan yoki a'zo bo'lgan guruhlar — kirish ro'yxatida ko'rsatiladi."""
    rows = conn.execute(
        """SELECT id, name FROM groups
           WHERE teacher_id = :uid OR id IN (SELECT group_id FROM group_members WHERE student_id = :uid)
           ORDER BY id""",
        {"uid": user_id},
    )
    return [dict(row) for row in rows]


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(DEMO_USERNAMES))
    return conn.execute(
        f"""SELECT * FROM users WHERE is_active = 1 AND username IN ({marks})
            ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'teacher' THEN 1 ELSE 2 END, id""",
        DEMO_USERNAMES,
    ).fetchall()
