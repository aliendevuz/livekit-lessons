import logging
import sqlite3

import aiohttp
from livekit import api as lk

from . import config

log = logging.getLogger(__name__)


def join_token(user: sqlite3.Row, room: str, is_teacher: bool) -> str:
    grants = lk.VideoGrants(
        room_join=True,
        room=room,
        room_admin=is_teacher,
        can_publish=True,
        can_subscribe=True,
    )
    return (
        lk.AccessToken(config.LIVEKIT_API_KEY, config.LIVEKIT_API_SECRET)
        .with_identity(str(user["id"]))
        .with_name(user["full_name"])
        .with_grants(grants)
        .to_jwt()
    )


async def delete_room(room: str) -> None:
    """Room'ni yopadi, barcha ishtirokchilar chiqariladi. Room ochilmagan bo'lsa — hech narsa qilmaydi."""
    client = lk.LiveKitAPI(config.LIVEKIT_INTERNAL_URL, config.LIVEKIT_API_KEY, config.LIVEKIT_API_SECRET)
    try:
        await client.room.delete_room(lk.DeleteRoomRequest(room=room))
    except lk.TwirpError as exc:
        if exc.code != "not_found":
            log.warning("room %s o'chirilmadi: %s", room, exc.message)
    except aiohttp.ClientError as exc:
        log.warning("LiveKit serverga ulanib bo'lmadi, room %s o'chirilmadi: %s", room, exc)
    finally:
        await client.aclose()
