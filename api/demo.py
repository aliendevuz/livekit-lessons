"""Sinov (demo) rejimi: tayyor userlar, login sahifasida bir bosishda kiriladi.

Faqat DEMO_MODE=1 bo'lganda ishlaydi. Bu rejimda havolani bilgan har kim istalgan user,
jumladan admin nomidan kira oladi — haqiqiy foydalanuvchilar bilan ishlatilmaydi.
"""

import secrets
import sqlite3

from . import config
from .db import fmt, now
from .security import hash_pincode

DEMO_USERS = [
    (config.ADMIN_USERNAME, "Admin", "admin"),
    *[(f"teacher{number}", f"Teacher {number}", "teacher") for number in range(1, 3)],
    *[(f"student{number}", f"Student {number}", "student") for number in range(1, 11)],
]
DEMO_USERNAMES = [username for username, _, _ in DEMO_USERS]

# (guruh nomi, teacher, o'quvchilar)
DEMO_GROUPS = [
    ("Group 1", "teacher1", [f"student{number}" for number in range(1, 6)]),
    ("Group 2", "teacher2", [f"student{number}" for number in range(6, 11)]),
]


def seed(conn: sqlite3.Connection) -> None:
    """Yo'q demo userlarni yaratadi. Mavjudlariga (masalan, o'z pincode'li admin) tegmaydi."""
    for username, full_name, role in DEMO_USERS:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            continue
        # pincode tasodifiy: bu userlarga faqat demo tugmasi orqali kiriladi
        conn.execute(
            "INSERT INTO users (username, pincode_hash, full_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, hash_pincode(secrets.token_hex(16)), full_name, role, fmt(now())),
        )
    _seed_groups(conn)


def _seed_groups(conn: sqlite3.Connection) -> None:
    """Hech qanday guruh bo'lmasa tayyor guruhlarni yaratadi. Admin o'zgartirgan guruhlarga tegmaydi."""
    if conn.execute("SELECT 1 FROM groups").fetchone():
        return

    def user_id(username: str) -> int:
        return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]

    for name, teacher, students in DEMO_GROUPS:
        group_id = conn.execute(
            "INSERT INTO groups (teacher_id, name, created_at) VALUES (?, ?, ?)", (user_id(teacher), name, fmt(now()))
        ).lastrowid
        conn.executemany(
            "INSERT INTO group_members (group_id, student_id, joined_at) VALUES (?, ?, ?)",
            [(group_id, user_id(student), fmt(now())) for student in students],
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
