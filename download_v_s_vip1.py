#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
🚀 بوت تيليجرام الاحترافي لتحميل الفيديوهات والصوتيات من جميع منصات التواصل الاجتماعي
===================================================================================
المميزات:
- تحميل فيديو بأعلى جودة وبدون علامة مائية (YouTube, TikTok, Instagram, Facebook, X, Pinterest, Snapchat, Reddit, Threads, Likee...)
- دعم تحميل ألبومات صور تيك توك (TikTok Photo Slideshows) وقوائم تشغيل يوتيوب (Playlists)
- استخراج الصوت بصيغة MP3 مع إمكانية (إعادة التسمية، تغيير صورة الغلاف، تعديل الوصف/المؤدي)
- نظام اشتراك إجباري متكامل للقناة (https://t.me/Ell_Hoot) مع التحقق الفوري بضغطة زر
- لوحة تحكم أدمن متكاملة ومحمية بالكامل (إحصائيات يومية وكلية، إذاعة، حظر/فك حظر، تعديل الترحيب، رسائل المستخدمين والرد عليها، إدارة الكوكيز)
- أزرار ملونة ومنظمة مع أزرار (⬅️ رجوع) و (🏠 الرئيسية) في جميع القوائم
- قاعدة بيانات SQLite مدمجة وآمنة + نظام إعادة تشغيل تلقائي (Auto-Restart) عند حدوث أي خطأ

📦 المكتبات المطلوبة للتشغيل (قم بتثبيتها عبر الأمر التالي في التيرمينال):
    pip install -U python-telegram-bot yt-dlp httpx requests
    (اختياري لدعم رفع الملفات الأكبر من 50MB حتى 2GB):
    pip install -U pyrogram tgcrypto
    (تأكد أيضاً من وجود برنامج ffmpeg مثبتاً على السيرفر لمعالجة الصوتيات والفيديو)
===================================================================================
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import requests
import yt_dlp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import (
    BadRequest,
    Conflict as TelegramConflict,
    Forbidden,
    NetworkError,
    TimedOut as TelegramTimedOut,
)
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

# ═══════════════════════════════════════════════════════════════════════
# 📌 الإعدادات الأساسية (ضع التوكن والـ ID الخاص بك هنا)
# ═══════════════════════════════════════════════════════════════════════

TOKEN = "8853263450:AAFInewWao0Fr3V49koepB2bJxFyIwCaWJk"
ADMIN_ID = "1444139300"

# إعدادات قناة الاشتراك الإجباري
FORCE_SUB_CHANNEL_URL = "https://t.me/Ell_Hoot"
FORCE_SUB_CHANNEL_USERNAME = "@Ell_Hoot"

# (اختياري) إعدادات Pyrogram لرفع الفيديوهات الكبيرة جداً (حتى 2 جيجابايت)
# إذا تركتها كما هي سيعمل البوت بشكل طبيعي تماماً عبر Bot API الرسمي
API_ID = 0
API_HASH = ""

# ═══════════════════════════════════════════════════════════════════════
# 🛠️ تهيئة البيئة، المسارات، وسجل الأخطاء (Logging)
# ═══════════════════════════════════════════════════════════════════════

# التأكد من وجود مسار Node.js في بيئة النظام لدعم فك تشفير يوتيوب في yt-dlp
_existing_path = os.environ.get("PATH", "")
_node_bin = shutil.which("node") or ""
if _node_bin:
    _node_dir = os.path.dirname(_node_bin)
    if _node_dir not in _existing_path:
        os.environ["PATH"] = f"{_node_dir}:{_existing_path}"

# إعداد نظام تسجيل الأحداث (Logging)
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram-downloader")
logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_admin_id(raw_id: Any) -> int:
    """دالة لتحويل معرف الأدمن إلى رقم صحيح بأمان مع دعم القيمة الافتراضية."""
    try:
        cleaned = str(raw_id).strip()
        if cleaned.isdigit():
            return int(cleaned)
    except Exception:
        pass
    # رقم افتراضي احتياطي في حال لم يتم تغيير النص بعد
    return 8220915719


OWNER_ID: int = parse_admin_id(ADMIN_ID)

# الثوابت العامة للبوت
MAX_CONCURRENT_DOWNLOADS = 50
DOWNLOAD_TIMEOUT_SECONDS = 20 * 60
PLAYLIST_WORKERS = 10
USERS_PER_PAGE = 15
MESSAGES_PER_PAGE = 10
COOKIES_DIR = Path("cookies")
DB_PATH = Path("bot_database.db")

download_slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

# المنصات المدعومة لإدارة الكوكيز
SUPPORTED_PLATFORMS_BUTTONS = [
    ("🔴 YouTube", "youtube"),
    ("⚫ TikTok", "tiktok"),
    ("🟣 Instagram", "instagram"),
    ("🔵 Facebook", "facebook"),
    ("⚫ X / Twitter", "twitter"),
    ("🔴 Pinterest", "pinterest"),
    ("🟡 Snapchat", "snapchat"),
    ("⚫ Threads", "threads"),
    ("🟠 Likee", "likee"),
    ("🟠 Reddit", "reddit"),
]

PLATFORM_HOSTS = {
    "youtube": {"youtube.com", "youtu.be", "youtube-nocookie.com"},
    "tiktok": {"tiktok.com"},
    "instagram": {"instagram.com"},
    "twitter": {"twitter.com", "x.com"},
    "pinterest": {"pinterest.com", "pin.it"},
    "facebook": {"facebook.com", "fb.com", "fb.watch", "m.facebook.com"},
    "snapchat": {"snapchat.com"},
    "threads": {"threads.net", "threads.com"},
    "likee": {"likee.video"},
    "reddit": {"reddit.com", "redd.it"},
}

# الرسالة الترحيبية الافتراضية
DEFAULT_WELCOME_MESSAGE = (
    "✨ *أهلاً بك يا {name} في بوت التحميل الشامل!* ✨\n\n"
    "🎬 *البوت الأول لتحميل الفيديوهات والصوتيات من جميع منصات التواصل الاجتماعي بأعلى جودة وبدون علامة مائية.*\n\n"
    "📌 *ماذا يمكنك أن تفعل هنا؟*\n"
    "• 📥 أرسل أي رابط فيديو وسيتم تحميله فوراً.\n"
    "• 🎵 استخرج الصوت بصيغة MP3 مع تغيير الاسم والغلاف والوصف.\n"
    "• 📸 تحميل ألبومات صور تيك توك وقوائم تشغيل يوتيوب.\n\n"
    "👇 *اضغط على «🚀 ابدأ الآن» أو أرسل الرابط مباشرة في المحادثة:*"
)

# ═══════════════════════════════════════════════════════════════════════
# 🗄️ الفئة الأولى: إدارة قاعدة البيانات (DatabaseManager)
# ═══════════════════════════════════════════════════════════════════════


class DatabaseManager:
    """فئة متكاملة لإدارة قاعدة بيانات SQLite لحفظ المستخدمين، الإحصائيات، الإعدادات، والرسائل."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.lock = asyncio.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_tables()

    def _init_tables(self) -> None:
        """إنشاء الجداول الضرورية إذا لم تكن موجودة."""
        cursor = self.conn.cursor()
        # جدول المستخدمين
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                joined_at TEXT,
                is_banned INTEGER NOT NULL DEFAULT 0,
                is_stopped INTEGER NOT NULL DEFAULT 0,
                downloads_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # جدول الإحصائيات اليومية (الرسائل والتحميلات لكل يوم)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_stats (
                stat_date TEXT PRIMARY KEY,
                messages_count INTEGER NOT NULL DEFAULT 0,
                downloads_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # جدول إعدادات البوت (رسالة الترحيب، حالة الاشتراك الإجباري، إلخ)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # جدول رسائل المستخدمين للأدمن (تذاكر الدعم)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                message_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_replied INTEGER NOT NULL DEFAULT 0,
                reply_text TEXT DEFAULT ''
            )
            """
        )
        # جدول كوكيز المنصات
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_cookies (
                platform TEXT PRIMARY KEY,
                cookie_path TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    async def register_or_update_user(self, user: Any) -> bool:
        """تسجيل مستخدم جديد أو تحديث بياناته، ويُرجع True إذا كان مستخدماً جديداً."""
        if user is None:
            return False
        async with self.lock:
            row = self.conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?", (user.id,)
            ).fetchone()
            is_new = row is None
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.conn.execute(
                """
                INSERT INTO users (user_id, first_name, last_name, username, joined_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    username = excluded.username
                """,
                (
                    user.id,
                    user.first_name or "",
                    user.last_name or "",
                    user.username or "",
                    now_str,
                ),
            )
            self.conn.commit()
            return is_new

    async def increment_daily_messages(self) -> None:
        """زيادة عداد الرسائل اليومية."""
        today = self._today_str()
        async with self.lock:
            self.conn.execute(
                """
                INSERT INTO daily_stats (stat_date, messages_count, downloads_count)
                VALUES (?, 1, 0)
                ON CONFLICT(stat_date) DO UPDATE SET
                    messages_count = messages_count + 1
                """,
                (today,),
            )
            self.conn.commit()

    async def increment_download(self, user_id: int) -> None:
        """زيادة عداد التحميلات للمستخدم وللإحصائيات اليومية."""
        today = self._today_str()
        async with self.lock:
            self.conn.execute(
                "UPDATE users SET downloads_count = downloads_count + 1 WHERE user_id = ?",
                (user_id,),
            )
            self.conn.execute(
                """
                INSERT INTO daily_stats (stat_date, messages_count, downloads_count)
                VALUES (?, 0, 1)
                ON CONFLICT(stat_date) DO UPDATE SET
                    downloads_count = downloads_count + 1
                """,
                (today,),
            )
            self.conn.commit()

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        """جلب بيانات مستخدم واحد."""
        async with self.lock:
            row = self.conn.execute(
                """
                SELECT user_id, first_name, last_name, username, joined_at,
                       is_banned, is_stopped, downloads_count
                FROM users WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "first": row[1],
            "last": row[2],
            "username": row[3],
            "joined": row[4],
            "banned": bool(row[5]),
            "stopped": bool(row[6]),
            "downloads": row[7],
        }

    async def get_all_users(self) -> list[dict[str, Any]]:
        """جلب قائمة بجميع المستخدمين مرتبة من الأحدث للأقدم."""
        async with self.lock:
            rows = self.conn.execute(
                """
                SELECT user_id, first_name, last_name, username, joined_at,
                       is_banned, is_stopped, downloads_count
                FROM users ORDER BY rowid DESC
                """
            ).fetchall()
        return [
            {
                "id": r[0],
                "first": r[1],
                "last": r[2],
                "username": r[3],
                "joined": r[4],
                "banned": bool(r[5]),
                "stopped": bool(r[6]),
                "downloads": r[7],
            }
            for r in rows
        ]

    async def set_ban(self, user_id: int, ban: bool) -> bool:
        """حظر أو فك حظر مستخدم."""
        async with self.lock:
            cur = self.conn.execute(
                "UPDATE users SET is_banned = ? WHERE user_id = ?",
                (int(ban), user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    async def set_stop(self, user_id: int, stop: bool) -> bool:
        """إيقاف سري أو استئناف مستخدم."""
        async with self.lock:
            cur = self.conn.execute(
                "UPDATE users SET is_stopped = ? WHERE user_id = ?",
                (int(stop), user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    async def is_banned(self, user_id: int) -> bool:
        if user_id == OWNER_ID:
            return False
        async with self.lock:
            row = self.conn.execute(
                "SELECT is_banned FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return bool(row[0]) if row else False

    async def is_stopped(self, user_id: int) -> bool:
        if user_id == OWNER_ID:
            return False
        async with self.lock:
            row = self.conn.execute(
                "SELECT is_stopped FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return bool(row[0]) if row else False

    async def get_stats_summary(self) -> dict[str, int]:
        """جلب ملخص كامل للإحصائيات لعرضها في لوحة الأدمن."""
        today = self._today_str()
        async with self.lock:
            total_users = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            banned_users = self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_banned = 1"
            ).fetchone()[0]
            stopped_users = self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_stopped = 1"
            ).fetchone()[0]
            total_downloads = (
                self.conn.execute("SELECT SUM(downloads_count) FROM users").fetchone()[0]
                or 0
            )
            today_row = self.conn.execute(
                "SELECT messages_count, downloads_count FROM daily_stats WHERE stat_date = ?",
                (today,),
            ).fetchone()
            today_messages = today_row[0] if today_row else 0
            today_downloads = today_row[1] if today_row else 0
            unreplied_msgs = self.conn.execute(
                "SELECT COUNT(*) FROM support_messages WHERE is_replied = 0"
            ).fetchone()[0]

        return {
            "total_users": total_users,
            "active_users": max(0, total_users - banned_users - stopped_users),
            "banned_users": banned_users,
            "stopped_users": stopped_users,
            "total_downloads": total_downloads,
            "today_messages": today_messages,
            "today_downloads": today_downloads,
            "unreplied_msgs": unreplied_msgs,
        }

    # --- إعدادات البوت ---
    async def get_setting(self, key: str, default: str = "") -> str:
        async with self.lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with self.lock:
            self.conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            self.conn.commit()

    # --- رسائل المستخدمين للأدمن ---
    async def add_support_message(
        self, user_id: int, user_name: str, username: str, text: str
    ) -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with self.lock:
            cur = self.conn.execute(
                """
                INSERT INTO support_messages (user_id, user_name, username, message_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, user_name, username, text, now_str),
            )
            self.conn.commit()
            return int(cur.lastrowid or 0)

    async def get_support_messages(self, only_unreplied: bool = False) -> list[dict[str, Any]]:
        async with self.lock:
            query = (
                "SELECT id, user_id, user_name, username, message_text, created_at, is_replied, reply_text "
                "FROM support_messages "
            )
            if only_unreplied:
                query += "WHERE is_replied = 0 "
            query += "ORDER BY id DESC LIMIT 100"
            rows = self.conn.execute(query).fetchall()
        return [
            {
                "id": r[0],
                "user_id": r[1],
                "user_name": r[2],
                "username": r[3],
                "text": r[4],
                "created_at": r[5],
                "is_replied": bool(r[6]),
                "reply_text": r[7],
            }
            for r in rows
        ]

    async def get_support_message_by_id(self, msg_id: int) -> dict[str, Any] | None:
        async with self.lock:
            r = self.conn.execute(
                """
                SELECT id, user_id, user_name, username, message_text, created_at, is_replied, reply_text
                FROM support_messages WHERE id = ?
                """,
                (msg_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r[0],
            "user_id": r[1],
            "user_name": r[2],
            "username": r[3],
            "text": r[4],
            "created_at": r[5],
            "is_replied": bool(r[6]),
            "reply_text": r[7],
        }

    async def mark_support_replied(self, msg_id: int, reply_text: str) -> None:
        async with self.lock:
            self.conn.execute(
                "UPDATE support_messages SET is_replied = 1, reply_text = ? WHERE id = ?",
                (reply_text, msg_id),
            )
            self.conn.commit()

    # --- إدارة الكوكيز ---
    async def save_cookie(self, platform: str, content: str) -> Path:
        COOKIES_DIR.mkdir(exist_ok=True)
        safe = re.sub(r"[^\w\-]", "_", platform.lower())
        path = COOKIES_DIR / f"{safe}.txt"
        path.write_text(content, encoding="utf-8")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with self.lock:
            self.conn.execute(
                """
                INSERT INTO platform_cookies (platform, cookie_path, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    cookie_path = excluded.cookie_path,
                    updated_at = excluded.updated_at
                """,
                (platform.lower(), str(path), now_str),
            )
            self.conn.commit()
        PLATFORM_COOKIES[platform.lower()] = path
        return path

    async def get_all_cookies(self) -> list[tuple[str, str]]:
        async with self.lock:
            return self.conn.execute(
                "SELECT platform, updated_at FROM platform_cookies ORDER BY platform"
            ).fetchall()

    async def delete_cookie(self, platform: str) -> bool:
        async with self.lock:
            row = self.conn.execute(
                "SELECT cookie_path FROM platform_cookies WHERE platform = ?",
                (platform.lower(),),
            ).fetchone()
            if row:
                p = Path(row[0])
                if p.is_file():
                    try:
                        p.unlink()
                    except Exception:
                        pass
                self.conn.execute(
                    "DELETE FROM platform_cookies WHERE platform = ?",
                    (platform.lower(),),
                )
                self.conn.commit()
                PLATFORM_COOKIES.pop(platform.lower(), None)
                return True
        return False

    def load_cookies_into_memory(self) -> dict[str, Path]:
        cookies_map: dict[str, Path] = {}
        rows = self.conn.execute(
            "SELECT platform, cookie_path FROM platform_cookies"
        ).fetchall()
        for plat, pstr in rows:
            p = Path(pstr)
            if p.is_file():
                cookies_map[plat.lower()] = p
        return cookies_map


# إنشاء نسخة قاعدة البيانات وتحميل الكوكيز المحفوظة
db = DatabaseManager(DB_PATH)
PLATFORM_COOKIES: dict[str, Path] = db.load_cookies_into_memory()

# ═══════════════════════════════════════════════════════════════════════
# 📦 إعداد Pyrogram الاختياري للملفات الضخمة (أكبر من 50MB)
# ═══════════════════════════════════════════════════════════════════════

pyro_client: Any = None
try:
    if API_ID and API_HASH and TOKEN and TOKEN != "ضع_التوكن_هنا":
        from pyrogram import Client
        from pyrogram.types import (
            InlineKeyboardButton as PyroInlineKeyboardButton,
            InlineKeyboardMarkup as PyroInlineKeyboardMarkup,
        )

        pyro_client = Client(
            "bot_session",
            api_id=int(API_ID),
            api_hash=str(API_HASH),
            bot_token=TOKEN,
            in_memory=True,
        )
except Exception as _pyro_err:
    logger.info("Pyrogram is disabled or not configured: %s", _pyro_err)
    pyro_client = None


def _to_pyro_markup(markup: InlineKeyboardMarkup | None) -> Any:
    """تحويل أزرار python-telegram-bot إلى صيغة Pyrogram عند الحاجة."""
    if markup is None or pyro_client is None:
        return None
    try:
        from pyrogram.types import (
            InlineKeyboardButton as PyroBtn,
            InlineKeyboardMarkup as PyroMarkup,
        )

        rows = []
        for row in markup.inline_keyboard:
            pyro_row = []
            for btn in row:
                if getattr(btn, "url", None):
                    pyro_row.append(PyroBtn(text=btn.text, url=btn.url))
                else:
                    pyro_row.append(
                        PyroBtn(text=btn.text, callback_data=btn.callback_data or "noop")
                    )
            rows.append(pyro_row)
        return PyroMarkup(rows)
    except Exception:
        return None


async def upload_large_media_pyrogram(
    chat_id: int,
    media_path: Path,
    media_type: str,
    caption: str,
    reply_to_message_id: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    duration: int | None = None,
    performer: str | None = None,
    title: str | None = None,
    thumb: Path | None = None,
) -> Any:
    """رفع الملفات الكبيرة عبر Pyrogram في حال كان مفعلاً."""
    if pyro_client is None:
        return None
    pyro_markup = _to_pyro_markup(reply_markup)
    if not pyro_client.is_connected:
        try:
            await pyro_client.start()
        except Exception as e:
            logger.warning("Pyrogram start failed: %s", e)
            return None

    try:
        thumb_str = str(thumb) if thumb and thumb.exists() else None
        if media_type == "video":
            return await pyro_client.send_video(
                chat_id=chat_id,
                video=str(media_path),
                caption=caption,
                duration=duration or 0,
                thumb=thumb_str,
                reply_to_message_id=reply_to_message_id,
                reply_markup=pyro_markup,
                supports_streaming=True,
            )
        elif media_type == "audio":
            return await pyro_client.send_audio(
                chat_id=chat_id,
                audio=str(media_path),
                caption=caption,
                duration=duration or 0,
                performer=performer,
                title=title,
                thumb=thumb_str,
                reply_to_message_id=reply_to_message_id,
                reply_markup=pyro_markup,
            )
        else:
            return await pyro_client.send_document(
                chat_id=chat_id,
                document=str(media_path),
                caption=caption,
                thumb=thumb_str,
                reply_to_message_id=reply_to_message_id,
                reply_markup=pyro_markup,
            )
    except Exception as e:
        logger.warning("Pyrogram upload failed: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════
# 🎨 دوال بناء الأزرار الملونة والمنظمة (Keyboards Builder)
# ═══════════════════════════════════════════════════════════════════════


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """القائمة الرئيسية الملونة للمستخدم (مع زر خاص للأدمن)."""
    buttons = [
        [InlineKeyboardButton("🚀 ابدأ الآن (طريقة التحميل)", callback_data="menu_start_now")],
        [
            InlineKeyboardButton("👤 حسابي وإحصائياتي", callback_data="menu_account"),
            InlineKeyboardButton("🌐 المنصات المدعومة", callback_data="menu_platforms"),
        ],
        [
            InlineKeyboardButton("📩 تواصل مع الإدارة", callback_data="menu_contact_admin"),
            InlineKeyboardButton("ℹ️ مساعدة وأوامر", callback_data="menu_help"),
        ],
    ]
    if is_admin:
        buttons.append(
            [InlineKeyboardButton("🔐 لوحة تحكم الأدمن", callback_data="adm_main")]
        )
    return InlineKeyboardMarkup(buttons)


def back_and_home_keyboard(back_callback: str = "menu_home") -> InlineKeyboardMarkup:
    """أزرار الرجوع والصفحة الرئيسية القياسية في كل قائمة فرعية."""
    row = []
    if back_callback != "menu_home":
        row.append(InlineKeyboardButton("⬅️ رجوع", callback_data=back_callback))
    row.append(InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"))
    return InlineKeyboardMarkup([row])


def force_sub_keyboard() -> InlineKeyboardMarkup:
    """أزرار الاشتراك الإجباري والتحقق من الاشتراك."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 اشترك في القناة الآن", url=FORCE_SUB_CHANNEL_URL
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ تحقّق من الاشتراك", callback_data="check_sub"
                )
            ],
        ]
    )


def video_actions_keyboard(session_key: str) -> InlineKeyboardMarkup:
    """الأزرار الملونة أسفل الفيديو المحمّل."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎵 تحميل الملف الصوتي (MP3)",
                    callback_data=f"audio:{session_key}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 تفاصيل الفيديو التقنية",
                    callback_data=f"vinfo:{session_key}",
                ),
                InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
            ],
        ]
    )


def audio_actions_keyboard(session_key: str) -> InlineKeyboardMarkup:
    """الأزرار الملونة أسفل الملف الصوتي المحمّل."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ إعادة تسمية الملف", callback_data=f"rename:{session_key}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🖼️ وضع غلاف للصوت", callback_data=f"cover:{session_key}"
                ),
                InlineKeyboardButton(
                    "📝 وضع وصف للملف", callback_data=f"desc:{session_key}"
                ),
            ],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home")],
        ]
    )


def admin_main_keyboard(unreplied_count: int = 0) -> InlineKeyboardMarkup:
    """لوحة تحكم الأدمن الرئيسية بجميع أقسامها."""
    msg_badge = f" ({unreplied_count} جديد)" if unreplied_count > 0 else ""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 الإحصائيات الشاملة", callback_data="adm_stats"),
                InlineKeyboardButton("📢 بث رسالة (Broadcast)", callback_data="adm_broadcast"),
            ],
            [
                InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="adm_users_0"),
                InlineKeyboardButton("🔍 بحث/حظر بالـ ID", callback_data="adm_search_user"),
            ],
            [
                InlineKeyboardButton(
                    f"📩 رسائل المستخدمين{msg_badge}", callback_data="adm_msgs_0"
                ),
            ],
            [
                InlineKeyboardButton("⚙️ إعدادات البوت والترحيب", callback_data="adm_settings"),
                InlineKeyboardButton("🍪 إدارة الكوكيز", callback_data="adm_cookies"),
            ],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home")],
        ]
    )


# ═══════════════════════════════════════════════════════════════════════
# 🔍 دوال التحقق من الاشتراك الإجباري وتنسيق البيانات
# ═══════════════════════════════════════════════════════════════════════


async def check_user_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    التحقق مما إذا كان المستخدم مشتركاً في قناة الاشتراك الإجباري.
    الأدمن معفي تلقائياً، وفي حال لم يكن البوت مشرفاً في القناة لا يتعطل البوت.
    """
    if user_id == OWNER_ID:
        return True

    force_sub_enabled = await db.get_setting("force_sub_enabled", "1")
    if force_sub_enabled != "1":
        return True

    channel_id = await db.get_setting("force_sub_channel", FORCE_SUB_CHANNEL_USERNAME)
    if not channel_id:
        return True

    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ("left", "kicked", "banned"):
            return False
        return True
    except BadRequest as exc:
        # في حال لم يرفع صاحب البوت البوت كأدمن في القناة بعد، نسجل تحذيراً في اللوج
        logger.warning(
            "Force-sub check warning for channel %s (make sure bot is admin in channel): %s",
            channel_id,
            exc,
        )
        return False
    except Exception as exc:
        logger.warning("Unexpected error checking subscription: %s", exc)
        return True


async def send_force_sub_prompt(update: Update) -> None:
    """إرسال رسالة الاشتراك الإجباري للمستخدم غير المشترك."""
    user_name = (
        html.escape(update.effective_user.first_name)
        if update.effective_user and update.effective_user.first_name
        else "صديقي"
    )
    text = (
        f"⚠️ <b>عذراً يا {user_name}، لا يمكنك استخدام البوت قبل الاشتراك في قناة البوت الرسمية!</b>\n\n"
        f"📢 <b>القناة:</b> <a href='{FORCE_SUB_CHANNEL_URL}'>اضغط هنا للاشتراك ({FORCE_SUB_CHANNEL_USERNAME})</a>\n\n"
        "✅ <i>بعد الاشتراك، اضغط على زر «تحقّق من الاشتراك» بالأسفل لتفعيل البوت فوراً:</i>"
    )
    if update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=force_sub_keyboard(),
                disable_web_page_preview=True,
            )
            return
        except Exception:
            pass
    if update.effective_message:
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=force_sub_keyboard(),
            disable_web_page_preview=True,
        )


def extract_media_url(text: str) -> str | None:
    """استخراج أول رابط HTTP/HTTPS صالح من النص."""
    for raw_url in URL_PATTERN.findall(text):
        candidate = raw_url.rstrip(".,!?؛،)]}")
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
    return None


def platform_name(url: str) -> str:
    """تحديد اسم المنصة من الرابط."""
    hostname = (urlparse(url).hostname or "").lower()
    for name, domains in PLATFORM_HOSTS.items():
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            if name == "twitter":
                return "X / Twitter"
            return name.capitalize()
    return "المصدر"


def is_youtube_playlist(url: str) -> bool:
    """التحقق مما إذا كان الرابط لقائمة تشغيل يوتيوب."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    is_yt = any(
        hostname == d or hostname.endswith(f".{d}") for d in PLATFORM_HOSTS["youtube"]
    )
    if not is_yt:
        return False
    qs = parse_qs(parsed.query)
    return bool(qs.get("list")) and not qs.get("v")


def format_count(value: Any) -> str:
    if value is None:
        return "غير متاح"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def format_duration(value: Any) -> str:
    if value is None:
        return "غير متاح"
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        if hours
        else f"{minutes:02d}:{seconds:02d}"
    )


def format_bytes(value: Any) -> str:
    if value is None:
        return "غير متاح"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return "غير متاح"


def format_date(value: Any) -> str:
    if not value:
        return "غير متاح"
    value_str = str(value)
    try:
        return datetime.strptime(value_str, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return value_str


def safe_html(value: Any, limit: int = 180) -> str:
    text = str(value or "غير متاح").strip()
    return html.escape(text[:limit], quote=False)


def clean_filename(value: str) -> str:
    """تنظيف اسم الملف الصوتي مع دعم الحروف العربية والإنجليزية."""
    cleaned = re.sub(r"[\\/:*?\"<>|{}\[\]\x00-\x1f]", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if cleaned.lower().endswith(".mp3"):
        cleaned = cleaned[:-4].rstrip(" .")
    return (cleaned[:90] or "ملف_صوتي") + ".mp3"


# ═══════════════════════════════════════════════════════════════════════
# 🎬 الفئة الثانية: محرك التحميل والمعالجة (MediaDownloader)
# ═══════════════════════════════════════════════════════════════════════


class MediaDownloader:
    """محرك تحميل الفيديوهات، الصوتيات، ألبومات تيك توك، وقوائم يوتيوب."""

    @staticmethod
    def source_metadata(info: dict[str, Any], media_path: Path) -> dict[str, str]:
        width = info.get("width")
        height = info.get("height")
        resolution = f"{width}x{height}" if width and height else info.get("resolution")
        uploader = (
            info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or "غير متاح"
        )
        platform = (
            info.get("extractor_key")
            or info.get("extractor")
            or urlparse(str(info.get("webpage_url") or "")).netloc
            or "غير معروف"
        )
        return {
            "title": str(info.get("title") or media_path.stem),
            "uploader": str(uploader),
            "uploader_id": str(info.get("uploader_id") or info.get("channel_id") or "غير متاح"),
            "platform": str(platform),
            "duration": format_duration(info.get("duration")),
            "duration_seconds": str(int(float(info.get("duration") or 0))),
            "resolution": str(resolution or "غير متاح"),
            "format": str(info.get("ext") or media_path.suffix.lstrip(".") or "mp4"),
            "format_note": str(info.get("format_note") or "أعلى جودة"),
            "video_codec": str(info.get("vcodec") or "غير متاح"),
            "audio_codec": str(info.get("acodec") or "غير متاح"),
            "size": format_bytes(media_path.stat().st_size if media_path.exists() else 0),
            "published": format_date(info.get("upload_date")),
            "views": format_count(info.get("view_count")),
            "likes": format_count(info.get("like_count")),
            "comments": format_count(info.get("comment_count")),
            "id": str(info.get("id") or "غير متاح"),
            "url": str(info.get("webpage_url") or ""),
        }

    @staticmethod
    def build_caption(metadata: dict[str, str], custom_desc: str | None = None) -> str:
        """بناء كابشن أنيق ومختصر يرفق مع الفيديو أو الصوت."""
        title = safe_html(metadata.get("title", "فيديو"), 200)
        uploader = safe_html(metadata.get("uploader", "غير متاح"), 70)
        platform = safe_html(metadata.get("platform", "المصدر"), 40)
        duration = safe_html(metadata.get("duration", "غير متاح"), 20)
        size = safe_html(metadata.get("size", "غير متاح"), 20)

        lines = [
            f"🎬 <b>{title}</b>",
            f"👤 <b>القناة/الحساب:</b> <i>{uploader}</i>",
            f"🌐 <b>المنصة:</b> <code>{platform}</code>  |  ⏱️ <b>المدة:</b> <code>{duration}</code>  |  📦 <b>الحجم:</b> <code>{size}</code>",
        ]
        if custom_desc:
            lines.append(f"\n📝 <b>الوصف:</b> {safe_html(custom_desc, 300)}")
        return "\n".join(lines)

    @staticmethod
    def build_technical_details_text(metadata: dict[str, str]) -> str:
        """بناء نافذة التفاصيل التقنية الكاملة للفيديو."""
        return (
            f"📊 <b>التفاصيل التقنية والإحصائيات الكاملة:</b>\n\n"
            f"📌 <b>العنوان:</b> {safe_html(metadata.get('title'), 150)}\n"
            f"👤 <b>الناشر:</b> <code>{safe_html(metadata.get('uploader'), 60)}</code>\n"
            f"🌐 <b>المنصة:</b> <code>{safe_html(metadata.get('platform'), 40)}</code>\n"
            f"⏱️ <b>المدة:</b> <code>{safe_html(metadata.get('duration'), 20)}</code>\n"
            f"📐 <b>الدقة:</b> <code>{safe_html(metadata.get('resolution'), 25)}</code>\n"
            f"🎞️ <b>الصيغة والجودة:</b> <code>{safe_html(metadata.get('format'), 15)} ({safe_html(metadata.get('format_note'), 30)})</code>\n"
            f"📦 <b>الحجم:</b> <code>{safe_html(metadata.get('size'), 20)}</code>\n"
            f"📅 <b>تاريخ النشر:</b> <code>{safe_html(metadata.get('published'), 20)}</code>\n\n"
            f"👁️ <b>المشاهدات:</b> <code>{safe_html(metadata.get('views'), 20)}</code>\n"
            f"❤️ <b>الإعجابات:</b> <code>{safe_html(metadata.get('likes'), 20)}</code>\n"
            f"💬 <b>التعليقات:</b> <code>{safe_html(metadata.get('comments'), 20)}</code>"
        )

    @staticmethod
    def convert_cover_to_jpeg(source: Path, directory: Path) -> Path | None:
        """تحويل الصورة المصغرة إلى JPEG متوافق مع تيليجرام باستخدام ffmpeg."""
        target = directory / "cover.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(source),
                    "-vf",
                    "scale='min(600,iw)':-2",
                    "-q:v",
                    "4",
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return target if target.is_file() and target.stat().st_size > 0 else None

    @classmethod
    def download_media(
        cls, url: str, mode: str = "video"
    ) -> tuple[Path, dict[str, str], Path | None]:
        """تحميل الفيديو أو الصوت عبر yt-dlp مع دعم تعدد الجودات والكوكيز."""
        plat = platform_name(url).lower()
        is_youtube = "youtube" in plat

        if is_youtube:
            quality_profiles = (
                ("bestvideo+bestaudio/best", "أفضل جودة متاحة"),
                ("bestvideo[height<=1080]+bestaudio/best", "جودة 1080p"),
                ("bestvideo[height<=720]+bestaudio/best", "جودة 720p"),
                ("best", "أفضل صيغة متاحة"),
            )
        else:
            quality_profiles = (
                ("bestvideo+bestaudio/best", "أفضل جودة متاحة"),
                ("bestvideo[height<=1080]+bestaudio/best[height<=1080]/best", "جودة 1080p"),
                ("bestvideo[height<=720]+bestaudio/best[height<=720]/best", "جودة 720p"),
                ("best", "أفضل صيغة متاحة"),
            )

        with tempfile.TemporaryDirectory(prefix="tg-dl-") as temp_dir:
            directory = Path(temp_dir)
            last_error: Exception | None = None

            for format_selector, quality_label in quality_profiles:
                try:
                    if mode == "audio":
                        format_selector = "bestaudio/best"

                    output_template = str(directory / "%(title).80s-%(id)s.%(ext)s")
                    options: dict[str, Any] = {
                        "format": format_selector,
                        "outtmpl": output_template,
                        "merge_output_format": "mp4",
                        "noplaylist": True,
                        "quiet": True,
                        "no_warnings": True,
                        "retries": 8,
                        "fragment_retries": 8,
                        "extractor_retries": 4,
                        "concurrent_fragment_downloads": 16,
                        "buffersize": 16 * 1024 * 1024,
                        "http_chunk_size": 10 * 1024 * 1024,
                        "file_access_retries": 5,
                        "socket_timeout": 30,
                        "continuedl": True,
                        "writethumbnail": True,
                        "sleep_interval": 0,
                        "sleep_interval_requests": 0,
                        "restrictfilenames": True,
                        "overwrites": True,
                        "geo_bypass": True,
                        "http_headers": {
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/131.0.0.0 Safari/537.36"
                            )
                        },
                    }

                    if is_youtube:
                        options["extractor_args"] = {
                            "youtube": {
                                "player_client": [
                                    "ios",
                                    "android",
                                    "tv_embedded",
                                    "mweb",
                                ]
                            }
                        }

                    if "pinterest" in plat:
                        options["http_headers"]["Referer"] = "https://www.pinterest.com/"

                    # فحص ما إذا كان هناك ملف كوكيز مرفوع لهذه المنصة
                    for key, cookie_file in PLATFORM_COOKIES.items():
                        if (key in plat or plat in key) and cookie_file.is_file():
                            options["cookiefile"] = str(cookie_file)
                            break

                    if mode == "audio":
                        options["postprocessors"] = [
                            {
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "192",
                            }
                        ]

                    with yt_dlp.YoutubeDL(options) as downloader:
                        info = downloader.extract_info(url, download=True)
                        if not isinstance(info, dict):
                            raise RuntimeError("لم يُرجع المصدر بيانات صالحة.")

                    candidates = [
                        path
                        for path in directory.iterdir()
                        if path.is_file()
                        and path.suffix.lower()
                        not in {".part", ".ytdl", ".jpg", ".jpeg", ".png", ".webp", ".json"}
                    ]
                    if not candidates:
                        raise RuntimeError("لم يتم إنشاء ملف الوسائط بعد التحميل.")

                    media_path = max(candidates, key=lambda p: p.stat().st_mtime)
                    logger.info(
                        "Downloaded %s (%s, %.1f MB)",
                        info.get("title") or "media",
                        quality_label,
                        media_path.stat().st_size / 1024 / 1024,
                    )

                    fd, persistent_name = tempfile.mkstemp(suffix=media_path.suffix)
                    os.close(fd)
                    persistent_path = Path(persistent_name)
                    shutil.copy2(media_path, persistent_path)

                    metadata = cls.source_metadata(info, persistent_path)

                    # تجهيز الغلاف المصغر إن وجد
                    persistent_cover: Path | None = None
                    cover_candidates = [
                        path
                        for path in directory.iterdir()
                        if path.is_file()
                        and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                    ]
                    if cover_candidates:
                        cover_path = cls.convert_cover_to_jpeg(
                            max(cover_candidates, key=lambda p: p.stat().st_mtime),
                            directory,
                        )
                        if cover_path is not None:
                            cfd, cover_name = tempfile.mkstemp(suffix=".jpg")
                            os.close(cfd)
                            persistent_cover = Path(cover_name)
                            shutil.copy2(cover_path, persistent_cover)

                    return persistent_path, metadata, persistent_cover

                except Exception as error:
                    last_error = error
                    logger.warning("Download profile (%s) failed: %s", quality_label, error)
                    for old_file in directory.iterdir():
                        old_file.unlink(missing_ok=True)
                    if mode == "audio":
                        break

            if last_error is not None:
                raise last_error
            raise RuntimeError("فشل التنزيل لسبب غير معروف.")

    @classmethod
    def download_tiktok_photos(cls, url: str) -> tuple[list[Path], dict[str, str]]:
        """تحميل ألبومات الصور من تيك توك (Photo Slideshows) إن كان الرابط ألبوم صور."""
        with tempfile.TemporaryDirectory(prefix="tiktok-photo-") as temp_dir:
            directory = Path(temp_dir)
            options: dict[str, Any] = {
                "outtmpl": str(directory / "%(autonumber)03d_%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "retries": 5,
                "socket_timeout": 30,
                "http_headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                    )
                },
            }
            for key, cookie_file in PLATFORM_COOKIES.items():
                if "tiktok" in key.lower() and cookie_file.is_file():
                    options["cookiefile"] = str(cookie_file)
                    break

            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                if not isinstance(info, dict):
                    return [], {}
            except Exception as exc:
                logger.debug("TikTok photo check: %s", exc)
                return [], {}

            image_exts = {".jpg", ".jpeg", ".png", ".webp"}
            skip_exts = {".json", ".part", ".ytdl", ".tmp"}
            all_files = [p for p in directory.iterdir() if p.is_file()]

            non_images = [
                p
                for p in all_files
                if p.suffix.lower() not in image_exts and p.suffix.lower() not in skip_exts
            ]
            if non_images:
                return [], {}

            images = sorted(
                [p for p in all_files if p.suffix.lower() in image_exts],
                key=lambda p: p.name,
            )
            if not images:
                return [], {}

            result: list[Path] = []
            for src in images[:10]:
                fd, dst_name = tempfile.mkstemp(suffix=src.suffix)
                os.close(fd)
                dst = Path(dst_name)
                shutil.copy2(src, dst)
                result.append(dst)

            metadata = cls.source_metadata(info, images[0])
            return result, metadata

    @staticmethod
    def extract_playlist_entries(url: str) -> list[dict[str, str]]:
        """استخراج جميع روابط الفيديوهات داخل قائمة تشغيل يوتيوب."""
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "socket_timeout": 20,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                return []
            entries = info.get("entries") or []
            result = []
            for e in entries:
                if not e:
                    continue
                vid_id = e.get("id")
                entry_url = e.get("url") or e.get("webpage_url")
                if not entry_url and vid_id:
                    entry_url = f"https://www.youtube.com/watch?v={vid_id}"
                if entry_url:
                    result.append(
                        {"url": entry_url, "title": str(e.get("title") or vid_id or "")}
                    )
            return result


# ═══════════════════════════════════════════════════════════════════════
# 🧠 إدارة الجلسات والحالات المؤقتة للمستخدمين والأدمن
# ═══════════════════════════════════════════════════════════════════════

# تخزين بيانات الفيديوهات والصوتيات المحملة لربطها بالأزرار
media_sessions: dict[str, dict[str, Any]] = {}

# حالات المستخدمين (إعادة تسمية، غلاف، وصف، مراسلة الأدمن)
rename_pending: dict[tuple[int, int], str] = {}
cover_pending: dict[tuple[int, int], str] = {}
desc_pending: dict[tuple[int, int], str] = {}
user_support_pending: set[int] = set()

# حالات الأدمن (إذاعة، مراسلة مستخدم، الرد على تذكرة، تعديل الترحيب، بحث عن مستخدم، رفع كوكيز)
admin_broadcast_pending: set[int] = set()
admin_send_msg_pending: dict[int, int] = {}
admin_reply_ticket_pending: dict[int, int] = {}
admin_welcome_edit_pending: set[int] = set()
admin_search_user_pending: set[int] = set()
admin_cookie_selected_platform: dict[int, str] = {}


def _prune_store(store: dict[Any, Any], limit: int = 1000) -> None:
    """تنظيف الذاكرة المؤقتة عند تجاوز الحد الأقصى."""
    if len(store) > limit:
        del store[next(iter(store))]


def clear_user_pending_states(chat_id: int, user_id: int) -> None:
    """إلغاء أي حالة معلقة للمستخدم عند الرجوع للرئيسية."""
    key = (chat_id, user_id)
    rename_pending.pop(key, None)
    cover_pending.pop(key, None)
    desc_pending.pop(key, None)
    user_support_pending.discard(user_id)
    if user_id == OWNER_ID:
        admin_broadcast_pending.discard(user_id)
        admin_send_msg_pending.pop(user_id, None)
        admin_reply_ticket_pending.pop(user_id, None)
        admin_welcome_edit_pending.discard(user_id)
        admin_search_user_pending.discard(user_id)
        admin_cookie_selected_platform.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════════════
# 📤 إرسال الوسائط المحملة للمستخدم (فيديو / صوت / ألبوم / قائمة تشغيل)
# ═══════════════════════════════════════════════════════════════════════


async def send_downloaded_media(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    mode: str = "video",
    custom_filename: str | None = None,
    custom_thumbnail: Path | None = None,
    custom_caption: str | None = None,
    custom_performer: str | None = None,
    show_loading: bool = True,
) -> None:
    """الدالة الرئيسية لتحميل وإرسال الفيديو أو الصوت للمستخدم مع معالجة كافة الأخطاء."""
    if message is None:
        return

    loading_msg = None
    if show_loading:
        try:
            loading_msg = await message.reply_text(
                "⏳ <b>جاري التحميل والمعالجة بأعلى جودة...</b>\n"
                "<i>يرجى الانتظار قليلاً، يعتمد الوقت على حجم الفيديو</i> 🚀",
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.message_id,
            )
        except Exception:
            pass

    async def delete_loading() -> None:
        if loading_msg:
            try:
                await loading_msg.delete()
            except Exception:
                pass

    downloaded_path: Path | None = None
    cover_path: Path | None = None

    try:
        # 1. فحص ما إذا كان الرابط ألبوم صور تيك توك
        if mode == "video" and platform_name(url).lower() == "tiktok":
            async with download_slots:
                await context.bot.send_chat_action(
                    chat_id=message.chat_id, action=ChatAction.UPLOAD_PHOTO
                )
                photo_paths, photo_meta = await asyncio.wait_for(
                    asyncio.to_thread(MediaDownloader.download_tiktok_photos, url),
                    timeout=DOWNLOAD_TIMEOUT_SECONDS,
                )
            if photo_paths:
                file_handles: list[Any] = []
                try:
                    title = (photo_meta.get("title") or "ألبوم صور تيك توك").strip()
                    media_group = []
                    for i, p in enumerate(photo_paths):
                        fh = open(p, "rb")
                        file_handles.append(fh)
                        media_group.append(
                            InputMediaPhoto(
                                media=fh,
                                caption=f"📸 <b>{html.escape(title)}</b>" if i == 0 else None,
                                parse_mode=ParseMode.HTML if i == 0 else None,
                            )
                        )
                    await context.bot.send_media_group(
                        chat_id=message.chat_id,
                        media=media_group,
                        reply_to_message_id=message.message_id,
                    )
                    await delete_loading()
                    if message.from_user:
                        await db.increment_download(message.from_user.id)
                    return
                finally:
                    for fh in file_handles:
                        try:
                            fh.close()
                        except Exception:
                            pass
                    for p in photo_paths:
                        p.unlink(missing_ok=True)

        # 2. تحميل الفيديو أو الصوت عبر yt-dlp
        async with download_slots:
            action = (
                ChatAction.UPLOAD_VOICE if mode == "audio" else ChatAction.UPLOAD_VIDEO
            )
            await context.bot.send_chat_action(chat_id=message.chat_id, action=action)
            downloaded_path, metadata, cover_path = await asyncio.wait_for(
                asyncio.to_thread(MediaDownloader.download_media, url, mode),
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )

        # حفظ الجلسة لربطها بالأزرار التفاعلية
        session_key = secrets.token_urlsafe(8)
        media_sessions[session_key] = {
            "url": url,
            "metadata": metadata,
        }
        _prune_store(media_sessions)

        caption_html = MediaDownloader.build_caption(metadata, custom_caption)
        thumb_to_use = custom_thumbnail if custom_thumbnail is not None else cover_path

        # 3. الإرسال حسب النوع (صوت أو فيديو)
        if mode == "audio":
            markup = audio_actions_keyboard(session_key)
            audio_fname = custom_filename or clean_filename(metadata["title"])
            performer = (custom_performer or metadata["uploader"])[:64]
            title = metadata["title"][:64]
            duration_sec = int(metadata.get("duration_seconds") or 0)

            with open(downloaded_path, "rb") as audio_file:
                thumb_fh = (
                    open(thumb_to_use, "rb")
                    if thumb_to_use and thumb_to_use.is_file()
                    else None
                )
                try:
                    await context.bot.send_audio(
                        chat_id=message.chat_id,
                        audio=audio_file,
                        caption=caption_html,
                        parse_mode=ParseMode.HTML,
                        title=title,
                        performer=performer,
                        duration=duration_sec,
                        filename=audio_fname,
                        thumbnail=thumb_fh,
                        reply_markup=markup,
                        reply_to_message_id=message.message_id,
                        read_timeout=300,
                        write_timeout=300,
                    )
                finally:
                    if thumb_fh:
                        thumb_fh.close()
        else:
            markup = video_actions_keyboard(session_key)
            duration_sec = int(metadata.get("duration_seconds") or 0)
            file_size = downloaded_path.stat().st_size

            sent_via_pyro = None
            # إذا كان حجم الملف أكبر من 49 ميجابايت وكان Pyrogram مفعلاً، نرفعه عبر Pyrogram
            if file_size > 49 * 1024 * 1024 and pyro_client is not None:
                sent_via_pyro = await upload_large_media_pyrogram(
                    chat_id=message.chat_id,
                    media_path=downloaded_path,
                    media_type="video",
                    caption=caption_html,
                    reply_to_message_id=message.message_id,
                    reply_markup=markup,
                    duration=duration_sec,
                    thumb=thumb_to_use,
                )

            if not sent_via_pyro:
                with open(downloaded_path, "rb") as video_file:
                    thumb_fh = (
                        open(thumb_to_use, "rb")
                        if thumb_to_use and thumb_to_use.is_file()
                        else None
                    )
                    try:
                        await context.bot.send_video(
                            chat_id=message.chat_id,
                            video=video_file,
                            caption=caption_html,
                            parse_mode=ParseMode.HTML,
                            duration=duration_sec,
                            thumbnail=thumb_fh,
                            supports_streaming=True,
                            reply_markup=markup,
                            reply_to_message_id=message.message_id,
                            read_timeout=300,
                            write_timeout=300,
                        )
                    finally:
                        if thumb_fh:
                            thumb_fh.close()

        await delete_loading()
        if message.from_user:
            await db.increment_download(message.from_user.id)

    except asyncio.TimeoutError:
        await delete_loading()
        await message.reply_text(
            "⚠️ <b>انتهت مهلة التحميل!</b>\n"
            "حجم الفيديو كبير جداً أو الاتصال بالمصدر بطيء حالياً، يرجى المحاولة لاحقاً.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
    except Exception as error:
        logger.exception("Error downloading URL %s: %s", url, error)
        await delete_loading()
        await message.reply_text(
            "❌ <b>عذراً، تعذّر تحميل هذا الرابط!</b>\n\n"
            "• تأكد من أن الرابط عام وليس خاصاً (Private).\n"
            "• تأكد من صحة الرابط وأن الفيديو لم يُحذف من المنصة.\n"
            "• إذا كانت المشكلة مستمرة، يمكنك مراسلة الإدارة من القائمة الرئيسية.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
    finally:
        if downloaded_path is not None:
            downloaded_path.unlink(missing_ok=True)
        if cover_path is not None:
            cover_path.unlink(missing_ok=True)


async def send_playlist(
    message: Any, context: ContextTypes.DEFAULT_TYPE, url: str
) -> None:
    """تحميل قائمة تشغيل يوتيوب كاملة بشكل متوازي مع عرض التقدم."""
    wait_msg = await message.reply_text(
        "⏳ <b>جاري فحص قائمة التشغيل (Playlist)...</b>\n<i>يرجى الانتظار قليلاً</i>",
        parse_mode=ParseMode.HTML,
    )
    try:
        entries = await asyncio.wait_for(
            asyncio.to_thread(MediaDownloader.extract_playlist_entries, url),
            timeout=60,
        )
    except Exception as err:
        logger.warning("Playlist extraction failed: %s", err)
        await wait_msg.edit_text(
            "❌ <b>تعذّر جلب قائمة التشغيل!</b>\nتأكد من أن القائمة عامة وليست خاصة.",
            parse_mode=ParseMode.HTML,
        )
        return

    total = len(entries)
    if total == 0:
        await wait_msg.edit_text(
            "⚠️ <b>لم يتم العثور على فيديوهات داخل قائمة التشغيل هذه.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    done_count = 0
    fail_count = 0
    counter_lock = asyncio.Lock()

    await wait_msg.edit_text(
        f"📋 <b>تم العثور على {total} فيديو في القائمة!</b>\n"
        f"⏳ جاري التحميل: <b>0 / {total}</b>",
        parse_mode=ParseMode.HTML,
    )

    playlist_sem = asyncio.Semaphore(PLAYLIST_WORKERS)

    async def _update_progress() -> None:
        try:
            await wait_msg.edit_text(
                f"📋 <b>تحميل قائمة التشغيل:</b>\n"
                f"✅ مكتمل: <b>{done_count} / {total}</b>"
                + (f"  |  ❌ فشل: <b>{fail_count}</b>" if fail_count else ""),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    async def _download_one(idx: int, entry: dict[str, str]) -> None:
        nonlocal done_count, fail_count
        async with playlist_sem:
            try:
                await send_downloaded_media(
                    message, context, entry["url"], show_loading=False
                )
                async with counter_lock:
                    done_count += 1
            except Exception as err:
                logger.warning("Playlist item %d failed: %s", idx, err)
                async with counter_lock:
                    done_count += 1
                    fail_count += 1
            await _update_progress()

    tasks = [
        asyncio.create_task(_download_one(idx, entry))
        for idx, entry in enumerate(entries, start=1)
    ]
    await asyncio.gather(*tasks)

    try:
        await wait_msg.delete()
    except Exception:
        pass

    await message.reply_text(
        f"✅ <b>اكتمل تحميل قائمة التشغيل بنجاح!</b>\n"
        f"📥 تم تنزيل: <b>{total - fail_count}</b> فيديو"
        + (f"\n❌ تعذر تنزيل: <b>{fail_count}</b>" if fail_count else ""),
        parse_mode=ParseMode.HTML,
        reply_markup=back_and_home_keyboard("menu_home"),
    )


# ═══════════════════════════════════════════════════════════════════════
# 💬 أوامر البوت والقوائم التفاعلية للمستخدمين
# ═══════════════════════════════════════════════════════════════════════


async def build_welcome_text(user: Any) -> str:
    """تجهيز نص رسالة الترحيب مع إدراج اسم المستخدم تلقائياً."""
    user_name = (user.first_name if user and user.first_name else "صديقي").strip()
    raw_template = await db.get_setting("welcome_message", DEFAULT_WELCOME_MESSAGE)
    # استبدال {name} باسم المستخدم بأمان
    return raw_template.replace("{name}", user_name)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أمر /start وعرض رسالة الترحيب الفريدة."""
    user = update.effective_user
    if user is None:
        return

    if update.effective_chat:
        clear_user_pending_states(update.effective_chat.id, user.id)

    # فحص الاشتراك الإجباري
    if not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    welcome_text = await build_welcome_text(user)
    is_admin = user.id == OWNER_ID
    markup = main_menu_keyboard(is_admin=is_admin)

    if update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.message.edit_text(
                welcome_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
            )
            return
        except Exception:
            try:
                await update.callback_query.message.edit_text(
                    welcome_text,
                    reply_markup=markup,
                )
                return
            except Exception:
                pass

    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                welcome_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
            )
        except Exception:
            # في حال عدّل الأدمن رسالة الترحيب برموز Markdown غير مغلقة، نرسلها كنص عادي حتى لا يتوقف البوت
            await update.effective_message.reply_text(
                welcome_text,
                reply_markup=markup,
            )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أمر /help لشرح استخدام البوت والأوامر المتاحة."""
    user = update.effective_user
    if user and not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    help_text = (
        "ℹ️ <b>دليل استخدام البوت والأوامر المتاحة:</b>\n\n"
        "1️⃣ <b>تحميل الفيديو:</b>\n"
        "أرسل رابط الفيديو مباشرة في المحادثة من أي منصة وسيقوم البوت بتحميله بأعلى جودة.\n\n"
        "2️⃣ <b>تحميل الصوت (MP3):</b>\n"
        "اضغط على زر <code>🎵 تحميل الملف الصوتي</code> أسفل أي فيديو، أو استخدم الأمر:\n"
        "<code>/audio https://...</code>\n\n"
        "3️⃣ <b>تخصيص الملف الصوتي:</b>\n"
        "بعد تحميل الصوت، يمكنك الضغط على الأزرار لتغيير اسمه، أو وضع صورة غلاف خاصة، أو تعديل الوصف.\n\n"
        "📌 <b>الأوامر السريعة:</b>\n"
        "• /start — فتح القائمة الرئيسية\n"
        "• /help — عرض تعليمات المساعدة\n"
        "• /audio — تحميل رابط كملف صوتي مباشرة\n"
        "• /admin — لوحة التحكم (للأدمن فقط)"
    )
    markup = back_and_home_keyboard("menu_home")

    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.edit_text(
            help_text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            help_text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أمر /audio لتحميل الصوت مباشرة من الرابط."""
    user = update.effective_user
    if user and not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    text = " ".join(context.args or [])
    url = extract_media_url(text)
    if not url:
        if update.effective_message:
            await update.effective_message.reply_text(
                "🎵 <b>الاستخدام الصحيح للأمر:</b>\n"
                "<code>/audio https://...</code>\n\n"
                "أو أرسل الرابط مباشرة في المحادثة ثم اختر تحميل الصوت!",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("menu_home"),
            )
        return
    await send_downloaded_media(update.effective_message, context, url, mode="audio")


# ═══════════════════════════════════════════════════════════════════════
# 🔘 معالجات أزرار القوائم للمستخدمين (Callbacks)
# ═══════════════════════════════════════════════════════════════════════


async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """التحقق الفوري عند ضغط المستخدم على زر (✅ تحقق من الاشتراك)."""
    query = update.callback_query
    if query is None or query.from_user is None:
        return

    is_subbed = await check_user_subscription(query.from_user.id, context)
    if is_subbed:
        await query.answer("🎉 شكراً لاشتراكك! تم تفعيل البوت بنجاح.", show_alert=True)
        await start_command(update, context)
    else:
        await query.answer(
            "⚠️ لم تشترك في القناة بعد! اشترك أولاً في @Ell_Hoot ثم اضغط تحقق.",
            show_alert=True,
        )


async def user_menu_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أزرار القائمة الرئيسية للمستخدم (ابدأ الآن، حسابي، المنصات، تواصل مع الإدارة)."""
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return

    user = query.from_user
    data = query.data or ""

    # فحص الاشتراك الإجباري
    if not await check_user_subscription(user.id, context):
        await query.answer("⚠️ يرجى الاشتراك في القناة أولاً!", show_alert=True)
        await send_force_sub_prompt(update)
        return

    await query.answer()

    if data == "menu_home":
        clear_user_pending_states(query.message.chat_id, user.id)
        await start_command(update, context)
        return

    if data == "menu_start_now":
        text = (
            "🚀 <b>أهلاً بك! البوت جاهز لاستقبال الروابط الآن</b>\n\n"
            "📥 <b>كيف تبدأ؟</b>\n"
            "فقط انسخ رابط أي فيديو أو ريلز أو شورتس أو ألبوم صور من أي تطبيق وأرسله هنا مباشرة في المحادثة!\n\n"
            "✨ <b>مميزات حصرية لك:</b>\n"
            "• 🎬 تحميل الفيديو بأعلى دقة متاحة وبدون علامة مائية.\n"
            "• 🎵 تحويل أي فيديو إلى ملف صوتي MP3 نقي بضغطة زر.\n"
            "• ✏️ تغيير اسم الملف الصوتي، صورته، ووصفه من داخل البوت.\n\n"
            "👇 <i>أرسل الرابط الآن وسأتولى الباقي فوراً!</i>"
        )
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return

    if data == "menu_account":
        user_info = await db.get_user(user.id)
        dl_count = user_info["downloads"] if user_info else 0
        joined = user_info["joined"] if user_info else "اليوم"
        uname = f"@{user.username}" if user.username else "لا يوجد"
        text = (
            f"👤 <b>الملف الشخصي وإحصائياتك:</b>\n\n"
            f"🏷️ <b>الاسم:</b> {html.escape(user.full_name)}\n"
            f"🆔 <b>المعرف (ID):</b> <code>{user.id}</code>\n"
            f"🔗 <b>اليوزر:</b> {html.escape(uname)}\n"
            f"📅 <b>تاريخ الانضمام:</b> <code>{joined}</code>\n"
            f"📥 <b>إجمالي تحميلاتك الناجحة:</b> <b>{dl_count}</b> ملف\n"
            f"✅ <b>حالة الحساب:</b> نشط ومشترك"
        )
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return

    if data == "menu_platforms":
        text = (
            "🌐 <b>المنصات المدعومة في البوت:</b>\n\n"
            "• 🔴 <b>YouTube</b> (فيديوهات، Shorts، قوائم تشغيل Playlists)\n"
            "• ⚫ <b>TikTok</b> (فيديوهات بدون علامة مائية + ألبومات الصور)\n"
            "• 🟣 <b>Instagram</b> (Reels، منشورات، IGTV)\n"
            "• 🔵 <b>Facebook</b> (فيديوهات عامة، Reels، Watch)\n"
            "• ⚫ <b>X / Twitter</b> (فيديوهات ومقاطع GIF)\n"
            "• 🔴 <b>Pinterest</b> (فيديوهات ومقاطع Pins)\n"
            "• 🟡 <b>Snapchat</b> (مقاطع Spotlight والقصص العامة)\n"
            "• ⚫ <b>Threads</b> & 🟠 <b>Reddit</b> & 🟠 <b>Likee</b>\n"
            "• 🌍 <b>أكثر من 1000 موقع ومنصة أخرى مدعومة تلقائياً!</b>"
        )
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return

    if data == "menu_help":
        await help_command(update, context)
        return

    if data == "menu_contact_admin":
        user_support_pending.add(user.id)
        text = (
            "📩 <b>التواصل المباشر مع إدارة البوت:</b>\n\n"
            "اكتب رسالتك، اقتراحك، أو المشكلة التي تواجهك وأرسلها الآن في المحادثة، "
            "وسيقوم الأدمن بالرد عليك هنا مباشرة في أقرب وقت."
        )
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return


# ═══════════════════════════════════════════════════════════════════════
# 🎵 معالجات أزرار الوسائط (تحويل لصوت، تفاصيل، تسمية، غلاف، وصف)
# ═══════════════════════════════════════════════════════════════════════


async def media_action_callbacks(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """معالجة الأزرار التفاعلية المرفقة مع الفيديوهات والملفات الصوتية."""
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return

    user = query.from_user
    if not await check_user_subscription(user.id, context):
        await query.answer("⚠️ يرجى الاشتراك في القناة أولاً!", show_alert=True)
        await send_force_sub_prompt(update)
        return

    data = query.data or ""
    action, _, session_key = data.partition(":")
    session = media_sessions.get(session_key)

    if not session:
        await query.answer(
            "⚠️ انتهت صلاحية هذا الزر، يرجى إرسال الرابط مرة أخرى.", show_alert=True
        )
        return

    if action == "audio":
        await query.answer("🎵 جاري استخراج وتجهيز الملف الصوتي...")
        await send_downloaded_media(
            query.message, context, session["url"], mode="audio"
        )
        return

    if action == "vinfo":
        await query.answer()
        details_text = MediaDownloader.build_technical_details_text(
            session.get("metadata", {})
        )
        await query.message.reply_text(
            details_text,
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
            reply_to_message_id=query.message.message_id,
        )
        return

    pending_key = (query.message.chat_id, user.id)

    if action == "rename":
        await query.answer()
        rename_pending[pending_key] = session["url"]
        _prune_store(rename_pending)
        await query.message.reply_text(
            "✏️ <b>إعادة تسمية الملف الصوتي:</b>\n"
            "أرسل الاسم الجديد الآن (بالعربية أو الإنجليزية)، وسأقوم بإضافة <code>.mp3</code> تلقائياً.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return

    if action == "cover":
        await query.answer()
        cover_pending[pending_key] = session_key
        _prune_store(cover_pending)
        await query.message.reply_text(
            "🖼️ <b>تغيير غلاف الملف الصوتي:</b>\n"
            "أرسل الصورة التي تريد تعيينها كغلاف للملف الصوتي الآن.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return

    if action == "desc":
        await query.answer()
        desc_pending[pending_key] = session_key
        _prune_store(desc_pending)
        await query.message.reply_text(
            "📝 <b>إضافة وصف / اسم المؤدي للملف الصوتي:</b>\n"
            "أرسل الوصف أو اسم المؤدي الذي تريد إضافته للملف الصوتي الآن.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return


# ═══════════════════════════════════════════════════════════════════════
# 🔐 لوحة تحكم الأدمن المتكاملة (Admin Panel)
# ═══════════════════════════════════════════════════════════════════════


def is_user_admin(user_id: int | None) -> bool:
    """التحقق الصارم من صلاحية الأدمن."""
    return user_id is not None and user_id == OWNER_ID


async def build_admin_dashboard_text() -> tuple[str, int]:
    """تجهيز نص لوحة التحكم الرئيسية مع الإحصائيات السريعة."""
    stats = await db.get_stats_summary()
    force_sub = await db.get_setting("force_sub_enabled", "1")
    sub_status = "🟢 مفعل" if force_sub == "1" else "🔴 معطل"

    text = (
        "🔐 <b>لوحة تحكم الإدارة الشاملة</b>\n\n"
        f"👥 <b>إجمالي المستخدمين:</b> <code>{stats['total_users']}</code>\n"
        f"✅ <b>المستخدمون النشطون:</b> <code>{stats['active_users']}</code>\n"
        f"🚫 <b>المحظورون / الموقوفون:</b> <code>{stats['banned_users']} / {stats['stopped_users']}</code>\n"
        f"📥 <b>إجمالي التحميلات الكلية:</b> <code>{stats['total_downloads']}</code>\n"
        f"📅 <b>رسائل اليوم:</b> <code>{stats['today_messages']}</code>  |  <b>تحميلات اليوم:</b> <code>{stats['today_downloads']}</code>\n"
        f"📩 <b>رسائل دعم بانتظار الرد:</b> <code>{stats['unreplied_msgs']}</code>\n"
        f"📢 <b>الاشتراك الإجباري ({FORCE_SUB_CHANNEL_USERNAME}):</b> {sub_status}\n\n"
        "👇 <i>اختر القسم الذي تريد إدارته من الأزرار التالية:</i>"
    )
    return text, stats["unreplied_msgs"]


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أمر /admin و /M لفتح لوحة التحكم (للأدمن فقط)."""
    user = update.effective_user
    if not user or not is_user_admin(user.id):
        if update.effective_message:
            await update.effective_message.reply_text(
                "⛔ <b>عذراً، هذا القسم مخصص لإدارة البوت فقط.</b>",
                parse_mode=ParseMode.HTML,
            )
        return

    if update.effective_chat:
        clear_user_pending_states(update.effective_chat.id, user.id)

    text, unreplied = await build_admin_dashboard_text()
    markup = admin_main_keyboard(unreplied)

    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def show_admin_user_profile(query: Any, uid: int) -> None:
    """عرض صفحة إدارة مستخدم محدد داخل لوحة الأدمن."""
    user = await db.get_user(uid)
    if not user:
        await query.message.edit_text(
            "⚠️ <b>لم يتم العثور على هذا المستخدم في قاعدة البيانات.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_main"),
        )
        return

    full = f"{user['first']} {user['last']}".strip() or "بدون اسم"
    uname = f"@{user['username']}" if user["username"] else "لا يوجد"
    if user["banned"]:
        status = "🚫 محظور"
    elif user["stopped"]:
        status = "🔇 موقوف سرياً"
    else:
        status = "🟢 نشط"

    text = (
        f"👤 <b>إدارة المستخدم: {html.escape(full)}</b>\n\n"
        f"🆔 <b>المعرف (ID):</b> <code>{uid}</code>\n"
        f"🔗 <b>اليوزر:</b> {html.escape(uname)}\n"
        f"📅 <b>تاريخ الانضمام:</b> <code>{user['joined'] or '—'}</code>\n"
        f"📥 <b>عدد التحميلات:</b> <b>{user['downloads']}</b>\n"
        f"📌 <b>الحالة الحالية:</b> <b>{status}</b>"
    )

    ban_btn = (
        InlineKeyboardButton("🟢 فك الحظر", callback_data=f"adm_unban_{uid}")
        if user["banned"]
        else InlineKeyboardButton("🔴 حظر المستخدم", callback_data=f"adm_ban_{uid}")
    )
    stop_btn = (
        InlineKeyboardButton("🔊 إلغاء الإيقاف السري", callback_data=f"adm_resume_{uid}")
        if user["stopped"]
        else InlineKeyboardButton("🔇 إيقاف سري", callback_data=f"adm_stop_{uid}")
    )

    markup = InlineKeyboardMarkup(
        [
            [ban_btn, stop_btn],
            [
                InlineKeyboardButton(
                    "✉️ إرسال رسالة خاصة للمستخدم", callback_data=f"adm_msg_{uid}"
                )
            ],
            [
                InlineKeyboardButton("⬅️ رجوع للمستخدمين", callback_data="adm_users_0"),
                InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
            ],
        ]
    )
    await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة جميع أزرار لوحة تحكم الأدمن مع حماية كاملة."""
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return

    user = query.from_user
    if not is_user_admin(user.id):
        await query.answer("⛔ غير مصرح لك بالدخول إلى لوحة الأدمن!", show_alert=True)
        return

    data = query.data or ""

    if data == "adm_noop":
        await query.answer()
        return

    if data in ("adm_main", "adm_back"):
        await query.answer()
        clear_user_pending_states(query.message.chat_id, user.id)
        text, unreplied = await build_admin_dashboard_text()
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=admin_main_keyboard(unreplied)
        )
        return

    # ── 1. الإحصائيات التفصيلية ──
    if data == "adm_stats":
        await query.answer("📊 تم تحديث الإحصائيات")
        stats = await db.get_stats_summary()
        cookies_rows = await db.get_all_cookies()
        text = (
            "📊 <b>تقرير إحصائيات البوت التفصيلي:</b>\n\n"
            f"👥 <b>إجمالي المسجلين:</b> <code>{stats['total_users']}</code> مستخدم\n"
            f"🟢 <b>المستخدمون النشطون:</b> <code>{stats['active_users']}</code> مستخدم\n"
            f"🔴 <b>المستخدمون المحظورون:</b> <code>{stats['banned_users']}</code> مستخدم\n"
            f"🔇 <b>المستخدمون الموقوفون سرياً:</b> <code>{stats['stopped_users']}</code> مستخدم\n\n"
            f"📈 <b>النشاط اليومي ({datetime.now().strftime('%Y-%m-%d')}):</b>\n"
            f"• 💬 الرسائل اليومية المستقبلة: <code>{stats['today_messages']}</code> رسالة\n"
            f"• 📥 عمليات التحميل اليوم: <code>{stats['today_downloads']}</code> عملية\n\n"
            f"🏆 <b>الإحصائيات الكلية:</b>\n"
            f"• 📥 إجمالي التحميلات الناجحة: <code>{stats['total_downloads']}</code> ملف\n"
            f"• 📩 رسائل المستخدمين غير المقروءة: <code>{stats['unreplied_msgs']}</code> رسالة\n"
            f"• 🍪 منصات مضاف لها كوكيز: <code>{len(cookies_rows)}</code> منصة"
        )
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 تحديث الأرقام", callback_data="adm_stats")],
                [
                    InlineKeyboardButton("⬅️ رجوع", callback_data="adm_main"),
                    InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
                ],
            ]
        )
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
        return

    # ── 2. قائمة المستخدمين (مقسمة لصفحات) ──
    if data.startswith("adm_users_"):
        await query.answer()
        page = int(data.split("_")[-1])
        users = await db.get_all_users()
        total = len(users)

        if total == 0:
            await query.message.edit_text(
                "👥 <b>لا يوجد مستخدمون مسجلون بعد.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_main"),
            )
            return

        start_idx = page * USERS_PER_PAGE
        page_users = users[start_idx : start_idx + USERS_PER_PAGE]
        total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)

        buttons: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []
        for u in page_users:
            name = (u["first"] or str(u["id"]))[:14]
            status_icon = "🔴" if u["banned"] else ("🔇" if u["stopped"] else "🟢")
            row.append(
                InlineKeyboardButton(
                    f"{status_icon} {name}", callback_data=f"adm_user_{u['id']}"
                )
            )
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton("⬅️ السابق", callback_data=f"adm_users_{page - 1}")
            )
        nav.append(
            InlineKeyboardButton(
                f"📄 {page + 1} / {total_pages}", callback_data="adm_noop"
            )
        )
        if start_idx + USERS_PER_PAGE < total:
            nav.append(
                InlineKeyboardButton("التالي ➡️", callback_data=f"adm_users_{page + 1}")
            )
        buttons.append(nav)
        buttons.append(
            [
                InlineKeyboardButton("🔍 بحث/حظر بالـ ID", callback_data="adm_search_user"),
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton("⬅️ رجوع", callback_data="adm_main"),
                InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
            ]
        )

        await query.message.edit_text(
            f"👥 <b>إدارة المستخدمين ({total} مستخدم) — صفحة {page + 1} من {total_pages}:</b>\n"
            "<i>اضغط على أي مستخدم لعرض ملفه، حظره، فك حظره، أو مراسلته:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # ── 3. البحث عن مستخدم بالـ ID لحظره أو إدارته ──
    if data == "adm_search_user":
        await query.answer()
        admin_search_user_pending.add(OWNER_ID)
        await query.message.edit_text(
            "🔍 <b>البحث عن مستخدم أو حظره بالـ ID:</b>\n\n"
            "أرسل الآن <b>الـ ID الخاص بالمستخدم</b> (أرقام فقط) لفتح ملفه والتحكم بحظره أو مراسلته:",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_main"),
        )
        return

    # ── 4. تفاصيل مستخدم وإجراءات الحظر/الإيقاف/المراسلة ──
    if data.startswith("adm_user_"):
        await query.answer()
        uid = int(data.split("_")[-1])
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_ban_"):
        uid = int(data.split("_")[-1])
        await db.set_ban(uid, True)
        await query.answer("🔴 تم حظر المستخدم بنجاح")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_unban_"):
        uid = int(data.split("_")[-1])
        await db.set_ban(uid, False)
        await query.answer("🟢 تم فك الحظر عن المستخدم")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_stop_"):
        uid = int(data.split("_")[-1])
        await db.set_stop(uid, True)
        await query.answer("🔇 تم الإيقاف السري للمستخدم")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_resume_"):
        uid = int(data.split("_")[-1])
        await db.set_stop(uid, False)
        await query.answer("🔊 تم استئناف حساب المستخدم")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_msg_"):
        uid = int(data.split("_")[-1])
        admin_send_msg_pending[OWNER_ID] = uid
        await query.answer()
        await query.message.edit_text(
            f"✉️ <b>إرسال رسالة خاصة للمستخدم <code>{uid}</code>:</b>\n\n"
            "أرسل الرسالة الآن (نص، صورة، فيديو، ملف صوتي...):",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard(f"adm_user_{uid}"),
        )
        return

    # ── 5. بث رسالة لجميع المستخدمين (Broadcast) ──
    if data == "adm_broadcast":
        await query.answer()
        admin_broadcast_pending.add(OWNER_ID)
        stats = await db.get_stats_summary()
        await query.message.edit_text(
            f"📢 <b>بث رسالة جماعية (Broadcast):</b>\n\n"
            f"سيتم إرسال رسالتك إلى <b>{stats['active_users']}</b> مستخدم نشط.\n\n"
            "أرسل الرسالة الآن (يدعم النص المنسق، الصور، الفيديو، الملفات الصوتية، التحويل...):",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_main"),
        )
        return

    # ── 6. إعدادات البوت (رسالة الترحيب + الاشتراك الإجباري) ──
    if data == "adm_settings":
        await query.answer()
        force_sub = await db.get_setting("force_sub_enabled", "1")
        sub_label = (
            "🔴 تعطيل الاشتراك الإجباري"
            if force_sub == "1"
            else "🟢 تفعيل الاشتراك الإجباري"
        )
        current_welcome = await db.get_setting(
            "welcome_message", DEFAULT_WELCOME_MESSAGE
        )
        text = (
            "⚙️ <b>إعدادات البوت ورسالة الترحيب:</b>\n\n"
            f"📢 <b>قناة الاشتراك الإجباري:</b> <a href='{FORCE_SUB_CHANNEL_URL}'>{FORCE_SUB_CHANNEL_USERNAME}</a>\n"
            f"📌 <b>حالة الاشتراك الإجباري:</b> {'🟢 مفعل' if force_sub == '1' else '🔴 معطل'}\n\n"
            "💬 <b>رسالة الترحيب الحالية:</b>\n"
            f"<blockquote>{html.escape(current_welcome[:500])}</blockquote>\n"
            "<i>ملاحظة: الكلمة <code>{name}</code> يتم استبدالها تلقائياً باسم المستخدم.</i>"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✏️ تعديل رسالة الترحيب", callback_data="adm_edit_welcome"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔄 استعادة الترحيب الافتراضي", callback_data="adm_reset_welcome"
                    )
                ],
                [
                    InlineKeyboardButton(
                        sub_label, callback_data="adm_toggle_forcesub"
                    )
                ],
                [
                    InlineKeyboardButton("⬅️ رجوع", callback_data="adm_main"),
                    InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
                ],
            ]
        )
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        return

    if data == "adm_edit_welcome":
        await query.answer()
        admin_welcome_edit_pending.add(OWNER_ID)
        await query.message.edit_text(
            "✏️ <b>تعديل رسالة الترحيب:</b>\n\n"
            "أرسل الآن نص رسالة الترحيب الجديدة.\n"
            "💡 <i>يمكنك كتابة <code>{name}</code> في أي مكان داخل النص ليقوم البوت بوضع اسم المستخدم مكانه تلقائياً!</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_settings"),
        )
        return

    if data == "adm_reset_welcome":
        await db.set_setting("welcome_message", DEFAULT_WELCOME_MESSAGE)
        await query.answer("✅ تمت استعادة رسالة الترحيب الافتراضية", show_alert=True)
        # إعادة فتح صفحة الإعدادات
        query.data = "adm_settings"
        await admin_callbacks(update, context)
        return

    if data == "adm_toggle_forcesub":
        curr = await db.get_setting("force_sub_enabled", "1")
        new_val = "0" if curr == "1" else "1"
        await db.set_setting("force_sub_enabled", new_val)
        await query.answer(
            "🟢 تم تفعيل الاشتراك الإجباري"
            if new_val == "1"
            else "🔴 تم تعطيل الاشتراك الإجباري"
        )
        query.data = "adm_settings"
        await admin_callbacks(update, context)
        return

    # ── 7. رسائل المستخدمين للأدمن والرد عليها ──
    if data.startswith("adm_msgs_"):
        await query.answer()
        page = int(data.split("_")[-1])
        msgs = await db.get_support_messages(only_unreplied=False)
        total = len(msgs)

        if total == 0:
            await query.message.edit_text(
                "📩 <b>صندوق رسائل المستخدمين فارغ حالياً.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_main"),
            )
            return

        start_idx = page * MESSAGES_PER_PAGE
        page_msgs = msgs[start_idx : start_idx + MESSAGES_PER_PAGE]
        total_pages = max(1, (total + MESSAGES_PER_PAGE - 1) // MESSAGES_PER_PAGE)

        buttons: list[list[InlineKeyboardButton]] = []
        for m in page_msgs:
            icon = "✅" if m["is_replied"] else "🆕"
            sender = (m["user_name"] or str(m["user_id"]))[:15]
            preview = m["text"][:20].replace("\n", " ")
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{icon} {sender}: {preview}...",
                        callback_data=f"adm_viewmsg_{m['id']}",
                    )
                ]
            )

        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton("⬅️ السابق", callback_data=f"adm_msgs_{page - 1}")
            )
        nav.append(
            InlineKeyboardButton(
                f"📄 {page + 1} / {total_pages}", callback_data="adm_noop"
            )
        )
        if start_idx + MESSAGES_PER_PAGE < total:
            nav.append(
                InlineKeyboardButton("التالي ➡️", callback_data=f"adm_msgs_{page + 1}")
            )
        buttons.append(nav)
        buttons.append(
            [
                InlineKeyboardButton("⬅️ رجوع", callback_data="adm_main"),
                InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
            ]
        )

        await query.message.edit_text(
            f"📩 <b>رسائل المستخدمين ({total} رسالة) — صفحة {page + 1} من {total_pages}:</b>\n"
            "<i>🆕 = بانتظار الرد  |  ✅ = تم الرد عليها</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("adm_viewmsg_"):
        await query.answer()
        msg_id = int(data.split("_")[-1])
        m = await db.get_support_message_by_id(msg_id)
        if not m:
            await query.message.edit_text(
                "⚠️ <b>الرسالة غير موجودة.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_msgs_0"),
            )
            return

        uname = f"@{m['username']}" if m["username"] else "لا يوجد"
        status_str = "✅ تم الرد" if m["is_replied"] else "🆕 بانتظار الرد"
        reply_section = (
            f"\n\n↩️ <b>رد الإدارة السابق:</b>\n<blockquote>{html.escape(m['reply_text'])}</blockquote>"
            if m["is_replied"] and m["reply_text"]
            else ""
        )

        text = (
            f"📩 <b>تفاصيل الرسالة #{m['id']}:</b>\n\n"
            f"👤 <b>المرسل:</b> {html.escape(m['user_name'])} (<code>{m['user_id']}</code>)\n"
            f"🔗 <b>اليوزر:</b> {html.escape(uname)}\n"
            f"🕒 <b>التاريخ:</b> <code>{m['created_at']}</code>\n"
            f"📌 <b>الحالة:</b> {status_str}\n\n"
            f"💬 <b>نص الرسالة:</b>\n<blockquote>{html.escape(m['text'])}</blockquote>"
            f"{reply_section}"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "↩️ الرد على هذه الرسالة",
                        callback_data=f"adm_replymsg_{m['id']}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "👤 فتح ملف المستخدم",
                        callback_data=f"adm_user_{m['user_id']}",
                    )
                ],
                [
                    InlineKeyboardButton("⬅️ رجوع للرسائل", callback_data="adm_msgs_0"),
                    InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
                ],
            ]
        )
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
        return

    if data.startswith("adm_replymsg_"):
        await query.answer()
        msg_id = int(data.split("_")[-1])
        m = await db.get_support_message_by_id(msg_id)
        if not m:
            await query.message.reply_text("⚠️ الرسالة غير موجودة.")
            return
        admin_reply_ticket_pending[OWNER_ID] = msg_id
        await query.message.edit_text(
            f"↩️ <b>الرد على رسالة {html.escape(m['user_name'])} (<code>{m['user_id']}</code>):</b>\n\n"
            f"<b>رسالته:</b> <i>{html.escape(m['text'][:200])}</i>\n\n"
            "✍️ أرسل نص الرد الآن وسيصل للمستخدم فوراً:",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard(f"adm_viewmsg_{msg_id}"),
        )
        return

    # ── 8. إدارة الكوكيز (Cookies) ──
    if data == "adm_cookies":
        await query.answer()
        rows = await db.get_all_cookies()
        lines = (
            "\n".join(
                f"• <b>{html.escape(r[0].capitalize())}</b> — <i>آخر تحديث: {r[1]}</i>"
                for r in rows
            )
            or "لا توجد ملفات كوكيز مرفوعة حالياً."
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "➕ إضافة / تحديث كوكيز منصة", callback_data="adm_cookie_add"
                    )
                ],
                [
                    InlineKeyboardButton("⬅️ رجوع", callback_data="adm_main"),
                    InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
                ],
            ]
        )
        await query.message.edit_text(
            f"🍪 <b>إدارة كوكيز المنصات (Cookies):</b>\n\n{lines}",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    if data == "adm_cookie_add":
        await query.answer()
        buttons: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []
        for display_name, platform_key in SUPPORTED_PLATFORMS_BUTTONS:
            row.append(
                InlineKeyboardButton(
                    display_name, callback_data=f"adm_cookie_plat_{platform_key}"
                )
            )
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append(
            [
                InlineKeyboardButton("⬅️ رجوع", callback_data="adm_cookies"),
                InlineKeyboardButton("🏠 الرئيسية", callback_data="menu_home"),
            ]
        )
        await query.message.edit_text(
            "🍪 <b>اختر المنصة التي تريد رفع ملف الكوكيز (TXT) لها:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("adm_cookie_plat_"):
        await query.answer()
        platform_key = data.removeprefix("adm_cookie_plat_")
        admin_cookie_selected_platform[OWNER_ID] = platform_key
        await query.message.edit_text(
            f"🍪 <b>رفع كوكيز لمنصة: {html.escape(platform_key.capitalize())}</b>\n\n"
            "📄 أرسل الآن <b>ملف الكوكيز بصيغة <code>.txt</code></b> (Netscape Cookies Format):",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_cookies"),
        )
        return


async def execute_broadcast(
    source_msg: Any, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """تنفيذ البث الجماعي لجميع المستخدمين النشطين."""
    users = await db.get_all_users()
    targets = [
        u
        for u in users
        if not u["banned"] and not u["stopped"] and u["id"] != OWNER_ID
    ]
    total = len(targets)

    prog = await source_msg.reply_text(
        f"📢 <b>جاري بث الرسالة... (0 / {total})</b>", parse_mode=ParseMode.HTML
    )
    success = 0
    fail = 0

    for i, u in enumerate(targets, 1):
        try:
            await context.bot.copy_message(
                chat_id=u["id"],
                from_chat_id=source_msg.chat_id,
                message_id=source_msg.message_id,
            )
            success += 1
        except (Forbidden, BadRequest):
            fail += 1
        except Exception:
            fail += 1

        if i % 15 == 0 or i == total:
            try:
                await prog.edit_text(
                    f"📢 <b>جاري بث الرسالة...</b>\n"
                    f"✅ نجح: <b>{success}</b>  |  ❌ فشل: <b>{fail}</b>  |  📊 الإجمالي: <b>{i}/{total}</b>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        await asyncio.sleep(0.04)

    await prog.edit_text(
        f"✅ <b>اكتملت عملية البث الجماعي بنجاح!</b>\n\n"
        f"🟢 <b>تم الإرسال لـ:</b> <code>{success}</code> مستخدم\n"
        f"🔴 <b>فشل الإرسال لـ:</b> <code>{fail}</code> مستخدم\n"
        f"📊 <b>المجموع الكلي:</b> <code>{total}</code> مستخدم",
        parse_mode=ParseMode.HTML,
        reply_markup=back_and_home_keyboard("adm_main"),
    )


# ═══════════════════════════════════════════════════════════════════════
# 📥 معالجات الرسائل الواردة (الحارس العام، الصور، ملفات الكوكيز، الروابط)
# ═══════════════════════════════════════════════════════════════════════


async def global_pre_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    الحارس العام (يعمل في المجموعة -1 قبل أي معالج آخر):
    1. يسجل المستخدم الجديد ويحدث الإحصائيات اليومية.
    2. يفحص حالات الأدمن المعلقة (إذاعة، تعديل ترحيب، رد على رسالة، بحث، إلخ).
    3. يمنع المحظورين والموقوفين من استخدام البوت.
    """
    msg = update.effective_message
    if msg is None or msg.from_user is None:
        return

    user = msg.from_user
    user_id = user.id

    # تسجيل/تحديث المستخدم وزيادة عداد الرسائل اليومية
    await db.register_or_update_user(user)
    await db.increment_daily_messages()

    # إذا أرسل المستخدم أمر /start أو /admin نسمح له بالمرور للمعالج المخصص
    if msg.text and msg.text.strip().split()[0].lower() in ("/start", "/admin", "/m", "/help"):
        return

    # ── أولاً: معالجة حالات الأدمن المعلقة ──
    if is_user_admin(user_id):
        # 1. حالة البث الجماعي
        if user_id in admin_broadcast_pending:
            admin_broadcast_pending.discard(user_id)
            await execute_broadcast(msg, context)
            raise ApplicationHandlerStop

        # 2. حالة تعديل رسالة الترحيب
        if user_id in admin_welcome_edit_pending and msg.text:
            admin_welcome_edit_pending.discard(user_id)
            await db.set_setting("welcome_message", msg.text.strip())
            await msg.reply_text(
                "✅ <b>تم حفظ وتحديث رسالة الترحيب بنجاح!</b>\n"
                "جرب إرسال /start لرؤية الشكل الجديد.",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_settings"),
            )
            raise ApplicationHandlerStop

        # 3. حالة البحث عن مستخدم بالـ ID
        if user_id in admin_search_user_pending and msg.text:
            raw_uid = msg.text.strip()
            if not raw_uid.isdigit():
                await msg.reply_text(
                    "⚠️ <b>يرجى إرسال أرقام فقط تمثل الـ ID الخاص بالمستخدم:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard("adm_main"),
                )
                raise ApplicationHandlerStop
            admin_search_user_pending.discard(user_id)
            uid = int(raw_uid)
            u_info = await db.get_user(uid)
            if not u_info:
                await msg.reply_text(
                    f"⚠️ <b>المستخدم صاحب المعرف <code>{uid}</code> غير مسجل في قاعدة البيانات بعد.</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard("adm_main"),
                )
                raise ApplicationHandlerStop
            # إرسال بطاقة التحكم بالمستخدم
            full = f"{u_info['first']} {u_info['last']}".strip() or "بدون اسم"
            ban_btn = (
                InlineKeyboardButton("🟢 فك الحظر", callback_data=f"adm_unban_{uid}")
                if u_info["banned"]
                else InlineKeyboardButton("🔴 حظر المستخدم", callback_data=f"adm_ban_{uid}")
            )
            await msg.reply_text(
                f"👤 <b>المستخدم: {html.escape(full)}</b>\n"
                f"🆔 المعرف: <code>{uid}</code>\n"
                f"📥 التحميلات: <b>{u_info['downloads']}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [ban_btn],
                        [
                            InlineKeyboardButton(
                                "✉️ إرسال رسالة", callback_data=f"adm_msg_{uid}"
                            ),
                            InlineKeyboardButton(
                                "📂 التفاصيل الكاملة", callback_data=f"adm_user_{uid}"
                            ),
                        ],
                        [InlineKeyboardButton("⬅️ رجوع للوحة", callback_data="adm_main")],
                    ]
                ),
            )
            raise ApplicationHandlerStop

        # 4. حالة الرد على تذكرة دعم مستخدم
        if user_id in admin_reply_ticket_pending and msg.text:
            ticket_id = admin_reply_ticket_pending.pop(user_id)
            ticket = await db.get_support_message_by_id(ticket_id)
            if not ticket:
                await msg.reply_text("⚠️ لم يتم العثور على التذكرة.")
                raise ApplicationHandlerStop
            reply_content = msg.text.strip()
            try:
                await context.bot.send_message(
                    chat_id=ticket["user_id"],
                    text=(
                        f"📩 <b>رد جديد من إدارة البوت على رسالتك:</b>\n\n"
                        f"💬 <b>رسالتك السابقة:</b>\n<blockquote>{html.escape(ticket['text'][:200])}</blockquote>\n\n"
                        f"↩️ <b>رد الإدارة:</b>\n<blockquote>{html.escape(reply_content)}</blockquote>"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "📩 إرسال رد آخر للإدارة",
                                    callback_data="menu_contact_admin",
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    "🏠 الرئيسية", callback_data="menu_home"
                                )
                            ],
                        ]
                    ),
                )
                await db.mark_support_replied(ticket_id, reply_content)
                await msg.reply_text(
                    f"✅ <b>تم إرسال ردك بنجاح إلى {html.escape(ticket['user_name'])}!</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard("adm_msgs_0"),
                )
            except Exception as exc:
                await msg.reply_text(
                    f"❌ <b>فشل إرسال الرد للمستخدم (ربما قام بحظر البوت):</b>\n<code>{html.escape(str(exc))}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard("adm_msgs_0"),
                )
            raise ApplicationHandlerStop

        # 5. حالة إرسال رسالة خاصة لمستخدم محدد
        if user_id in admin_send_msg_pending:
            target_id = admin_send_msg_pending.pop(user_id)
            try:
                await context.bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=msg.chat_id,
                    message_id=msg.message_id,
                )
                await msg.reply_text(
                    f"✅ <b>تم إرسال الرسالة بنجاح إلى المستخدم <code>{target_id}</code>!</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard(f"adm_user_{target_id}"),
                )
            except Exception as exc:
                await msg.reply_text(
                    f"❌ <b>تعذّر إرسال الرسالة:</b> <code>{html.escape(str(exc))}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard(f"adm_user_{target_id}"),
                )
            raise ApplicationHandlerStop

        # 6. حالة انتظار ملف كوكيز
        if user_id in admin_cookie_selected_platform and msg.text:
            await msg.reply_text(
                "⚠️ <b>يرجى إرسال ملف بصيغة <code>.txt</code> وليس رسالة نصية!</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_cookies"),
            )
            raise ApplicationHandlerStop

    # ── ثانياً: فحص الحظر والإيقاف للمستخدمين العاديين ──
    if await db.is_banned(user_id):
        await msg.reply_text(
            "⛔ <b>عذراً، تم حظر حسابك من استخدام هذا البوت من قِبل الإدارة.</b>",
            parse_mode=ParseMode.HTML,
        )
        raise ApplicationHandlerStop

    if await db.is_stopped(user_id):
        raise ApplicationHandlerStop


async def cookie_document_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """استقبال وحفظ ملف الكوكيز (.txt) من الأدمن."""
    message = update.effective_message
    if message is None or message.from_user is None:
        return
    user_id = message.from_user.id
    if not is_user_admin(user_id):
        return

    platform = admin_cookie_selected_platform.pop(user_id, None)
    if not platform:
        return

    doc = message.document
    if doc is None or not (doc.file_name or "").lower().endswith(".txt"):
        admin_cookie_selected_platform[user_id] = platform
        await message.reply_text(
            "⚠️ <b>يجب أن يكون الملف بصيغة <code>.txt</code> فقط!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_cookies"),
        )
        return

    fd, tmp_path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        doc_file = await context.bot.get_file(doc.file_id)
        await doc_file.download_to_drive(tmp)
        content = tmp.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            admin_cookie_selected_platform[user_id] = platform
            await message.reply_text(
                "⚠️ <b>الملف فارغ! أرسل ملف كوكيز صالح.</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        saved_path = await db.save_cookie(platform, content)
        await message.reply_text(
            f"✅ <b>تم حفظ وتفعيل كوكيز منصة {html.escape(platform.capitalize())} بنجاح!</b>\n"
            f"📂 المسار: <code>{saved_path}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_cookies"),
        )
    except Exception as exc:
        logger.exception("Failed saving cookie file: %s", exc)
        admin_cookie_selected_platform[user_id] = platform
        await message.reply_text(
            "❌ <b>حدث خطأ أثناء حفظ ملف الكوكيز، حاول مجدداً.</b>",
            parse_mode=ParseMode.HTML,
        )
    finally:
        tmp.unlink(missing_ok=True)


async def photo_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """معالجة الصور المرسلة من المستخدم لتعيينها كغلاف للملف الصوتي."""
    message = update.effective_message
    if message is None or message.from_user is None:
        return

    user = message.from_user
    if not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    pending_key = (message.chat_id, user.id)
    session_key = cover_pending.pop(pending_key, None)
    if not session_key:
        await message.reply_text(
            "🖼️ <b>لتغيير غلاف ملف صوتي:</b>\n"
            "قم بتحميل ملف صوتي أولاً ثم اضغط على زر «🖼️ وضع غلاف للصوت» أسفله!",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        return

    session = media_sessions.get(session_key)
    if not session:
        await message.reply_text(
            "⚠️ <b>انتهت صلاحية الجلسة، يرجى إرسال الرابط من جديد.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    photo = message.photo[-1] if message.photo else None
    if photo is None:
        await message.reply_text("⚠️ لم أتمكن من قراءة الصورة، أرسلها كصورة عادية.")
        return

    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        photo_file = await context.bot.get_file(photo.file_id)
        await photo_file.download_to_drive(tmp)
        await send_downloaded_media(
            message,
            context,
            session["url"],
            mode="audio",
            custom_thumbnail=tmp,
        )
    finally:
        tmp.unlink(missing_ok=True)


async def text_and_url_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """معالجة الرسائل النصية: (مراسلة الأدمن، إعادة تسمية الصوت، تعديل الوصف، أو تحميل رابط)."""
    message = update.effective_message
    if message is None or not message.text or message.from_user is None:
        return

    user = message.from_user

    # 1. التحقق من الاشتراك الإجباري أولاً
    if not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    pending_key = (message.chat_id, user.id)

    # 2. إذا كان المستخدم في وضع إرسال رسالة للأدمن
    if user.id in user_support_pending:
        user_support_pending.discard(user.id)
        ticket_id = await db.add_support_message(
            user_id=user.id,
            user_name=user.full_name or user.first_name or "مستخدم",
            username=user.username or "",
            text=message.text.strip(),
        )
        await message.reply_text(
            "✅ <b>تم إرسال رسالتك إلى إدارة البوت بنجاح!</b>\n"
            "سيقوم الأدمن بمراجعتها والرد عليك هنا في أقرب وقت.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
        # إشعار فوري للأدمن بوصول رسالة جديدة مع زر الرد السريع
        try:
            uname_str = f"@{user.username}" if user.username else "لا يوجد"
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"📩 <b>رسالة جديدة من مستخدم (#{ticket_id}):</b>\n\n"
                    f"👤 <b>الاسم:</b> {html.escape(user.full_name)}\n"
                    f"🆔 <b>المعرف:</b> <code>{user.id}</code>  |  <b>اليوزر:</b> {html.escape(uname_str)}\n\n"
                    f"💬 <b>الرسالة:</b>\n<blockquote>{html.escape(message.text.strip()[:500])}</blockquote>"
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "↩️ الرد على المستخدم الآن",
                                callback_data=f"adm_replymsg_{ticket_id}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "👤 ملف المستخدم",
                                callback_data=f"adm_user_{user.id}",
                            )
                        ],
                    ]
                ),
            )
        except Exception as notify_err:
            logger.debug("Could not notify admin directly: %s", notify_err)
        return

    # 3. إذا كان المستخدم في وضع إعادة تسمية ملف صوتي
    pending_url = rename_pending.pop(pending_key, None)
    if pending_url:
        await send_downloaded_media(
            message,
            context,
            pending_url,
            mode="audio",
            custom_filename=clean_filename(message.text),
        )
        return

    # 4. إذا كان المستخدم في وضع إضافة وصف/مؤدي للملف الصوتي
    desc_token = desc_pending.pop(pending_key, None)
    if desc_token:
        session = media_sessions.get(desc_token)
        if session and session.get("url"):
            await send_downloaded_media(
                message,
                context,
                session["url"],
                mode="audio",
                custom_caption=message.text.strip()[:300],
                custom_performer=message.text.strip()[:64],
            )
        else:
            await message.reply_text(
                "⚠️ <b>انتهت صلاحية الطلب، يرجى إرسال الرابط مجدداً.</b>",
                parse_mode=ParseMode.HTML,
            )
        return

    # 5. استخراج الرابط وتحميله
    url = extract_media_url(message.text)
    if url:
        if is_youtube_playlist(url):
            await send_playlist(message, context, url)
        else:
            await send_downloaded_media(message, context, url)
    else:
        # رسالة ودودة وواضحة إذا أرسل نصاً عادياً ليس رابطاً
        await message.reply_text(
            "🤖 <b>مرحباً بك! أنا بوت تحميل الفيديوهات والصوتيات.</b>\n\n"
            "🔗 يرجى إرسال <b>رابط صحيح يبدأ بـ http أو https</b> من يوتيوب، تيك توك، إنستجرام، فيسبوك، أو أي منصة لتحميله فوراً!\n\n"
            "👇 <i>أو استخدم القائمة بالأسفل للتنقل في البوت:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(is_admin=(user.id == OWNER_ID)),
        )


async def unknown_command_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """رسالة ودودة إذا كتب المستخدم أمراً غير معروف."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ <b>عذراً، هذا الأمر غير معروف!</b>\n\n"
            "الأوامر المتاحة في البوت:\n"
            "• /start — القائمة الرئيسية\n"
            "• /help — تعليمات الاستخدام\n"
            "• /audio — تحميل ملف صوتي\n"
            "• /admin — لوحة تحكم الأدمن",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )


async def global_error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """معالج الأخطاء الشامل لمنع توقف البوت عند أي خطأ شبكي أو برمجي."""
    error = context.error
    if isinstance(error, TelegramTimedOut):
        logger.warning("Telegram TimedOut — temporary network delay.")
        return
    if isinstance(error, TelegramConflict):
        logger.warning("Telegram Conflict — another instance polling.")
        return
    if isinstance(error, NetworkError):
        logger.warning("Telegram NetworkError: %s", error)
        return
    logger.exception("Unhandled exception caught in error_handler:", exc_info=error)


# ═══════════════════════════════════════════════════════════════════════
# 🚀 تشغيل البوت ونظام الإقلاع التلقائي (Auto-Restart System)
# ═══════════════════════════════════════════════════════════════════════


def build_and_run_bot() -> None:
    """بناء تطبيق البوت وربط جميع الأوامر والأزرار وتشغيل الـ Polling."""
    if not TOKEN or TOKEN == "ضع_التوكن_هنا":
        logger.error(
            "❌ خطأ: يرجى وضع توكن البوت الصحيح في المتغير TOKEN أعلى ملف bot.py قبل التشغيل!"
        )
        sys.exit(1)

    request = HTTPXRequest(
        connection_pool_size=32,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=30.0,
    )

    async def _post_init(app: Application) -> None:
        if pyro_client is not None:
            try:
                await pyro_client.start()
                logger.info("Pyrogram client started successfully.")
            except Exception as e:
                logger.warning("Pyrogram client failed to start: %s", e)

    async def _post_shutdown(app: Application) -> None:
        if pyro_client is not None and pyro_client.is_connected:
            try:
                await pyro_client.stop()
            except Exception:
                pass

    application = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(True)
        .request(request)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    # 1. الحارس العام (يعمل أولاً في المجموعة -1)
    application.add_handler(MessageHandler(filters.ALL, global_pre_handler), group=-1)

    # 2. الأوامر الأساسية (/start, /help, /audio, /admin, /M)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("audio", audio_command))
    application.add_handler(CommandHandler(["admin", "M", "m"], admin_command))

    # 3. أزرار الاشتراك الإجباري والقوائم العامة
    application.add_handler(
        CallbackQueryHandler(check_sub_callback, pattern=r"^check_sub$")
    )
    application.add_handler(
        CallbackQueryHandler(user_menu_callbacks, pattern=r"^menu_")
    )

    # 4. أزرار إجراءات الفيديو والصوت
    application.add_handler(
        CallbackQueryHandler(
            media_action_callbacks, pattern=r"^(audio|vinfo|rename|cover|desc):"
        )
    )

    # 5. أزرار لوحة تحكم الأدمن
    application.add_handler(
        CallbackQueryHandler(admin_callbacks, pattern=r"^adm_")
    )

    # 6. معالجات الملفات، الصور، النصوص، والأوامر غير المعروفة
    application.add_handler(
        MessageHandler(filters.Document.FileExtension("txt"), cookie_document_handler)
    )
    application.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_and_url_handler)
    )
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command_handler))

    # 7. معالج الأخطاء العام
    application.add_error_handler(global_error_handler)

    # تنظيف أي Webhook قديم قبل بدء الـ Polling
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=10,
        )
    except Exception:
        pass

    logger.info("✅ البوت يعمل الآن وجاهز لاستقبال الطلبات...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


def main() -> None:
    """حلقة التشغيل التلقائي (Auto-Restart) لضمان استمرار عمل البوت 24/7 عند حدوث أي خطأ طارئ."""
    restart_delay = 5
    while True:
        try:
            build_and_run_bot()
            break
        except KeyboardInterrupt:
            logger.info("🛑 تم إيقاف البوت يدوياً بواسطة المستخدم.")
            break
        except SystemExit:
            break
        except Exception as crash_err:
            logger.error(
                "⚠️ حدث خطأ غير متوقع أدى لتوقف البوت: %s\n%s",
                crash_err,
                traceback.format_exc(),
            )
            logger.info(
                "🔄 سيتم إعادة تشغيل البوت تلقائياً خلال %d ثوانٍ...", restart_delay
            )
            time.sleep(restart_delay)


if __name__ == "__main__":
    main()