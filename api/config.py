import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "app.db"))

# Birinchi admin (seed). ADMIN_PINCODE bo'sh bo'lsa admin yaratilmaydi.
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PINCODE = os.getenv("ADMIN_PINCODE", "")

# `livekit-server --dev` standart kalitlari
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
# LIVEKIT_URL brauzerga beriladi (tashqi manzil bo'lishi mumkin); API o'zi shu manzil orqali ulanadi
LIVEKIT_INTERNAL_URL = os.getenv("LIVEKIT_INTERNAL_URL") or LIVEKIT_URL
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "secret")

# Media backend: brauzer ko'radigan manzil va ikki backend o'rtasidagi umumiy kalit
MEDIA_URL = os.getenv("MEDIA_URL", "http://localhost:8001").rstrip("/")
# MEDIA_URL brauzerga beriladi; API media backend bilan shu manzil orqali gaplashadi
MEDIA_INTERNAL_URL = (os.getenv("MEDIA_INTERNAL_URL") or MEDIA_URL).rstrip("/")
MEDIA_SECRET = os.environ["MEDIA_SECRET"]

# Telegram. BOT_TOKEN bo'sh bo'lsa havolalar faqat logga yoziladi.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8000").rstrip("/")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# Sinov rejimi: login sahifasida tayyor userlar ro'yxati, pincode'siz kirish. Qarang: demo.py
DEMO_MODE = os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")

SESSION_DAYS = 30
LINK_BEFORE_MIN = 1
AUTO_END_AFTER_MIN = 30
