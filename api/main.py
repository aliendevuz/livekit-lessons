"""Backend 1: login, admin, jadval va tokenlar. Video bu serverdan o'tmaydi."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, demo, jobs, routes_admin, routes_auth, routes_lessons
from .db import SCHEMA, connect, fmt, now
from .security import hash_pincode

logging.basicConfig(level=logging.INFO)


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # avvalroq yaratilgan bazalarda bu ustun yo'q
        if "last_seen_at" not in [column["name"] for column in conn.execute("PRAGMA table_info(sessions)")]:
            conn.execute("ALTER TABLE sessions ADD COLUMN last_seen_at TEXT")
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (config.ADMIN_USERNAME,)).fetchone()
        if config.ADMIN_PINCODE and not exists:
            conn.execute(
                "INSERT INTO users (username, pincode_hash, full_name, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
                (config.ADMIN_USERNAME, hash_pincode(config.ADMIN_PINCODE), "Admin", fmt(now())),
            )
        if config.DEMO_MODE:
            demo.seed(conn)
        conn.commit()
    finally:
        conn.close()


class FreshStaticFiles(StaticFiles):
    """Brauzer sahifa fayllarini har safar server bilan solishtiradi — eski app.js keshda qolib ketmaydi."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cron = asyncio.create_task(jobs.run_forever())
    yield
    cron.cancel()


app = FastAPI(title="Lesson API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes_auth.router)
app.include_router(routes_admin.router)
app.include_router(routes_lessons.router)
# Mini app sahifasi (statik fayllar). API yo'llaridan keyin turishi shart.
app.mount("/", FreshStaticFiles(directory=config.BASE_DIR.parent / "web", html=True), name="web")
