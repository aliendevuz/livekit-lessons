"""Backend 2: recording bo'laklarini qabul qiladi, saqlaydi, MP4 ga o'tkazadi va ko'rish uchun uzatadi.

Bazaga ulanmaydi. Kim nima qila olishini API backend imzolagan token hal qiladi.

Bitta dars uchun fayllar (RECORDINGS_DIR ichida):
    {room}.webm    brauzerdan kelgan xom yozuv (o'tkazilgach o'chiriladi)
    {room}.seq     navbatdagi bo'lak raqami
    {room}.done    dars tugagan, endi bo'lak qabul qilinmaydi
    {room}.mp4     siqilgan tayyor yozuv
    {room}.failed  o'tkazish xato bergan — xom webm o'zi beriladi
"""

import logging
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media")

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

MEDIA_SECRET = os.environ["MEDIA_SECRET"]
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", str(BASE_DIR / "recordings")))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
MAX_CHUNK_BYTES = 32 * 1024 * 1024

# Sifat/hajm: CRF katta bo'lsa fayl kichik, sifat past (23 — yaxshi, 28 — tejamkor).
VIDEO_CRF = os.getenv("VIDEO_CRF", "28")
# 0 = barcha yadrolar. Kuchsiz serverda API sekinlashmasligi uchun 1 qo'yish mumkin.
FFMPEG_THREADS = os.getenv("FFMPEG_THREADS", "0")

ROOM_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def find_ffmpeg() -> str:
    path = os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg")
    if path:
        return path
    # tizimda ffmpeg yo'q bo'lsa — pip bilan kelgan nusxasi
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG = find_ffmpeg()

# Bir vaqtda faqat bitta yozuv o'tkaziladi, qolganlari navbatda kutadi
converter = ThreadPoolExecutor(max_workers=1)
converting: set[str] = set()
progress: dict[str, int] = {}  # room -> necha foizi o'tkazildi

app = FastAPI(title="Media")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def authorize(token: str, room: str, act: str) -> None:
    # room fayl nomiga aylanadi, shuning uchun qat'iy tekshiriladi
    if not ROOM_RE.fullmatch(room):
        raise HTTPException(404, "recording topilmadi")
    try:
        claims = jwt.decode(token, MEDIA_SECRET, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "token yaroqsiz") from exc
    if claims.get("room") != room or claims.get("act") != act:
        raise HTTPException(403, "token bu amal uchun emas")


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "token yo'q")
    return authorization[7:]


def file_of(room: str, suffix: str) -> Path:
    return RECORDINGS_DIR / f"{room}.{suffix}"


def run_ffmpeg(room: str, arguments: list[str], total_seconds: float = 0) -> tuple[int, str, float]:
    """ffmpeg'ni ishga tushiradi va qayerga yetganini kuzatadi. (kod, xato matni, yetgan soniya) qaytaradi."""
    errors_path = file_of(room, "log")
    reached = 0.0
    with errors_path.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [FFMPEG, "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1", *arguments],
            stdout=subprocess.PIPE, stderr=errors, text=True,
        )
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit():
                reached = int(value) / 1_000_000
                if total_seconds:
                    progress[room] = min(99, int(reached * 100 / total_seconds))
        code = process.wait()
    message = errors_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    errors_path.unlink(missing_ok=True)
    return code, message, reached


def convert(room: str) -> None:
    """Xom webm'ni siqilgan MP4 ga o'tkazadi (H.264 + AAC, boshidan o'ynaladigan va suriladigan)."""
    source, target, partial = file_of(room, "webm"), file_of(room, "mp4"), file_of(room, "part")
    try:
        # Brauzer yozgan webm'da davomiylik yo'q. Foizni hisoblash uchun avval fayl
        # qayta kodlanmasdan o'qib chiqiladi — bu tez, faqat diskdan o'qish.
        _, _, duration = run_ffmpeg(room, ["-i", str(source), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"])
        code, message, _ = run_ffmpeg(room, [
            "-i", str(source),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", VIDEO_CRF, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", "-threads", FFMPEG_THREADS,
            "-f", "mp4", str(partial),
        ], duration)
        if code != 0:
            partial.unlink(missing_ok=True)
            file_of(room, "failed").write_text(message, encoding="utf-8")
            log.error("%s o'tkazilmadi, xom webm beriladi: %s", room, message[-500:])
            return
        before, after = source.stat().st_size, partial.stat().st_size
        partial.replace(target)
        source.unlink()
        file_of(room, "seq").unlink(missing_ok=True)
        log.info("%s tayyor: %.1f MB -> %.1f MB", room, before / 1e6, after / 1e6)
    finally:
        converting.discard(room)
        progress.pop(room, None)


@app.post("/recordings/{room}/chunks")
async def upload_chunk(room: str, seq: int, request: Request, authorization: str | None = Header(None)):
    """Navbatdagi bo'lakni fayl oxiriga qo'shadi. seq 0 dan boshlanadi va tartib bilan keladi."""
    authorize(bearer(authorization), room, "upload")
    if int(request.headers.get("content-length", 0)) > MAX_CHUNK_BYTES:
        raise HTTPException(413, "bo'lak juda katta")
    if file_of(room, "done").exists():
        raise HTTPException(409, "dars tugagan, yozuv yopilgan")

    seq_path = file_of(room, "seq")
    expected = int(seq_path.read_text()) if seq_path.exists() else 0
    if seq != expected:
        # qayta yuborilgan bo'lak ikki marta yozilmasligi uchun
        raise HTTPException(409, {"expected_seq": expected})

    # avval to'liq o'qiladi: aloqa uzilsa faylga yarim bo'lak tushmaydi
    body = await request.body()
    if not body or len(body) > MAX_CHUNK_BYTES:
        raise HTTPException(400, "bo'lak bo'sh yoki juda katta")
    with file_of(room, "webm").open("ab") as file:
        file.write(body)
    seq_path.write_text(str(expected + 1))
    return {"next_seq": expected + 1}


@app.post("/internal/recordings/{room}/finish")
def finish(room: str, authorization: str | None = Header(None)):
    """API backend dars tugaganda chaqiradi: yozuvni yopadi va MP4 ga o'tkazishni boshlaydi.

    Qayta chaqirsa bo'ladi — holatni qaytaradi: none | processing (progress: 0-99) | ready.
    """
    authorize(bearer(authorization), room, "finish")
    if file_of(room, "mp4").exists():
        return {"state": "ready", "file": f"{room}.mp4"}
    if not file_of(room, "webm").exists():
        return {"state": "none"}
    file_of(room, "done").touch()
    if file_of(room, "failed").exists():
        return {"state": "ready", "file": f"{room}.webm"}
    if room not in converting:
        converting.add(room)
        converter.submit(convert, room)
    # navbatda turgan yozuvda progress 0 bo'ladi
    return {"state": "processing", "progress": progress.get(room, 0)}


@app.get("/recordings/{room}")
def watch(room: str, token: str):
    """Recording'ni uzatadi (Range so'rovlari bilan). Token query'da, chunki <video> sarlavha yubora olmaydi."""
    authorize(token, room, "view")
    for suffix, media_type in (("mp4", "video/mp4"), ("webm", "video/webm")):
        path = file_of(room, suffix)
        if path.exists():
            return FileResponse(path, media_type=media_type)
    raise HTTPException(404, "recording topilmadi")
