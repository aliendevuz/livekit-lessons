import asyncio
import logging
from datetime import date

from . import lessons
from .db import TZ, connect, now

log = logging.getLogger(__name__)

TICK_SECONDS = 60

_generated_on: date | None = None


async def tick() -> None:
    global _generated_on
    conn = connect()
    try:
        today = now().astimezone(TZ).date()
        if _generated_on != today:
            lessons.generate_lessons(conn)
            conn.commit()
            _generated_on = today
        await lessons.send_links(conn)
        await lessons.end_overdue_lessons(conn)
        await lessons.finalize_pending_recordings(conn)
    finally:
        conn.close()


async def run_forever() -> None:
    while True:
        try:
            await tick()
        except Exception:
            # bitta xato butun cron'ni to'xtatmasligi kerak
            log.exception("cron xatosi")
        await asyncio.sleep(TICK_SECONDS)
