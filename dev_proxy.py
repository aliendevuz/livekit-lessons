"""Lokal sinov uchun: uchta serverni bitta port ortiga yig'adi, shunda bitta tunnel (ngrok) yetadi.

    /rtc, /twirp   -> LiveKit (WebSocket signaling)
    /recordings    -> media backend
    qolgan hammasi -> API backend (sahifa ham shu yerda)

Ishga tushirish:
    .venv\\Scripts\\python dev_proxy.py
    ngrok http 8080

Haqiqiy serverda bu ishni nginx yoki Caddy qiladi. Jonli video (UDP) bu yerdan o'tmaydi —
u brauzerdan to'g'ridan-to'g'ri LiveKit'ga boradi.
"""

import asyncio
import os

from aiohttp import ClientConnectorError, ClientSession, ClientTimeout, WSMsgType, web

PORT = int(os.getenv("PROXY_PORT", "8080"))
API = os.getenv("API_UPSTREAM", "http://localhost:8000")
MEDIA = os.getenv("MEDIA_UPSTREAM", "http://localhost:8001")
LIVEKIT = os.getenv("LIVEKIT_UPSTREAM", "http://localhost:7880")

ROUTES = (("/rtc", LIVEKIT), ("/twirp", LIVEKIT), ("/recordings", MEDIA))
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length"}
MAX_BODY = 64 * 1024 * 1024


def upstream_for(path: str) -> str:
    for prefix, upstream in ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return upstream
    return API


def forwarded_headers(headers) -> dict:
    return {name: value for name, value in headers.items() if name.lower() not in HOP_BY_HOP}


async def proxy_websocket(request: web.Request, url: str) -> web.WebSocketResponse:
    session: ClientSession = request.app["session"]
    client = web.WebSocketResponse(max_msg_size=0)
    await client.prepare(request)
    async with session.ws_connect(url, max_msg_size=0) as server:

        async def pump(source, target):
            async for message in source:
                if message.type == WSMsgType.TEXT:
                    await target.send_str(message.data)
                elif message.type == WSMsgType.BINARY:
                    await target.send_bytes(message.data)
            await target.close()

        # bir tomon yopilsa ikkinchisi ham yopiladi
        _, pending = await asyncio.wait(
            {asyncio.create_task(pump(client, server)), asyncio.create_task(pump(server, client))},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    return client


async def handle(request: web.Request) -> web.StreamResponse:
    session: ClientSession = request.app["session"]
    url = upstream_for(request.path) + request.rel_url.raw_path_qs
    try:
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await proxy_websocket(request, url)
        async with session.request(
            request.method, url, headers=forwarded_headers(request.headers),
            data=await request.read(), allow_redirects=False,
        ) as upstream:
            response = web.StreamResponse(status=upstream.status, headers=forwarded_headers(upstream.headers))
            if "Content-Length" in upstream.headers:
                response.content_length = int(upstream.headers["Content-Length"])
            await response.prepare(request)
            async for chunk in upstream.content.iter_chunked(64 * 1024):
                await response.write(chunk)
            await response.write_eof()
            return response
    except ClientConnectorError:
        return web.Response(status=502, text=f"{upstream_for(request.path)} ishlamayapti")
    except ConnectionResetError:
        # brauzer so'rovni o'zi uzdi (masalan, videoni surganda)
        return web.Response(status=499)


async def create_app() -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)
    # auto_decompress=False: siqilgan javob o'zgartirilmasdan uzatiladi
    app["session"] = ClientSession(auto_decompress=False, timeout=ClientTimeout(total=None))

    async def close_session(_: web.Application) -> None:
        await app["session"].close()

    app.on_cleanup.append(close_session)
    app.router.add_route("*", "/{path:.*}", handle)
    return app


if __name__ == "__main__":
    print(f"proxy: http://localhost:{PORT}  ->  API {API} | media {MEDIA} | LiveKit {LIVEKIT}")
    web.run_app(create_app(), port=PORT, print=None)
