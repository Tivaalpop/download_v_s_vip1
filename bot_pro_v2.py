#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
🚀 بوت التحميل الشامل PRO V2 (فيديو + صوت MP3 + صور + أرشيف رقابي + ترشيح AI)
===================================================================================
📦 تثبيت المكتبات (في Termux أو الاستضافة):
    pip install -U python-telegram-bot "yt-dlp[default]" gallery-dl httpx requests
===================================================================================
"""

from __future__ import annotations

import asyncio
import html
import json
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
from urllib.parse import parse_qs, urljoin, urlparse

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
# 📌 الإعدادات الأساسية (ضع التوكن والـ ID هنا أو في متغيرات الاستضافة)
# ═══════════════════════════════════════════════════════════════════════

TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = os.environ.get("ADMIN_ID", "")

# (اختياري) مفتاح Gemini API لتحسين ترشيح الفيديوهات — البوت يعمل بدونه أيضاً بكفاءة كاملة
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# مجلد حفظ قاعدة البيانات والكوكيز (في الاستضافة يمكنك ضبط DATA_DIR=/data لربطه بـ Volume)
DATA_DIR = Path(os.environ.get("DATA_DIR", ".")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# قناة الاشتراك الإجباري
FORCE_SUB_CHANNEL_URL = "https://t.me/Ell_Hoot"
FORCE_SUB_CHANNEL_USERNAME = "@Ell_Hoot"

# تفعيل ألوان تيليجرام الرسمية للأزرار (primary=أزرق | success=أخضر | danger=أحمر)
USE_NATIVE_BUTTON_COLORS = True

# (اختياري) إعدادات Pyrogram لرفع الملفات الأكبر من 50MB حتى 2GB
API_ID = 0
API_HASH = ""

# ═══════════════════════════════════════════════════════════════════════
# 🛠️ تهيئة البيئة، المسارات، وسجل الأحداث (Logging)
# ═══════════════════════════════════════════════════════════════════════

_existing_path = os.environ.get("PATH", "")
for _tool in ("node", "deno", "ffmpeg"):
    _bin = shutil.which(_tool) or ""
    if _bin:
        _dir = os.path.dirname(_bin)
        if _dir not in _existing_path:
            _existing_path = f"{_dir}:{_existing_path}"
os.environ["PATH"] = _existing_path

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram-downloader-pro-v2")
logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_admin_id(raw_id: Any) -> int:
    try:
        cleaned = str(raw_id).strip()
        if cleaned.isdigit():
            return int(cleaned)
    except Exception:
        pass
    return 8220915719


OWNER_ID: int = parse_admin_id(ADMIN_ID)

# الثوابت العامة للبوت
MAX_CONCURRENT_DOWNLOADS = 50
DOWNLOAD_TIMEOUT_SECONDS = 20 * 60
PLAYLIST_WORKERS = 6
USERS_PER_PAGE = 14
MESSAGES_PER_PAGE = 10
ARCHIVE_PER_PAGE = 8
TELEGRAM_BOT_API_MAX_BYTES = 49 * 1024 * 1024
COOKIES_DIR = DATA_DIR / "cookies"
DB_PATH = DATA_DIR / "bot_database.db"

download_slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

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
    "youtube": {"youtube.com", "youtu.be", "youtube-nocookie.com", "music.youtube.com"},
    "tiktok": {"tiktok.com", "vm.tiktok.com", "vt.tiktok.com"},
    "instagram": {"instagram.com", "instagr.am"},
    "twitter": {"twitter.com", "x.com", "vxtwitter.com", "fxtwitter.com"},
    "pinterest": {"pinterest.com", "pin.it", "pinterest.co.uk"},
    "facebook": {"facebook.com", "fb.com", "fb.watch", "m.facebook.com"},
    "snapchat": {"snapchat.com", "t.snapchat.com"},
    "threads": {"threads.net", "threads.com"},
    "likee": {"likee.video", "l.likee.video"},
    "reddit": {"reddit.com", "redd.it"},
}

DEFAULT_WELCOME_MESSAGE = (
    "✨ *أهلاً بك يا {name} في بوت التحميل الشامل PRO!* ✨\n\n"
    "🎬 *أقوى بوت لتحميل الفيديوهات والصور والصوتيات من جميع المنصات والمواقع بأعلى جودة وبدون علامة مائية.*\n\n"
    "📌 *ماذا يمكنك أن تفعل هنا؟*\n"
    "• 🎥 تحميل الفيديوهات من يوتيوب، تيك توك، إنستجرام، فيسبوك، X وغيرها.\n"
    "• 🖼️ تحميل الصور والألبومات من أي منصة أو موقع إلكتروني.\n"
    "• 🎵 استخراج الصوت MP3 مع تعديل الاسم والغلاف والوصف.\n"
    "• 🤖 ترشيح فيديوهات مميزة بالذكاء الاصطناعي وتحميلها بضغطة زر.\n\n"
    "👇 *اضغط على «🚀 ابدأ الآن» أو أرسل الرابط مباشرة في المحادثة:*"
)

# ═══════════════════════════════════════════════════════════════════════
# 🎨 محرك الأزرار الملونة والمنظمة (Colored Keyboards Builder)
# ═══════════════════════════════════════════════════════════════════════

VALID_BTN_STYLES = {"primary", "success", "danger"}


def make_btn(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    """أزرار تيليجرام الملونة المنظمة: primary=أزرق | success=أخضر | danger=أحمر | None=محايد."""
    kwargs: dict[str, Any] = {"text": text}
    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = callback_data or "noop"

    if USE_NATIVE_BUTTON_COLORS and style in VALID_BTN_STYLES:
        kwargs["api_kwargs"] = {"style": style}

    return InlineKeyboardButton(**kwargs)


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [make_btn("🚀 ابدأ الآن (طريقة التحميل)", callback_data="menu_start_now", style="primary")],
        [make_btn("🤖 ترشيح فيديوهات بالذكاء الاصطناعي", callback_data="ai_menu", style="success")],
        [
            make_btn("👤 حسابي وإحصائياتي", callback_data="menu_account"),
            make_btn("🌐 المنصات المدعومة", callback_data="menu_platforms"),
        ],
        [
            make_btn("📩 تواصل مع الإدارة", callback_data="menu_contact_admin"),
            make_btn("ℹ️ مساعدة وأوامر", callback_data="menu_help"),
        ],
    ]
    if is_admin:
        buttons.append(
            [make_btn("🔐 لوحة تحكم الأدمن", callback_data="adm_main", style="danger")]
        )
    return InlineKeyboardMarkup(buttons)


def ai_menu_keyboard() -> InlineKeyboardMarkup:
    """قائمة الذكاء الاصطناعي لترشيح الفيديوهات حسب المزاج أو البحث الحر."""
    return InlineKeyboardMarkup(
        [
            [make_btn("✍️ اكتب طلبك أو مزاجك بحرية (AI)", callback_data="ai_custom", style="primary")],
            [
                make_btn("🔥 تريند وممتع", callback_data="ai_cat_trend", style="success"),
                make_btn("🎓 تعليمي وتطوير", callback_data="ai_cat_edu", style="primary"),
            ],
            [
                make_btn("😂 كوميدي وترفيه", callback_data="ai_cat_comedy"),
                make_btn("⚽ رياضة وأهداف", callback_data="ai_cat_sports"),
            ],
            [
                make_btn("🎬 ملخصات أفلام", callback_data="ai_cat_movies"),
                make_btn("🕌 قرآن ومواعظ", callback_data="ai_cat_islamic", style="success"),
            ],
            [
                make_btn("💻 برمجة وتقنية", callback_data="ai_cat_tech"),
                make_btn("💪 تحفيز ومذاكرة", callback_data="ai_cat_motivation"),
            ],
            [make_btn("🏠 الرئيسية", callback_data="menu_home")],
        ]
    )


def back_and_home_keyboard(back_callback: str = "menu_home") -> InlineKeyboardMarkup:
    row = []
    if back_callback != "menu_home":
        row.append(make_btn("⬅️ رجوع", callback_data=back_callback))
    row.append(make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"))
    return InlineKeyboardMarkup([row])


def force_sub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [make_btn("📢 اشترك في القناة الآن", url=FORCE_SUB_CHANNEL_URL, style="primary")],
            [make_btn("✅ تحقّق من الاشتراك", callback_data="check_sub", style="success")],
        ]
    )


def video_actions_keyboard(session_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                make_btn(
                    "🎵 تحميل الملف الصوتي (MP3)",
                    callback_data=f"audio:{session_key}",
                    style="primary",
                )
            ],
            [
                make_btn("📊 تفاصيل الفيديو", callback_data=f"vinfo:{session_key}"),
                make_btn("🏠 الرئيسية", callback_data="menu_home"),
            ],
        ]
    )


def audio_actions_keyboard(session_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                make_btn(
                    "✏️ إعادة تسمية الملف",
                    callback_data=f"rename:{session_key}",
                    style="primary",
                )
            ],
            [
                make_btn("🖼️ وضع غلاف للصوت", callback_data=f"cover:{session_key}", style="success"),
                make_btn("📝 وضع وصف للملف", callback_data=f"desc:{session_key}"),
            ],
            [make_btn("🏠 الرئيسية", callback_data="menu_home")],
        ]
    )


def image_actions_keyboard(session_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                make_btn(
                    "📂 إرسال الصورة الأصلية (بدون ضغط HD)",
                    callback_data=f"hdimg:{session_key}",
                    style="success",
                )
            ],
            [make_btn("🏠 الرئيسية", callback_data="menu_home")],
        ]
    )


def admin_main_keyboard(unreplied_count: int = 0, archive_count: int = 0) -> InlineKeyboardMarkup:
    msg_badge = f" ({unreplied_count} جديد)" if unreplied_count > 0 else ""
    arch_badge = f" ({archive_count})" if archive_count > 0 else ""
    return InlineKeyboardMarkup(
        [
            [
                make_btn("📊 الإحصائيات الشاملة", callback_data="adm_stats", style="primary"),
                make_btn("🩺 فحص النظام", callback_data="adm_health", style="success"),
            ],
            [
                make_btn(f"🗂️ الأرشيف{arch_badge}", callback_data="adm_arch_0", style="danger"),
                make_btn("📢 بث رسالة للجميع", callback_data="adm_broadcast", style="primary"),
            ],
            [
                make_btn("👥 إدارة المستخدمين", callback_data="adm_users_0"),
                make_btn("🔍 بحث / حظر بالـ ID", callback_data="adm_search_user", style="danger"),
            ],
            [
                make_btn(f"📩 رسائل الدعم{msg_badge}", callback_data="adm_msgs_0"),
                make_btn("🍪 إدارة الكوكيز", callback_data="adm_cookies", style="success"),
            ],
            [
                make_btn("⚙️ الإعدادات والترحيب", callback_data="adm_settings"),
                make_btn("🏠 الرئيسية", callback_data="menu_home"),
            ],
        ]
    )


# ═══════════════════════════════════════════════════════════════════════
# 🗄️ الفئة الأولى: إدارة قاعدة البيانات والأرشيف (DatabaseManager)
# ═══════════════════════════════════════════════════════════════════════


class DatabaseManager:
    """إدارة قاعدة بيانات SQLite: المستخدمين، الإحصائيات، الإعدادات، الدعم، الكوكيز، والأرشيف."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.lock = asyncio.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_tables()

    def _init_tables(self) -> None:
        cursor = self.conn.cursor()
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_stats (
                stat_date TEXT PRIMARY KEY,
                messages_count INTEGER NOT NULL DEFAULT 0,
                downloads_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_cookies (
                platform TEXT PRIMARY KEY,
                cookie_path TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # جدول الأرشيف الجديد لحفظ ومراقبة كل رابط يتم إرساله للبوت
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS url_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                platform TEXT DEFAULT '',
                url TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    async def register_or_update_user(self, user: Any) -> bool:
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

    # ── دوال الأرشيف (حفظ ومراجعة كل رابط) ──
    async def log_url_archive(
        self,
        user: Any,
        url: str,
        platform: str,
        status: str = "جارٍ التحميل",
    ) -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        uid = user.id if user else 0
        uname = (user.username or "") if user else ""
        full_name = (user.full_name or user.first_name or "مستخدم") if user else "مستخدم"
        async with self.lock:
            cur = self.conn.execute(
                """
                INSERT INTO url_archive (user_id, user_name, username, platform, url, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, full_name, uname, platform, url, status, now_str),
            )
            self.conn.commit()
            return int(cur.lastrowid or 0)

    async def update_archive_status(self, archive_id: int, status: str) -> None:
        if archive_id <= 0:
            return
        async with self.lock:
            self.conn.execute(
                "UPDATE url_archive SET status = ? WHERE id = ?",
                (status, archive_id),
            )
            self.conn.commit()

    async def get_archive_entries(
        self, limit: int = 8, offset: int = 0, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        async with self.lock:
            if user_id is not None:
                rows = self.conn.execute(
                    """
                    SELECT id, user_id, user_name, username, platform, url, status, created_at
                    FROM url_archive WHERE user_id = ?
                    ORDER BY id DESC LIMIT ? OFFSET ?
                    """,
                    (user_id, limit, offset),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """
                    SELECT id, user_id, user_name, username, platform, url, status, created_at
                    FROM url_archive ORDER BY id DESC LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
        return [
            {
                "id": r[0],
                "user_id": r[1],
                "user_name": r[2],
                "username": r[3],
                "platform": r[4],
                "url": r[5],
                "status": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]

    async def get_archive_entry_by_id(self, entry_id: int) -> dict[str, Any] | None:
        async with self.lock:
            r = self.conn.execute(
                """
                SELECT id, user_id, user_name, username, platform, url, status, created_at
                FROM url_archive WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r[0],
            "user_id": r[1],
            "user_name": r[2],
            "username": r[3],
            "platform": r[4],
            "url": r[5],
            "status": r[6],
            "created_at": r[7],
        }

    async def count_archive(self, user_id: int | None = None) -> int:
        async with self.lock:
            if user_id is not None:
                return int(
                    self.conn.execute(
                        "SELECT COUNT(*) FROM url_archive WHERE user_id = ?", (user_id,)
                    ).fetchone()[0]
                )
            return int(self.conn.execute("SELECT COUNT(*) FROM url_archive").fetchone()[0])

    async def delete_archive_entry(self, entry_id: int) -> None:
        async with self.lock:
            self.conn.execute("DELETE FROM url_archive WHERE id = ?", (entry_id,))
            self.conn.commit()

    async def clear_archive(self) -> int:
        async with self.lock:
            cur = self.conn.execute("DELETE FROM url_archive")
            self.conn.commit()
            return cur.rowcount

    async def export_archive_text(self) -> str:
        async with self.lock:
            rows = self.conn.execute(
                """
                SELECT id, created_at, user_id, user_name, username, platform, status, url
                FROM url_archive ORDER BY id DESC LIMIT 2000
                """
            ).fetchall()
        if not rows:
            return "الأرشيف فارغ حالياً."
        lines = [
            f"=== أرشيف روابط البوت ({datetime.now().strftime('%Y-%m-%d %H:%M')}) — الإجمالي: {len(rows)} ===",
            "",
        ]
        for r in rows:
            u_str = f"@{r[4]}" if r[4] else "بدون يوزر"
            lines.append(
                f"#{r[0]} | {r[1]} | {r[3]} ({u_str} / ID:{r[2]}) | [{r[5]}] ({r[6]})\n   URL: {r[7]}"
            )
        return "\n".join(lines)

    # ── دوال المستخدمين والإحصائيات ──
    async def get_user(self, user_id: int) -> dict[str, Any] | None:
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
        async with self.lock:
            cur = self.conn.execute(
                "UPDATE users SET is_banned = ? WHERE user_id = ?",
                (int(ban), user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    async def set_stop(self, user_id: int, stop: bool) -> bool:
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
            archive_count = self.conn.execute("SELECT COUNT(*) FROM url_archive").fetchone()[0]

        return {
            "total_users": total_users,
            "active_users": max(0, total_users - banned_users - stopped_users),
            "banned_users": banned_users,
            "stopped_users": stopped_users,
            "total_downloads": total_downloads,
            "today_messages": today_messages,
            "today_downloads": today_downloads,
            "unreplied_msgs": unreplied_msgs,
            "archive_count": archive_count,
        }

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

    async def save_cookie(self, platform: str, content: str) -> Path:
        COOKIES_DIR.mkdir(parents=True, exist_ok=True)
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


db = DatabaseManager(DB_PATH)
PLATFORM_COOKIES: dict[str, Path] = db.load_cookies_into_memory()

# ═══════════════════════════════════════════════════════════════════════
# 📦 إعداد Pyrogram الاختياري + أدوات الفحص والتنسيق
# ═══════════════════════════════════════════════════════════════════════

pyro_client: Any = None
try:
    if API_ID and API_HASH and TOKEN and TOKEN != "ضع_التوكن_هنا":
        from pyrogram import Client

        pyro_client = Client(
            "bot_session",
            api_id=int(API_ID),
            api_hash=str(API_HASH),
            bot_token=TOKEN,
            in_memory=True,
        )
except Exception as _pyro_err:
    logger.info("Pyrogram disabled or not configured: %s", _pyro_err)
    pyro_client = None


def _to_pyro_markup(markup: InlineKeyboardMarkup | None) -> Any:
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
        if media_type == "audio":
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


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def has_js_runtime() -> str | None:
    if shutil.which("deno"):
        return "Deno"
    if shutil.which("node"):
        return "Node.js"
    return None


def has_gallery_dl() -> bool:
    if shutil.which("gallery-dl"):
        return True
    try:
        import gallery_dl  # noqa: F401
        return True
    except Exception:
        return False


def get_system_health_report() -> str:
    try:
        import yt_dlp.version as _ydl_v
        ydl_ver = _ydl_v.__version__
    except Exception:
        ydl_ver = "غير معروف"

    ffmpeg_ok = "🟢 مثبت وجاهز" if has_ffmpeg() else "🔴 غير مثبت (ضروري لدمج HD و MP3)"
    js_rt = has_js_runtime()
    js_ok = f"🟢 {js_rt} متاح" if js_rt else "🟡 غير مثبت (مهم جداً ليوتيوب)"
    gdl_ok = "🟢 متاح (+300 موقع صور)" if has_gallery_dl() else "🟡 غير مثبت (pip install -U gallery-dl)"
    ai_ok = "🟢 Gemini AI + بحث يوتيوب" if GEMINI_API_KEY else "🟢 محرك ترشيح ذكي مدمج (مجاني)"
    pyro_ok = "🟢 مفعّل (حتى 2GB)" if pyro_client is not None else "⚪ غير مفعّل (الحد 50MB)"
    cookies_list = ", ".join(sorted(PLATFORM_COOKIES.keys())) or "لا يوجد"

    return (
        "🩺 <b>تقرير فحص صحة النظام PRO V2:</b>\n\n"
        f"• 📦 <b>إصدار yt-dlp:</b> <code>{html.escape(ydl_ver)}</code>\n"
        f"• 🎞️ <b>برنامج FFmpeg:</b> {ffmpeg_ok}\n"
        f"• ⚡ <b>محرك JavaScript:</b> {js_ok}\n"
        f"• 🖼️ <b>محرك الصور gallery-dl:</b> {gdl_ok}\n"
        f"• 🤖 <b>محرك ترشيح AI:</b> {ai_ok}\n"
        f"• 🚀 <b>رفع الملفات الضخمة:</b> {pyro_ok}\n"
        f"• 🍪 <b>الكوكيز المفعّلة:</b> <code>{html.escape(cookies_list)}</code>"
    )


def validate_netscape_cookies(content: str) -> tuple[bool, str]:
    stripped = content.strip()
    if not stripped:
        return False, "الملف فارغ تماماً."
    if stripped.startswith("[") or stripped.startswith("{"):
        return (
            False,
            "الملف بصيغة JSON وليس Netscape TXT! استخدم إضافة Get cookies.txt LOCALLY بصيغة Netscape.",
        )
    valid_lines = sum(
        1
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("#") and len(line.strip().split("\t")) >= 7
    )
    if valid_lines == 0:
        return False, "لم يتم العثور على أسطر كوكيز صالحة بصيغة Netscape (مفصولة بـ Tab)."
    return True, f"صالح ({valid_lines} سجل كوكيز)"


def extract_media_url(text: str) -> str | None:
    for raw_url in URL_PATTERN.findall(text):
        candidate = raw_url.rstrip(".,!?؛،)]}")
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
    return None


def platform_name(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    for name, domains in PLATFORM_HOSTS.items():
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            return "X / Twitter" if name == "twitter" else name.capitalize()
    return hostname or "المصدر"


def get_cookie_for_url(url: str) -> Path | None:
    plat = platform_name(url).lower()
    hostname = (urlparse(url).hostname or "").lower()
    for key, cookie_file in PLATFORM_COOKIES.items():
        if not cookie_file.is_file():
            continue
        if key in plat or plat in key or key in hostname:
            return cookie_file
        if key == "twitter" and ("x.com" in hostname or "twitter.com" in hostname):
            return cookie_file
    return None


def is_youtube_playlist(url: str) -> bool:
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
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


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
    cleaned = re.sub(r"[\\/:*?\"<>|{}\[\]\x00-\x1f]", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if cleaned.lower().endswith(".mp3"):
        cleaned = cleaned[:-4].rstrip(" .")
    return (cleaned[:90] or "ملف_صوتي") + ".mp3"


# === نهاية المرحلة 1 من 3 (الصق المرحلة 2 مباشرة أسفل هذا السطر) ===
import random

# ═══════════════════════════════════════════════════════════════════════
# ⚡ الفئة الثانية: محرك التحميل الشامل التربو (UniversalMediaEngine)
# ═══════════════════════════════════════════════════════════════════════

KNOWN_VIDEO_DOMAINS = set().union(*PLATFORM_HOSTS.values())


class UniversalMediaEngine:
    """
    محرك تحميل فائق السرعة (Turbo Mode):
    - استخراج فوري بدون تأخير مسبق على المنصات المعروفة
    - تحميل متوازي (16 خيط + 10MB chunks) لتجاوز تبطيء يوتيوب
    - أولوية فورية للكوكيز عند وجودها + بديل android_vr السريع
    - محرك صور شامل من 3 طبقات (رابط مباشر -> gallery-dl -> OpenGraph Scraper)
    """

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
        title = safe_html(metadata.get("title", "وسائط"), 200)
        uploader = safe_html(metadata.get("uploader", "غير متاح"), 70)
        platform = safe_html(metadata.get("platform", "المصدر"), 40)
        duration = safe_html(metadata.get("duration", "غير متاح"), 20)
        size = safe_html(metadata.get("size", "غير متاح"), 20)

        lines = [
            f"🎬 <b>{title}</b>",
            f"👤 <b>الحساب/القناة:</b> <i>{uploader}</i>",
            f"🌐 <b>المنصة:</b> <code>{platform}</code>  |  ⏱️ <b>المدة:</b> <code>{duration}</code>  |  📦 <b>الحجم:</b> <code>{size}</code>",
        ]
        if custom_desc:
            lines.append(f"\n📝 <b>الوصف:</b> {safe_html(custom_desc, 300)}")
        return "\n".join(lines)

    @staticmethod
    def build_technical_details_text(metadata: dict[str, str]) -> str:
        return (
            "📊 <b>التفاصيل التقنية والإحصائيات الكاملة:</b>\n\n"
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
        if source.suffix.lower() in {".jpg", ".jpeg"} and source.stat().st_size < 180_000:
            return source
        if not has_ffmpeg():
            return source if source.suffix.lower() in {".jpg", ".jpeg"} else None
        target = directory / "cover.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(source),
                    "-vf",
                    "scale='min(500,iw)':-2",
                    "-q:v",
                    "5",
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return target if target.is_file() and target.stat().st_size > 0 else None

    @staticmethod
    def _build_quality_profiles(plat: str, mode: str) -> list[tuple[str, str]]:
        """صيغة ذكية موحّدة تختار أفضل جودة مناسبة من أول محاولة بدون إضاعة وقت."""
        if mode == "audio":
            return [("ba[ext=m4a]/ba/bestaudio/best", "أفضل صوت")]

        ffmpeg_available = has_ffmpeg()
        limit_50mb = pyro_client is None

        if "instagram" in plat:
            return [("bv*+ba/b/best", "أفضل جودة إنستجرام")]

        if not ffmpeg_available:
            return [("b[ext=mp4][height<=720]/b[height<=720]/b[ext=mp4]/b", "فيديو جاهز سريع")]

        if limit_50mb:
            return [
                (
                    "bv*[height<=720][ext=mp4]+ba[ext=m4a]"
                    "/bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
                    "720p سريع ومتوافق",
                ),
                ("bv*[height<=480]+ba/b[height<=480]/b", "480p حجم أصغر"),
            ]

        return [
            ("bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b", "أعلى جودة MP4"),
            ("bv*[height<=1080]+ba/b[height<=1080]/b", "جودة 1080p"),
        ]

    @classmethod
    def download_media(
        cls, url: str, mode: str = "video"
    ) -> tuple[Path, dict[str, str], Path | None]:
        """تحميل فائق السرعة عبر yt-dlp مع أولوية ذكية للكوكيز وتجاوز تبطيء يوتيوب."""
        plat = platform_name(url).lower()
        is_youtube = "youtube" in plat
        cookie_file = get_cookie_for_url(url)
        quality_profiles = cls._build_quality_profiles(plat, mode)

        # ترتيب الاستراتيجيات للأسرع فالأسرع
        passes: list[tuple[bool, dict[str, Any] | None, str]] = []
        if is_youtube:
            if cookie_file:
                # لو الكوكيز موجودة نبدأ بها فوراً (الأسرع والأضمن)
                passes.append((True, None, "yt-cookies-fast"))
                passes.append((True, {"youtube": {"player_client": ["tv"]}}, "yt-tv-cookies"))
            passes.append((False, {"youtube": {"player_client": ["android_vr"]}}, "yt-android-vr"))
            passes.append((False, {"youtube": {"player_client": ["ios"]}}, "yt-ios"))
            passes.append((False, None, "yt-default"))
        else:
            if cookie_file:
                passes.append((True, None, "plat-cookies"))
            passes.append((False, None, "plat-fast"))

        with tempfile.TemporaryDirectory(prefix="tg-dl-") as temp_dir:
            directory = Path(temp_dir)
            last_error: Exception | None = None

            for use_cookies, extractor_args, pass_name in passes:
                for format_selector, quality_label in quality_profiles:
                    try:
                        output_template = str(directory / "%(title).75s-%(id)s.%(ext)s")
                        options: dict[str, Any] = {
                            "format": format_selector,
                            "outtmpl": output_template,
                            "noplaylist": True,
                            "quiet": True,
                            "no_warnings": True,
                            "retries": 5,
                            "fragment_retries": 5,
                            "extractor_retries": 2,
                            "skip_unavailable_fragments": True,
                            # إعدادات تسريع التحميل المتوازي وتجاوز التبطيء
                            "concurrent_fragment_downloads": 16,
                            "http_chunk_size": 10 * 1024 * 1024,
                            "buffersize": 1024 * 1024,
                            "socket_timeout": 20,
                            "continuedl": True,
                            "writethumbnail": True,
                            "restrictfilenames": True,
                            "overwrites": True,
                            "geo_bypass": True,
                            "nocheckcertificate": True,
                            "format_sort": ["ext:mp4:m4a", "vcodec:h264", "res:720"],
                        }

                        if not is_youtube:
                            options["http_headers"] = dict(BROWSER_HEADERS)
                            if "pinterest" in plat:
                                options["http_headers"]["Referer"] = "https://www.pinterest.com/"
                        else:
                            options["remote_components"] = ["ejs:github"]

                        if has_ffmpeg() and mode == "video":
                            options["merge_output_format"] = "mp4"

                        if extractor_args is not None:
                            options["extractor_args"] = extractor_args

                        if use_cookies and cookie_file and cookie_file.is_file():
                            options["cookiefile"] = str(cookie_file)

                        if mode == "audio" and has_ffmpeg():
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

                        skip_exts = {
                            ".part", ".ytdl", ".jpg", ".jpeg", ".png",
                            ".webp", ".json", ".vtt", ".srt", ".mhtml",
                        }
                        candidates = [
                            p for p in directory.iterdir()
                            if p.is_file() and p.suffix.lower() not in skip_exts and p.stat().st_size > 0
                        ]
                        if not candidates:
                            raise RuntimeError("لم يتم إنشاء ملف فيديو/صوت بعد التحميل.")

                        media_path = max(candidates, key=lambda p: p.stat().st_mtime)
                        file_size = media_path.stat().st_size

                        if pyro_client is None and file_size > TELEGRAM_BOT_API_MAX_BYTES:
                            if format_selector != quality_profiles[-1][0]:
                                raise RuntimeError(
                                    f"حجم الملف ({format_bytes(file_size)}) أكبر من 50MB، جاري تجربة جودة أقل."
                                )

                        logger.info(
                            "Turbo Downloaded [%s | %s] %s (%.1f MB)",
                            pass_name,
                            quality_label,
                            info.get("title") or "media",
                            file_size / 1024 / 1024,
                        )

                        fd, persistent_name = tempfile.mkstemp(suffix=media_path.suffix)
                        os.close(fd)
                        persistent_path = Path(persistent_name)
                        shutil.copy2(media_path, persistent_path)

                        metadata = cls.source_metadata(info, persistent_path)

                        persistent_cover: Path | None = None
                        cover_candidates = [
                            p for p in directory.iterdir()
                            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
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
                        clean_err = re.sub(r"\x1b\[[0-9;]*m", "", str(error))
                        last_error = RuntimeError(f"[{pass_name}] {clean_err}")
                        logger.warning("Pass [%s | %s] failed: %s", pass_name, quality_label, clean_err)
                        for old_file in directory.iterdir():
                            old_file.unlink(missing_ok=True)
                        err_low = clean_err.lower()
                        if any(
                            k in err_low
                            for k in (
                                "sign in", "bot", "cookies", "login",
                                "private", "403", "429", "requested format",
                            )
                        ):
                            break

            if last_error is not None:
                raise last_error
            raise RuntimeError("فشل التنزيل بعد استنفاد جميع المحاولات.")

    # ── محرك تحميل الصور من أي موقع (3 طبقات فائقة السرعة) ──

    @staticmethod
    def _ext_from_content_type(content_type: str, url: str) -> str:
        ct = (content_type or "").lower()
        if "png" in ct:
            return ".png"
        if "webp" in ct:
            return ".webp"
        if "gif" in ct:
            return ".gif"
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
        path_ext = Path(urlparse(url).path).suffix.lower()
        return path_ext if path_ext in IMAGE_EXTENSIONS else ".jpg"

    @classmethod
    def _download_single_image_url(cls, img_url: str, referer: str | None = None) -> Path | None:
        headers = dict(BROWSER_HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            with httpx.Client(
                follow_redirects=True, timeout=18.0, verify=False, headers=headers
            ) as client:
                resp = client.get(img_url)
                if resp.status_code != 200:
                    return None
                ct = resp.headers.get("content-type", "").lower()
                data = resp.content
                if len(data) < 3500:
                    return None
                is_img = (
                    ct.startswith("image/")
                    or Path(urlparse(img_url).path).suffix.lower() in IMAGE_EXTENSIONS
                )
                if not is_img or "svg" in ct:
                    return None
                ext = cls._ext_from_content_type(ct, img_url)
                fd, dst_name = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                dst = Path(dst_name)
                dst.write_bytes(data)
                return dst
        except Exception:
            return None

    @classmethod
    def is_direct_image_url(cls, url: str) -> bool:
        """فحص فوري (0ms للمنصات المعروفة) لتجنب إبطاء روابط الفيديو."""
        parsed = urlparse(url)
        path_ext = Path(parsed.path).suffix.lower()
        if path_ext in IMAGE_EXTENSIONS:
            return True

        # تسريع فوري: لا نرسل طلب HEAD لروابط المنصات المعروفة
        hostname = (parsed.hostname or "").lower()
        if any(hostname == d or hostname.endswith(f".{d}") for d in KNOWN_VIDEO_DOMAINS):
            return False

        try:
            with httpx.Client(
                follow_redirects=True, timeout=4.0, verify=False, headers=BROWSER_HEADERS
            ) as client:
                resp = client.head(url)
                ct = resp.headers.get("content-type", "").lower()
                return ct.startswith("image/") and "svg" not in ct
        except Exception:
            return False

    @classmethod
    def _download_via_gallery_dl(cls, url: str) -> list[Path]:
        if not has_gallery_dl():
            return []
        cookie_file = get_cookie_for_url(url)
        with tempfile.TemporaryDirectory(prefix="tg-gdl-") as temp_dir:
            gdl_bin = shutil.which("gallery-dl")
            cmd = [gdl_bin] if gdl_bin else [sys.executable, "-m", "gallery_dl"]
            cmd.extend(["--directory", temp_dir, "--range", "1-10", "--quiet"])
            if cookie_file and cookie_file.is_file():
                cmd.extend(["--cookies", str(cookie_file)])
            cmd.append(url)
            try:
                subprocess.run(
                    cmd,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                )
            except Exception:
                return []

            found = sorted(
                [
                    p for p in Path(temp_dir).rglob("*")
                    if p.is_file()
                    and p.suffix.lower() in IMAGE_EXTENSIONS
                    and p.stat().st_size > 3500
                ],
                key=lambda p: p.name,
            )
            result: list[Path] = []
            for img in found[:10]:
                fd, dst_name = tempfile.mkstemp(suffix=img.suffix.lower())
                os.close(fd)
                dst = Path(dst_name)
                shutil.copy2(img, dst)
                result.append(dst)
            return result

    @classmethod
    def _download_via_webpage_scraper(cls, url: str) -> tuple[list[Path], str]:
        try:
            with httpx.Client(
                follow_redirects=True, timeout=15.0, verify=False, headers=BROWSER_HEADERS
            ) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    return [], ""
                ct = resp.headers.get("content-type", "").lower()
                if ct.startswith("image/"):
                    p = cls._download_single_image_url(url)
                    return ([p] if p else []), ""
                page_html = resp.text[:350_000]
        except Exception:
            return [], ""

        title_match = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
        page_title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""

        candidate_urls: list[str] = []
        meta_patterns = [
            r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
            r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        ]
        for pat in meta_patterns:
            for match in re.findall(pat, page_html, re.IGNORECASE):
                full_u = urljoin(url, html.unescape(match.strip()))
                if full_u.startswith("http") and full_u not in candidate_urls:
                    candidate_urls.append(full_u)

        for ld_raw in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            page_html,
            re.IGNORECASE | re.DOTALL,
        ):
            try:
                ld_data = json.loads(ld_raw)
                items = ld_data if isinstance(ld_data, list) else [ld_data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    img_field = item.get("image")
                    imgs = img_field if isinstance(img_field, list) else [img_field]
                    for im in imgs:
                        u = im.get("url") if isinstance(im, dict) else (im if isinstance(im, str) else None)
                        if u:
                            full_u = urljoin(url, u)
                            if full_u.startswith("http") and full_u not in candidate_urls:
                                candidate_urls.append(full_u)
            except Exception:
                pass

        if not candidate_urls:
            for m in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', page_html, re.IGNORECASE):
                if m.startswith("data:") or "logo" in m.lower() or "icon" in m.lower():
                    continue
                full_u = urljoin(url, html.unescape(m.strip()))
                if full_u.startswith("http") and full_u not in candidate_urls:
                    candidate_urls.append(full_u)
                if len(candidate_urls) >= 8:
                    break

        downloaded: list[Path] = []
        for img_u in candidate_urls[:10]:
            p = cls._download_single_image_url(img_u, referer=url)
            if p is not None:
                downloaded.append(p)
            if len(downloaded) >= 10:
                break

        return downloaded, page_title

    @classmethod
    def download_images_universal(cls, url: str) -> tuple[list[Path], str]:
        if cls.is_direct_image_url(url):
            single = cls._download_single_image_url(url)
            if single:
                return [single], Path(urlparse(url).path).name or "صورة"

        gdl_images = cls._download_via_gallery_dl(url)
        if gdl_images:
            return gdl_images, f"صور من {platform_name(url)}"

        web_images, title = cls._download_via_webpage_scraper(url)
        if web_images:
            return web_images, title or f"صور من {platform_name(url)}"

        return [], ""

    @classmethod
    def download_tiktok_photos(cls, url: str) -> tuple[list[Path], dict[str, str]]:
        gdl_imgs = cls._download_via_gallery_dl(url)
        if gdl_imgs:
            return gdl_imgs, {"title": "ألبوم صور تيك توك"}

        with tempfile.TemporaryDirectory(prefix="tiktok-photo-") as temp_dir:
            directory = Path(temp_dir)
            options: dict[str, Any] = {
                "outtmpl": str(directory / "%(autonumber)03d_%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "retries": 4,
                "socket_timeout": 20,
                "http_headers": dict(BROWSER_HEADERS),
            }
            cookie_file = get_cookie_for_url(url)
            if cookie_file:
                options["cookiefile"] = str(cookie_file)

            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                if not isinstance(info, dict):
                    return [], {}
            except Exception:
                return [], {}

            all_files = [p for p in directory.iterdir() if p.is_file()]
            if any(p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"} for p in all_files):
                return [], {}

            images = sorted(
                [p for p in all_files if p.suffix.lower() in IMAGE_EXTENSIONS and p.stat().st_size > 2000],
                key=lambda p: p.name,
            )
            if not images:
                return [], {}

            result: list[Path] = []
            for src in images[:10]:
                fd, dst_name = tempfile.mkstemp(suffix=src.suffix.lower())
                os.close(fd)
                dst = Path(dst_name)
                shutil.copy2(src, dst)
                result.append(dst)

            return result, cls.source_metadata(info, images[0])

    @staticmethod
    def extract_playlist_entries(url: str) -> list[dict[str, str]]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "socket_timeout": 20,
        }
        yt_cookie = PLATFORM_COOKIES.get("youtube")
        if yt_cookie and yt_cookie.is_file():
            options["cookiefile"] = str(yt_cookie)

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                return []
            result = []
            for e in info.get("entries") or []:
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
# 🤖 الفئة الثالثة: محرك الذكاء الاصطناعي لترشيح الفيديوهات (AIVideoRecommender)
# ═══════════════════════════════════════════════════════════════════════


class AIVideoRecommender:
    """
    يرشح للمستخدم فيديوهات حقيقية من يوتيوب قابلة للتحميل الفوري (فيديو أو MP3):
    - يعمل فوراً ومجاناً 100% عبر محرك بحث ذكي وتصنيفات متجددة
    - وإذا تم وضع GEMINI_API_KEY يحلل مزاج المستخدم وطلباته المعقدة بالذكاء الاصطناعي
    """

    CATEGORY_POOLS: dict[str, tuple[str, list[str]]] = {
        "trend": (
            "🔥 تريند وممتع",
            [
                "أفضل فيديوهات الدحيح ممتعة ومفيدة",
                "تحديات ممتعة يوتيوب عربي",
                "مغامرات وسفر حول العالم وثائقي قصير",
                "حقائق غريبة ومذهلة لم تسمع بها من قبل",
                "قصص نجاح واقعية ملهمة قصيرة",
            ],
        ),
        "edu": (
            "🎓 تعليمي وتطوير ذات",
            [
                "ملخص كتاب العادات الذرية عربي",
                "كيف تطور مهاراتك وتنظم وقتك",
                "معلومات علمية شيقة ومبسطة",
                "تعلم مهارات جديدة مفيدة في الحياة",
                "أفضل بودكاست عربي لتطوير الذات",
            ],
        ),
        "comedy": (
            "😂 كوميدي وترفيه",
            [
                "مقاطع كوميدية مصرية مضحكة",
                "ستاند اب كوميدي عربي مضحك",
                "مواقف طريفة ومضحكة قصيرة",
                "أفضل مقالب مضحكة ونظيفة",
            ],
        ),
        "sports": (
            "⚽ رياضة وأهداف عالمية",
            [
                "أجمل أهداف كرة القدم التاريخية",
                "مهارات محمد صلاح وأجمل الأهداف",
                "ملخصات ومهارات دوري أبطال أوروبا",
                "أقوى لحظات كرة القدم الحماسية",
            ],
        ),
        "movies": (
            "🎬 ملخصات أفلام مشوقة",
            [
                "ملخص فيلم غموض وذكاء مشوق عربي",
                "ملخص فيلم أكشن وإثارة ممتاز",
                "ملخص فيلم خيال علمي رهيب",
                "أفضل ملخصات أفلام قصيرة وممتعة",
            ],
        ),
        "islamic": (
            "🕌 قرآن وتلاوات ومواعظ",
            [
                "تلاوة خاشعة تريح القلب والاعصاب",
                "تلاوة قرآنية هادئة ياسر الدوسري",
                "موعظة دينية قصيرة مؤثرة للقلب",
                "أجمل تلاوات الشيخ المنشاوي",
            ],
        ),
        "tech": (
            "💻 برمجة وتقنية وذكاء اصطناعي",
            [
                "أحدث أخبار وتطبيقات الذكاء الاصطناعي",
                "مراجعة أحدث الهواتف الذكية عربي",
                "تعلم بايثون للمبتدئين بسهولة",
                "أفضل أدوات الذكاء الاصطناعي المجانية",
            ],
        ),
        "motivation": (
            "💪 تحفيز ومذاكرة وتركيز",
            [
                "فيديو تحفيزي قوي للدراسة والنجاح",
                "كيف تتغلب على الكسل والتسويف",
                "نصائح ذهبية للتركيز والمذاكرة",
                "قصص إصرار ونجاح ملهمة جداً",
            ],
        ),
    }

    @classmethod
    def _refine_query_with_gemini(cls, user_prompt: str) -> tuple[str, str]:
        """إذا وُجد مفتاح Gemini API نحول وصف المستخدم لاستعلام بحث ذكي + جملة ترشيح."""
        if not GEMINI_API_KEY:
            return user_prompt, f"🤖 ترشيحات ذكية مناسبة لطلبك: «{user_prompt}»"

        try:
            endpoint = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            )
            prompt = (
                "المستخدم يريد ترشيح فيديوهات يوتيوب بناءً على طلبه التالي:\n"
                f"«{user_prompt}»\n\n"
                "أجب بصيغة JSON فقط بدون أي نص إضافي:\n"
                '{"query": "عبارة بحث يوتيوب دقيقة وممتازة (3-6 كلمات)", '
                '"intro": "جملة عربية قصيرة وجذابة تشرح سبب هذا الترشيح"}'
            )
            with httpx.Client(timeout=10.0) as client:
                r = client.post(
                    endpoint,
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                if r.status_code == 200:
                    data = r.json()
                    txt = data["candidates"][0]["content"]["parts"][0]["text"]
                    m = re.search(r"\{.*\}", txt, re.DOTALL)
                    if m:
                        parsed = json.loads(m.group(0))
                        q = str(parsed.get("query") or user_prompt).strip()
                        intro = str(parsed.get("intro") or f"🤖 ترشيحات AI لطلبك: {user_prompt}").strip()
                        return q, intro
        except Exception as exc:
            logger.debug("Gemini refinement fallback: %s", exc)

        return user_prompt, f"🤖 ترشيحات ذكية مناسبة لطلبك: «{user_prompt}»"

    @classmethod
    def search_youtube_fast(cls, query: str, count: int = 5) -> list[dict[str, str]]:
        """بحث يوتيوب سريع جداً (extract_flat) يستغرق ~1.5 ثانية فقط."""
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": 15,
        }
        yt_cookie = PLATFORM_COOKIES.get("youtube")
        if yt_cookie and yt_cookie.is_file():
            options["cookiefile"] = str(yt_cookie)

        results: list[dict[str, str]] = []
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(f"ytsearch{count + 3}:{query}", download=False)
                entries = (info or {}).get("entries") or []
                for e in entries:
                    if not e:
                        continue
                    vid_id = e.get("id")
                    title = str(e.get("title") or "").strip()
                    if not vid_id or not title:
                        continue
                    vid_url = e.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
                    if not str(vid_url).startswith("http"):
                        vid_url = f"https://www.youtube.com/watch?v={vid_id}"
                    results.append(
                        {
                            "id": str(vid_id),
                            "title": title[:75],
                            "url": str(vid_url),
                            "channel": str(e.get("channel") or e.get("uploader") or "YouTube")[:35],
                            "duration": format_duration(e.get("duration")),
                            "views": format_count(e.get("view_count")),
                        }
                    )
                    if len(results) >= count:
                        break
        except Exception as exc:
            logger.warning("AI YouTube search failed: %s", exc)
        return results

    @classmethod
    def recommend(cls, *, category: str | None = None, custom_prompt: str | None = None) -> tuple[str, list[dict[str, str]]]:
        """إرجاع جملة تعريفية + قائمة فيديوهات مرشّحة جاهزة للتحميل."""
        if category and category in cls.CATEGORY_POOLS:
            cat_title, queries = cls.CATEGORY_POOLS[category]
            chosen_query = random.choice(queries)
            intro = f"🤖 <b>ترشيحات الذكاء الاصطناعي — {cat_title}</b>\n🔎 <i>محور الاختيار: {html.escape(chosen_query)}</i>"
            videos = cls.search_youtube_fast(chosen_query, count=5)
            return intro, videos

        clean_prompt = (custom_prompt or "أفضل فيديوهات ممتعة ومفيدة").strip()[:120]
        query, intro_text = cls._refine_query_with_gemini(clean_prompt)
        intro = f"✨ <b>{html.escape(intro_text)}</b>"
        videos = cls.search_youtube_fast(query, count=5)
        return intro, videos


# ═══════════════════════════════════════════════════════════════════════
# 🧠 إدارة الجلسات، الكاش السريع (File ID Cache)، والحالات المؤقتة
# ═══════════════════════════════════════════════════════════════════════

media_sessions: dict[str, dict[str, Any]] = {}
# كاش file_id لإرسال الروابط المكررة في أقل من ثانية!
url_file_id_cache: dict[tuple[str, str], dict[str, Any]] = {}

# حالات المستخدمين
rename_pending: dict[tuple[int, int], str] = {}
cover_pending: dict[tuple[int, int], str] = {}
desc_pending: dict[tuple[int, int], str] = {}
user_support_pending: set[int] = set()
ai_custom_pending: set[int] = set()

# حالات الأدمن
admin_broadcast_pending: set[int] = set()
admin_send_msg_pending: dict[int, int] = {}
admin_reply_ticket_pending: dict[int, int] = {}
admin_welcome_edit_pending: set[int] = set()
admin_search_user_pending: set[int] = set()
admin_cookie_selected_platform: dict[int, str] = {}


def _prune_store(store: dict[Any, Any], limit: int = 1000) -> None:
    if len(store) > limit:
        del store[next(iter(store))]


def clear_user_pending_states(chat_id: int, user_id: int) -> None:
    key = (chat_id, user_id)
    rename_pending.pop(key, None)
    cover_pending.pop(key, None)
    desc_pending.pop(key, None)
    user_support_pending.discard(user_id)
    ai_custom_pending.discard(user_id)
    if user_id == OWNER_ID:
        admin_broadcast_pending.discard(user_id)
        admin_send_msg_pending.pop(user_id, None)
        admin_reply_ticket_pending.pop(user_id, None)
        admin_welcome_edit_pending.discard(user_id)
        admin_search_user_pending.discard(user_id)
        admin_cookie_selected_platform.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════════════
# 📢 التحقق من الاشتراك الإجباري
# ═══════════════════════════════════════════════════════════════════════


async def check_user_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
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
        return member.status not in ("left", "kicked", "banned")
    except BadRequest as exc:
        logger.warning("Force-sub warning for %s: %s", channel_id, exc)
        return False
    except Exception:
        return True


async def send_force_sub_prompt(update: Update) -> None:
    user_name = (
        html.escape(update.effective_user.first_name)
        if update.effective_user and update.effective_user.first_name
        else "صديقي"
    )
    text = (
        f"⚠️ <b>عذراً يا {user_name}، لا يمكنك استخدام البوت قبل الاشتراك في القناة الرسمية!</b>\n\n"
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


# ═══════════════════════════════════════════════════════════════════════
# 📤 الإرسال التربو للوسائط (كاش فوري + أرشيف رقابي + فيديو/صوت/صور)
# ═══════════════════════════════════════════════════════════════════════


async def _send_image_list(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
    image_paths: list[Path],
    title: str,
    source_url: str,
    as_document: bool = False,
) -> None:
    if not image_paths:
        return

    safe_title = safe_html(title or f"صور من {platform_name(source_url)}", 180)
    plat = safe_html(platform_name(source_url), 40)
    caption = f"🖼️ <b>{safe_title}</b>\n🌐 <b>المصدر:</b> <code>{plat}</code>"

    try:
        if as_document:
            await context.bot.send_chat_action(
                chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT
            )
            for idx, img_path in enumerate(image_paths[:5], start=1):
                with open(img_path, "rb") as fh:
                    await context.bot.send_document(
                        chat_id=message.chat_id,
                        document=fh,
                        filename=f"image_{idx}{img_path.suffix or '.jpg'}",
                        caption=f"📂 <b>الصورة الأصلية بدون ضغط (HD)</b>\n{caption}" if idx == 1 else None,
                        parse_mode=ParseMode.HTML if idx == 1 else None,
                        reply_to_message_id=message.message_id,
                        read_timeout=180,
                        write_timeout=180,
                    )
            return

        await context.bot.send_chat_action(
            chat_id=message.chat_id, action=ChatAction.UPLOAD_PHOTO
        )

        if len(image_paths) == 1:
            session_key = secrets.token_urlsafe(8)
            media_sessions[session_key] = {"url": source_url, "type": "image", "title": title}
            _prune_store(media_sessions)

            img_path = image_paths[0]
            try:
                with open(img_path, "rb") as fh:
                    await context.bot.send_photo(
                        chat_id=message.chat_id,
                        photo=fh,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=image_actions_keyboard(session_key),
                        reply_to_message_id=message.message_id,
                        read_timeout=180,
                        write_timeout=180,
                    )
            except BadRequest:
                with open(img_path, "rb") as fh:
                    await context.bot.send_document(
                        chat_id=message.chat_id,
                        document=fh,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=message.message_id,
                    )
            return

        file_handles: list[Any] = []
        try:
            media_group = []
            for i, p in enumerate(image_paths[:10]):
                fh = open(p, "rb")
                file_handles.append(fh)
                media_group.append(
                    InputMediaPhoto(
                        media=fh,
                        caption=f"{caption}\n📸 <b>عدد الصور:</b> <code>{len(image_paths[:10])}</code>" if i == 0 else None,
                        parse_mode=ParseMode.HTML if i == 0 else None,
                    )
                )
            await context.bot.send_media_group(
                chat_id=message.chat_id,
                media=media_group,
                reply_to_message_id=message.message_id,
                read_timeout=240,
                write_timeout=240,
            )
        except BadRequest:
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass
            file_handles.clear()
            for idx, p in enumerate(image_paths[:10]):
                with open(p, "rb") as fh:
                    try:
                        await context.bot.send_photo(
                            chat_id=message.chat_id,
                            photo=fh,
                            caption=caption if idx == 0 else None,
                            parse_mode=ParseMode.HTML if idx == 0 else None,
                            reply_to_message_id=message.message_id,
                        )
                    except BadRequest:
                        fh.seek(0)
                        await context.bot.send_document(
                            chat_id=message.chat_id,
                            document=fh,
                            caption=caption if idx == 0 else None,
                            parse_mode=ParseMode.HTML if idx == 0 else None,
                            reply_to_message_id=message.message_id,
                        )
        finally:
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass
    finally:
        for p in image_paths:
            p.unlink(missing_ok=True)


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
    request_user: Any = None,
    skip_archive: bool = False,
) -> None:
    """الإرسال السريع مع الكاش الفوري وتسجيل كل رابط في أرشيف الأدمن."""
    if message is None:
        return

    actor = request_user or message.from_user
    plat_label = platform_name(url)

    # 1. تسجيل الرابط فوراً في أرشيف الأدمن للمراجعة والرقابة
    archive_id = 0
    if not skip_archive:
        try:
            archive_id = await db.log_url_archive(actor, url, plat_label, "⏳ جاري التحميل")
        except Exception:
            archive_id = 0

    # 2. الكاش التربو: لو الرابط نزل قبل كده وبنفس الإعدادات الافتراضية نرسله في 0.3 ثانية!
    cache_key = (url.strip(), mode)
    can_use_cache = (
        mode in ("video", "audio")
        and custom_filename is None
        and custom_thumbnail is None
        and custom_caption is None
        and custom_performer is None
        and cache_key in url_file_id_cache
    )
    if can_use_cache:
        cached = url_file_id_cache[cache_key]
        try:
            session_key = secrets.token_urlsafe(8)
            media_sessions[session_key] = {
                "url": url,
                "metadata": cached["metadata"],
                "type": mode,
            }
            _prune_store(media_sessions)
            if mode == "audio":
                await context.bot.send_audio(
                    chat_id=message.chat_id,
                    audio=cached["file_id"],
                    caption=cached["caption"],
                    parse_mode=ParseMode.HTML,
                    reply_markup=audio_actions_keyboard(session_key),
                    reply_to_message_id=message.message_id,
                )
            else:
                await context.bot.send_video(
                    chat_id=message.chat_id,
                    video=cached["file_id"],
                    caption=cached["caption"],
                    parse_mode=ParseMode.HTML,
                    reply_markup=video_actions_keyboard(session_key),
                    reply_to_message_id=message.message_id,
                )
            if actor:
                await db.increment_download(actor.id)
            if archive_id:
                await db.update_archive_status(archive_id, "✅ ناجح (إرسال فوري)")
            return
        except Exception:
            url_file_id_cache.pop(cache_key, None)

    # 3. إظهار رسالة الانتظار
    loading_msg = None
    if show_loading:
        status_label = {
            "audio": "🎵 جاري استخراج الصوت (MP3) بأقصى سرعة...",
            "image": "🖼️ جاري سحب الصور بأعلى دقة...",
            "image_hd": "📂 جاري تجهيز الصورة الأصلية (HD)...",
        }.get(mode, "⚡ جاري التحميل الفوري بأعلى جودة...")
        try:
            loading_msg = await message.reply_text(
                f"<b>{status_label}</b>",
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
        # ── المسار 1: طلب صور صريح أو رابط صورة مباشر ──
        if mode in ("image", "image_hd") or (
            mode == "video" and await asyncio.to_thread(UniversalMediaEngine.is_direct_image_url, url)
        ):
            async with download_slots:
                img_paths, img_title = await asyncio.wait_for(
                    asyncio.to_thread(UniversalMediaEngine.download_images_universal, url),
                    timeout=180,
                )
            if img_paths:
                await _send_image_list(
                    message, context, img_paths, img_title, url, as_document=(mode == "image_hd")
                )
                await delete_loading()
                if actor:
                    await db.increment_download(actor.id)
                if archive_id:
                    await db.update_archive_status(archive_id, "✅ صور")
                return
            if mode in ("image", "image_hd"):
                raise RuntimeError("لم يتم العثور على صور قابلة للتحميل في هذا الرابط.")

        # ── المسار 2: ألبومات صور تيك توك (فقط لو الرابط فيه /photo/ لعدم إبطاء فيديوهات تيك توك) ──
        if mode == "video" and plat_label.lower() == "tiktok" and "/photo/" in url.lower():
            async with download_slots:
                photo_paths, photo_meta = await asyncio.wait_for(
                    asyncio.to_thread(UniversalMediaEngine.download_tiktok_photos, url),
                    timeout=150,
                )
            if photo_paths:
                title = (photo_meta.get("title") or "ألبوم صور تيك توك").strip()
                await _send_image_list(message, context, photo_paths, title, url)
                await delete_loading()
                if actor:
                    await db.increment_download(actor.id)
                if archive_id:
                    await db.update_archive_status(archive_id, "✅ ألبوم صور")
                return

        # ── المسار 3: تحميل الفيديو أو الصوت بأقصى سرعة (مع خطة بديلة تلقائية للصور) ──
        try:
            async with download_slots:
                action = ChatAction.UPLOAD_VOICE if mode == "audio" else ChatAction.UPLOAD_VIDEO
                asyncio.create_task(context.bot.send_chat_action(chat_id=message.chat_id, action=action))
                downloaded_path, metadata, cover_path = await asyncio.wait_for(
                    asyncio.to_thread(UniversalMediaEngine.download_media, url, mode),
                    timeout=DOWNLOAD_TIMEOUT_SECONDS,
                )
        except Exception as ydl_error:
            if mode == "video":
                logger.info("yt-dlp failed for %s — trying image fallback...", url)
                async with download_slots:
                    if plat_label.lower() == "tiktok":
                        fb_imgs, fb_meta = await asyncio.wait_for(
                            asyncio.to_thread(UniversalMediaEngine.download_tiktok_photos, url),
                            timeout=100,
                        )
                        fb_title = fb_meta.get("title") or "ألبوم صور تيك توك"
                    else:
                        fb_imgs, fb_title = await asyncio.wait_for(
                            asyncio.to_thread(UniversalMediaEngine.download_images_universal, url),
                            timeout=100,
                        )
                if fb_imgs:
                    await _send_image_list(message, context, fb_imgs, fb_title, url)
                    await delete_loading()
                    if actor:
                        await db.increment_download(actor.id)
                    if archive_id:
                        await db.update_archive_status(archive_id, "✅ صور")
                    return
            raise ydl_error

        session_key = secrets.token_urlsafe(8)
        media_sessions[session_key] = {"url": url, "metadata": metadata, "type": mode}
        _prune_store(media_sessions)

        caption_html = UniversalMediaEngine.build_caption(metadata, custom_caption)
        thumb_to_use = custom_thumbnail if custom_thumbnail is not None else cover_path
        file_size = downloaded_path.stat().st_size

        sent_msg = None
        if mode == "audio":
            markup = audio_actions_keyboard(session_key)
            audio_fname = custom_filename or clean_filename(metadata["title"])
            performer = (custom_performer or metadata["uploader"])[:64]
            title = metadata["title"][:64]
            duration_sec = int(metadata.get("duration_seconds") or 0)

            sent_via_pyro = None
            if file_size > TELEGRAM_BOT_API_MAX_BYTES and pyro_client is not None:
                sent_via_pyro = await upload_large_media_pyrogram(
                    chat_id=message.chat_id,
                    media_path=downloaded_path,
                    media_type="audio",
                    caption=caption_html,
                    reply_to_message_id=message.message_id,
                    reply_markup=markup,
                    duration=duration_sec,
                    performer=performer,
                    title=title,
                    thumb=thumb_to_use,
                )

            if not sent_via_pyro:
                if file_size > TELEGRAM_BOT_API_MAX_BYTES:
                    raise RuntimeError(
                        f"حجم الصوت ({format_bytes(file_size)}) أكبر من حد تيليجرام 50MB."
                    )
                with open(downloaded_path, "rb") as audio_file:
                    thumb_fh = (
                        open(thumb_to_use, "rb")
                        if thumb_to_use and thumb_to_use.is_file()
                        else None
                    )
                    try:
                        sent_msg = await context.bot.send_audio(
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
                if sent_msg and sent_msg.audio and custom_filename is None and custom_thumbnail is None and custom_caption is None:
                    url_file_id_cache[cache_key] = {
                        "file_id": sent_msg.audio.file_id,
                        "caption": caption_html,
                        "metadata": metadata,
                    }
                    _prune_store(url_file_id_cache, limit=300)
        else:
            markup = video_actions_keyboard(session_key)
            duration_sec = int(metadata.get("duration_seconds") or 0)

            sent_via_pyro = None
            if file_size > TELEGRAM_BOT_API_MAX_BYTES and pyro_client is not None:
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
                if file_size > TELEGRAM_BOT_API_MAX_BYTES:
                    raise RuntimeError(
                        f"حجم الفيديو ({format_bytes(file_size)}) أكبر من حد تيليجرام (50MB). "
                        "يمكنك تحميل الصوت فقط بـ /audio أو تفعيل Pyrogram لرفع ملفات حتى 2GB."
                    )
                with open(downloaded_path, "rb") as video_file:
                    thumb_fh = (
                        open(thumb_to_use, "rb")
                        if thumb_to_use and thumb_to_use.is_file()
                        else None
                    )
                    try:
                        sent_msg = await context.bot.send_video(
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
                if sent_msg and sent_msg.video:
                    url_file_id_cache[cache_key] = {
                        "file_id": sent_msg.video.file_id,
                        "caption": caption_html,
                        "metadata": metadata,
                    }
                    _prune_store(url_file_id_cache, limit=300)

        await delete_loading()
        if actor:
            await db.increment_download(actor.id)
        if archive_id:
            await db.update_archive_status(archive_id, "✅ تم التحميل")

    except asyncio.TimeoutError:
        await delete_loading()
        if archive_id:
            await db.update_archive_status(archive_id, "⚠️ انتهت المهلة")
        await message.reply_text(
            "⚠️ <b>انتهت مهلة التحميل!</b>\nحجم الملف كبير أو الاتصال بالمصدر بطيء حالياً.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )
    except Exception as error:
        logger.exception("Error downloading URL %s: %s", url, error)
        await delete_loading()
        if archive_id:
            await db.update_archive_status(archive_id, "❌ فشل")

        plat_hint = plat_label.lower()
        extra_hint = ""
        if "instagram" in plat_hint:
            extra_hint = "\n• 🍪 إنستجرام يتطلب كوكيز حديثة من لوحة التحكم ← إدارة الكوكيز."
        elif "youtube" in plat_hint:
            extra_hint = "\n• 🛠️ يوتيوب: تأكد من تحديث الكوكيز ووجود Node.js و FFmpeg."

        admin_debug = ""
        if actor and actor.id == OWNER_ID:
            clean_err = re.sub(r"\x1b\[[0-9;]*m", "", str(error))
            admin_debug = (
                f"\n\n🩺 <b>تفاصيل الخطأ (تظهر للأدمن فقط):</b>\n"
                f"<code>{html.escape(clean_err[:420])}</code>"
            )

        await message.reply_text(
            "❌ <b>عذراً، تعذّر تحميل هذا الرابط!</b>\n\n"
            "• تأكد أن المنشور عام وليس خاصاً (Private).\n"
            "• تأكد من صحة الرابط وأن المحتوى متاح."
            f"{extra_hint}"
            f"{admin_debug}",
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
    actor = message.from_user
    try:
        await db.log_url_archive(actor, url, "YouTube Playlist", "📋 قائمة تشغيل")
    except Exception:
        pass

    wait_msg = await message.reply_text(
        "⏳ <b>جاري فحص قائمة التشغيل (Playlist)...</b>", parse_mode=ParseMode.HTML
    )
    try:
        entries = await asyncio.wait_for(
            asyncio.to_thread(UniversalMediaEngine.extract_playlist_entries, url),
            timeout=60,
        )
    except Exception as err:
        logger.warning("Playlist extraction failed: %s", err)
        await wait_msg.edit_text(
            "❌ <b>تعذّر جلب قائمة التشغيل!</b>\nتأكد من أنها عامة وليست خاصة.",
            parse_mode=ParseMode.HTML,
        )
        return

    total = len(entries)
    if total == 0:
        await wait_msg.edit_text(
            "⚠️ <b>لم يتم العثور على فيديوهات داخل هذه القائمة.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    done_count = 0
    fail_count = 0
    counter_lock = asyncio.Lock()

    await wait_msg.edit_text(
        f"📋 <b>تم العثور على {total} فيديو في القائمة!</b>\n⏳ جاري التحميل: <b>0 / {total}</b>",
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
                    message, context, entry["url"], show_loading=False, request_user=actor, skip_archive=True
                )
                async with counter_lock:
                    done_count += 1
            except Exception as err:
                logger.warning("Playlist item %d failed: %s", idx, err)
                async with counter_lock:
                    done_count += 1
                    fail_count += 1
            await _update_progress()

    tasks = [asyncio.create_task(_download_one(idx, entry)) for idx, entry in enumerate(entries, 1)]
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


# === نهاية المرحلة 2 من 3 (الصق المرحلة 3 مباشرة أسفل هذا السطر) ===
# ═══════════════════════════════════════════════════════════════════════
# 💬 أوامر البوت والقوائم التفاعلية للمستخدمين
# ═══════════════════════════════════════════════════════════════════════


async def build_welcome_text(user: Any) -> str:
    user_name = (user.first_name if user and user.first_name else "صديقي").strip()
    raw_template = await db.get_setting("welcome_message", DEFAULT_WELCOME_MESSAGE)
    return raw_template.replace("{name}", user_name)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return

    if update.effective_chat:
        clear_user_pending_states(update.effective_chat.id, user.id)

    if not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    welcome_text = await build_welcome_text(user)
    markup = main_menu_keyboard(is_admin=(user.id == OWNER_ID))

    if update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.message.edit_text(
                welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
            )
            return
        except Exception:
            try:
                await update.callback_query.message.edit_text(
                    welcome_text, reply_markup=markup
                )
                return
            except Exception:
                pass

    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
            )
        except Exception:
            await update.effective_message.reply_text(welcome_text, reply_markup=markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    help_text = (
        "ℹ️ <b>دليل استخدام البوت والأوامر المتاحة:</b>\n\n"
        "1️⃣ <b>تحميل الفيديو أو الصور تلقائياً:</b>\n"
        "أرسل أي رابط من يوتيوب، تيك توك، إنستجرام، فيسبوك، بنترست، X، أو أي موقع — والبوت يحمّله فوراً بأعلى جودة.\n\n"
        "2️⃣ <b>ترشيح فيديوهات بالذكاء الاصطناعي (AI):</b>\n"
        "اضغط على زر <code>🤖 ترشيح فيديوهات بالذكاء الاصطناعي</code> أو اكتب:\n"
        "<code>/ai عايز فيديو ممتع عن الفضاء</code>\n\n"
        "3️⃣ <b>سحب الصور من أي صفحة ويب:</b>\n"
        "<code>/img https://...</code>\n\n"
        "4️⃣ <b>تحميل الصوت (MP3) مباشرة:</b>\n"
        "<code>/audio https://...</code>\n\n"
        "📌 <b>الأوامر السريعة:</b>\n"
        "• /start — القائمة الرئيسية\n"
        "• /ai — ترشيح فيديوهات بالذكاء الاصطناعي\n"
        "• /audio — استخراج الصوت MP3\n"
        "• /img — سحب الصور من أي رابط\n"
        "• /help — تعليمات الاستخدام\n"
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
    user = update.effective_user
    if user and not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    url = extract_media_url(" ".join(context.args or []))
    if not url:
        if update.effective_message:
            await update.effective_message.reply_text(
                "🎵 <b>الاستخدام الصحيح:</b>\n<code>/audio https://...</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("menu_home"),
            )
        return
    await send_downloaded_media(
        update.effective_message, context, url, mode="audio", request_user=user
    )


async def img_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    url = extract_media_url(" ".join(context.args or []))
    if not url:
        if update.effective_message:
            await update.effective_message.reply_text(
                "🖼️ <b>سحب الصور من أي موقع:</b>\n<code>/img https://...</code>\n\n"
                "أو أرسل رابط الصورة/الألبوم مباشرة في المحادثة!",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("menu_home"),
            )
        return
    await send_downloaded_media(
        update.effective_message, context, url, mode="image", request_user=user
    )


# ═══════════════════════════════════════════════════════════════════════
# 🤖 معالجات الذكاء الاصطناعي لترشيح الفيديوهات (AI Recommender UI)
# ═══════════════════════════════════════════════════════════════════════


async def send_ai_recommendations(
    target_message: Any,
    *,
    category: str | None = None,
    custom_prompt: str | None = None,
    edit_existing: bool = False,
) -> None:
    """جلب ترشيحات فيديوهات حقيقية وعرضها مع أزرار تحميل فيديو/MP3 فورية."""
    wait_text = "🤖 <b>الذكاء الاصطناعي يختار لك أفضل الفيديوهات الآن...</b> ⚡"
    status_msg = target_message

    if edit_existing:
        try:
            await target_message.edit_text(wait_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    else:
        status_msg = await target_message.reply_text(wait_text, parse_mode=ParseMode.HTML)

    try:
        intro, videos = await asyncio.wait_for(
            asyncio.to_thread(
                AIVideoRecommender.recommend,
                category=category,
                custom_prompt=custom_prompt,
            ),
            timeout=30,
        )
    except Exception as exc:
        logger.warning("AI recommend error: %s", exc)
        intro, videos = "", []

    if not videos:
        err_text = (
            "⚠️ <b>لم أتمكن من إيجاد ترشيحات الآن، جرب تصنيفاً آخر أو اكتب طلباً مختلفاً.</b>"
        )
        await status_msg.edit_text(
            err_text, parse_mode=ParseMode.HTML, reply_markup=ai_menu_keyboard()
        )
        return

    lines = [intro, ""]
    buttons: list[list[InlineKeyboardButton]] = []

    for idx, v in enumerate(videos, start=1):
        s_key = secrets.token_urlsafe(7)
        media_sessions[s_key] = {
            "url": v["url"],
            "type": "ai_rec",
            "title": v["title"],
        }
        _prune_store(media_sessions)

        lines.append(
            f"<b>{idx}. {html.escape(v['title'])}</b>\n"
            f"   👤 {html.escape(v['channel'])}  |  ⏱️ <code>{html.escape(v['duration'])}</code>"
        )
        buttons.append(
            [
                make_btn(f"🎬 تحميل فيديو #{idx}", callback_data=f"ai_dlv_{s_key}", style="primary"),
                make_btn(f"🎵 صوت #{idx}", callback_data=f"ai_dla_{s_key}", style="success"),
            ]
        )

    lines.append("\n👇 <i>اضغط على أي زر لتحميل الفيديو أو الصوت فوراً:</i>")

    refresh_cb = f"ai_cat_{category}" if category else "ai_custom"
    refresh_label = "🔄 رشّح لي فيديوهات أخرى" if category else "✍️ طلب ترشيح جديد (AI)"
    buttons.append([make_btn(refresh_label, callback_data=refresh_cb, style="success")])
    buttons.append(
        [
            make_btn("⬅️ قائمة الذكاء الاصطناعي", callback_data="ai_menu"),
            make_btn("🏠 الرئيسية", callback_data="menu_home"),
        ]
    )

    await status_msg.edit_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أمر /ai لفتح قائمة الذكاء الاصطناعي أو البحث الفوري."""
    user = update.effective_user
    if user and not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    prompt = " ".join(context.args or []).strip()
    if prompt and update.effective_message:
        await send_ai_recommendations(update.effective_message, custom_prompt=prompt)
        return

    if update.effective_message:
        await update.effective_message.reply_text(
            "🤖 <b>مساعد الذكاء الاصطناعي لترشيح الفيديوهات:</b>\n\n"
            "اختر تصنيفاً من الأزرار بالأسفل أو اضغط «✍️ اكتب طلبك بحرية» "
            "وسأرشح لك أفضل الفيديوهات لتحميلها بضغطة زر!",
            parse_mode=ParseMode.HTML,
            reply_markup=ai_menu_keyboard(),
        )


async def ai_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أزرار الذكاء الاصطناعي والتحميل الفوري للفيديوهات المرشّحة."""
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return

    user = query.from_user
    if not await check_user_subscription(user.id, context):
        await query.answer("⚠️ يرجى الاشتراك في القناة أولاً!", show_alert=True)
        await send_force_sub_prompt(update)
        return

    data = query.data or ""

    if data == "ai_menu":
        await query.answer()
        ai_custom_pending.discard(user.id)
        await query.message.edit_text(
            "🤖 <b>مساعد الذكاء الاصطناعي لترشيح الفيديوهات:</b>\n\n"
            "اختر نوع الفيديوهات التي تناسب مزاجك الآن، أو اكتب ما تريد مشاهدته "
            "وسأجلب لك أفضل الترشيحات جاهزة للتحميل الفوري (فيديو أو MP3):",
            parse_mode=ParseMode.HTML,
            reply_markup=ai_menu_keyboard(),
        )
        return

    if data == "ai_custom":
        await query.answer()
        ai_custom_pending.add(user.id)
        await query.message.edit_text(
            "✍️ <b>اكتب طلبك أو مزاجك للذكاء الاصطناعي الآن:</b>\n\n"
            "💡 <i>أمثلة:</i>\n"
            "• «عايز فيديو قصير وممتع عن تاريخ مصر»\n"
            "• «ملخص فيلم غموض جامد»\n"
            "• «تلاوة هادئة قبل النوم»\n"
            "• «أجمل أهداف ريال مدريد»\n\n"
            "👇 <i>أرسل رسالتك الآن:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("ai_menu"),
        )
        return

    if data.startswith("ai_cat_"):
        cat = data.removeprefix("ai_cat_")
        await query.answer("🤖 جاري تجهيز الترشيحات...")
        await send_ai_recommendations(query.message, category=cat, edit_existing=True)
        return

    if data.startswith("ai_dlv_") or data.startswith("ai_dla_"):
        mode = "audio" if data.startswith("ai_dla_") else "video"
        s_key = data[7:]
        session = media_sessions.get(s_key)
        if not session or not session.get("url"):
            await query.answer(
                "⚠️ انتهت صلاحية هذا الترشيح، اضغط تحديث للحصول على ترشيحات جديدة.",
                show_alert=True,
            )
            return
        await query.answer("⚡ جاري التحميل الفوري...")
        await send_downloaded_media(
            query.message,
            context,
            session["url"],
            mode=mode,
            request_user=user,
        )
        return


# ═══════════════════════════════════════════════════════════════════════
# 🔘 معالجات أزرار القوائم والوسائط
# ═══════════════════════════════════════════════════════════════════════


async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None:
        return

    if await check_user_subscription(query.from_user.id, context):
        await query.answer("🎉 شكراً لاشتراكك! تم تفعيل البوت بنجاح.", show_alert=True)
        await start_command(update, context)
    else:
        await query.answer(
            f"⚠️ لم تشترك بعد! اشترك أولاً في {FORCE_SUB_CHANNEL_USERNAME} ثم اضغط تحقق.",
            show_alert=True,
        )


async def user_menu_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return

    user = query.from_user
    data = query.data or ""

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
            "🚀 <b>البوت جاهز الآن بأقصى سرعة (Turbo Mode)!</b>\n\n"
            "📥 <b>أرسل أي رابط مباشرة في المحادثة:</b>\n"
            "• 🎥 روابط فيديو (YouTube، TikTok، Reels، Facebook، X، Snapchat...)\n"
            "• 🖼️ روابط صور وألبومات (Instagram، Pinterest، X، TikTok، Reddit، أو أي موقع!)\n"
            "• 📋 روابط قوائم تشغيل يوتيوب (Playlists)\n\n"
            "✨ <i>ولسحب الصور من أي صفحة ويب استخدم:</i> <code>/img الرابط</code>"
        )
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=back_and_home_keyboard("menu_home")
        )
        return

    if data == "menu_account":
        user_info = await db.get_user(user.id)
        dl_count = user_info["downloads"] if user_info else 0
        joined = user_info["joined"] if user_info else "اليوم"
        uname = f"@{user.username}" if user.username else "لا يوجد"
        text = (
            "👤 <b>الملف الشخصي وإحصائياتك:</b>\n\n"
            f"🏷️ <b>الاسم:</b> {html.escape(user.full_name)}\n"
            f"🆔 <b>المعرف (ID):</b> <code>{user.id}</code>\n"
            f"🔗 <b>اليوزر:</b> {html.escape(uname)}\n"
            f"📅 <b>تاريخ الانضمام:</b> <code>{joined}</code>\n"
            f"📥 <b>إجمالي تحميلاتك الناجحة:</b> <b>{dl_count}</b> ملف\n"
            "✅ <b>حالة الحساب:</b> نشط ومشترك"
        )
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=back_and_home_keyboard("menu_home")
        )
        return

    if data == "menu_platforms":
        text = (
            "🌐 <b>المنصات والمواقع المدعومة (فيديو + صوت + صور):</b>\n\n"
            "• 🔴 <b>YouTube</b> (فيديوهات، Shorts، قوائم تشغيل، صوت MP3)\n"
            "• ⚫ <b>TikTok</b> (فيديوهات بدون علامة مائية + ألبومات الصور)\n"
            "• 🟣 <b>Instagram</b> (Reels، منشورات فيديو، ألبومات وصور)\n"
            "• 🔵 <b>Facebook</b> (فيديوهات عامة، Reels، Watch، صور)\n"
            "• ⚫ <b>X / Twitter</b> (فيديوهات، صور، GIF)\n"
            "• 🔴 <b>Pinterest</b> (فيديوهات وصور عالية الدقة)\n"
            "• 🟡 <b>Snapchat</b> & ⚫ <b>Threads</b> & 🟠 <b>Reddit</b> & 🟠 <b>Likee</b>\n"
            "• 🌍 <b>أي موقع ويب آخر:</b> +1000 موقع فيديو و +300 موقع صور!"
        )
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=back_and_home_keyboard("menu_home")
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
            text, parse_mode=ParseMode.HTML, reply_markup=back_and_home_keyboard("menu_home")
        )
        return


async def media_action_callbacks(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
        await query.answer("🎵 جاري استخراج الصوت (MP3)...")
        await send_downloaded_media(
            query.message, context, session["url"], mode="audio", request_user=user, skip_archive=True
        )
        return

    if action == "hdimg":
        await query.answer("📂 جاري إرسال الصورة الأصلية بدون ضغط...")
        await send_downloaded_media(
            query.message, context, session["url"], mode="image_hd", request_user=user, skip_archive=True
        )
        return

    if action == "vinfo":
        await query.answer()
        details_text = UniversalMediaEngine.build_technical_details_text(
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
            "أرسل الاسم الجديد الآن (بالعربية أو الإنجليزية)، وسأضيف <code>.mp3</code> تلقائياً.",
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
# 🔐 لوحة تحكم الأدمن المتكاملة + الأرشيف الرقابي (Admin Panel PRO V2)
# ═══════════════════════════════════════════════════════════════════════


def is_user_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id == OWNER_ID


async def build_admin_dashboard_text() -> tuple[str, int, int]:
    stats = await db.get_stats_summary()
    force_sub = await db.get_setting("force_sub_enabled", "1")
    sub_status = "🟢 مفعل" if force_sub == "1" else "🔴 معطل"

    text = (
        "🔐 <b>لوحة تحكم الإدارة الشاملة PRO V2</b>\n\n"
        f"👥 <b>إجمالي المستخدمين:</b> <code>{stats['total_users']}</code>  |  ✅ <b>النشطون:</b> <code>{stats['active_users']}</code>\n"
        f"🚫 <b>المحظورون / الموقوفون:</b> <code>{stats['banned_users']} / {stats['stopped_users']}</code>\n"
        f"📥 <b>إجمالي التحميلات:</b> <code>{stats['total_downloads']}</code>  |  🗂️ <b>الأرشيف:</b> <code>{stats['archive_count']}</code> رابط\n"
        f"📅 <b>اليوم:</b> <code>{stats['today_messages']}</code> رسالة  |  <code>{stats['today_downloads']}</code> تحميل\n"
        f"📩 <b>رسائل دعم جديدة:</b> <code>{stats['unreplied_msgs']}</code>\n"
        f"📢 <b>الاشتراك الإجباري ({FORCE_SUB_CHANNEL_USERNAME}):</b> {sub_status}\n\n"
        "👇 <i>اختر القسم الذي تريد إدارته:</i>"
    )
    return text, stats["unreplied_msgs"], stats["archive_count"]


async def render_admin_archive(
    query: Any, page: int = 0, filter_uid: int | None = None
) -> None:
    """عرض أرشيف الروابط للأدمن لمراجعة المواقع وحظر المخالفين."""
    total = await db.count_archive(user_id=filter_uid)
    if total == 0:
        back_cb = f"adm_user_{filter_uid}" if filter_uid else "adm_main"
        await query.message.edit_text(
            "🗂️ <b>الأرشيف فارغ حالياً — لم يتم تسجيل أي روابط بعد.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard(back_cb),
        )
        return

    total_pages = max(1, (total + ARCHIVE_PER_PAGE - 1) // ARCHIVE_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    entries = await db.get_archive_entries(
        limit=ARCHIVE_PER_PAGE, offset=page * ARCHIVE_PER_PAGE, user_id=filter_uid
    )

    header = (
        f"🗂️ <b>أرشيف روابط المستخدم <code>{filter_uid}</code> ({total} رابط)</b>"
        if filter_uid
        else f"🗂️ <b>أرشيف جميع الروابط المرسلة للبوت ({total} رابط)</b>"
    )
    lines = [
        f"{header} — صفحة <b>{page + 1}/{total_pages}</b>\n",
        "<i>اضغط على أي سجل لمراجعة الرابط الكامل أو حظر صاحبه فوراً:</i>\n",
    ]
    buttons: list[list[InlineKeyboardButton]] = []

    for e in entries:
        short_domain = (urlparse(e["url"]).hostname or e["platform"] or "موقع").replace("www.", "")[:18]
        short_name = (e["user_name"] or str(e["user_id"]))[:14]
        status_icon = "✅" if "✅" in e["status"] else ("❌" if "❌" in e["status"] else "⏳")
        lines.append(
            f"• <b>#{e['id']}</b> {status_icon} <b>{html.escape(short_name)}</b> (<code>{e['user_id']}</code>) "
            f"— <code>{html.escape(short_domain)}</code> <i>({e['created_at']})</i>"
        )
        buttons.append(
            [
                make_btn(
                    f"🔎 #{e['id']} | {short_name} — {short_domain}",
                    callback_data=f"adm_archview_{e['id']}",
                )
            ]
        )

    nav: list[InlineKeyboardButton] = []
    prefix = f"adm_archuser_{filter_uid}_" if filter_uid else "adm_arch_"
    if page > 0:
        nav.append(make_btn("⬅️ السابق", callback_data=f"{prefix}{page - 1}"))
    nav.append(make_btn(f"📄 {page + 1}/{total_pages}", callback_data="adm_noop"))
    if page + 1 < total_pages:
        nav.append(make_btn("التالي ➡️", callback_data=f"{prefix}{page + 1}"))
    buttons.append(nav)

    if not filter_uid:
        buttons.append(
            [
                make_btn("📄 تصدير الأرشيف (.txt)", callback_data="adm_archexport", style="success"),
                make_btn("🗑️ مسح الأرشيف", callback_data="adm_archclear", style="danger"),
            ]
        )
        buttons.append(
            [
                make_btn("⬅️ رجوع للوحة", callback_data="adm_main"),
                make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"),
            ]
        )
    else:
        buttons.append(
            [
                make_btn("⬅️ رجوع لملف المستخدم", callback_data=f"adm_user_{filter_uid}"),
                make_btn("🗂️ الأرشيف الكامل", callback_data="adm_arch_0", style="primary"),
            ]
        )

    await query.message.edit_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


async def render_admin_settings(query: Any) -> None:
    force_sub = await db.get_setting("force_sub_enabled", "1")
    is_on = force_sub == "1"
    current_welcome = await db.get_setting("welcome_message", DEFAULT_WELCOME_MESSAGE)
    text = (
        "⚙️ <b>إعدادات البوت ورسالة الترحيب:</b>\n\n"
        f"📢 <b>قناة الاشتراك الإجباري:</b> <a href='{FORCE_SUB_CHANNEL_URL}'>{FORCE_SUB_CHANNEL_USERNAME}</a>\n"
        f"📌 <b>حالة الاشتراك الإجباري:</b> {'🟢 مفعل' if is_on else '🔴 معطل'}\n\n"
        "💬 <b>رسالة الترحيب الحالية:</b>\n"
        f"<blockquote>{html.escape(current_welcome[:500])}</blockquote>\n"
        "<i>ملاحظة: الكلمة <code>{name}</code> تُستبدل تلقائياً باسم المستخدم.</i>"
    )
    markup = InlineKeyboardMarkup(
        [
            [make_btn("✏️ تعديل رسالة الترحيب", callback_data="adm_edit_welcome", style="primary")],
            [make_btn("🔄 استعادة الترحيب الافتراضي", callback_data="adm_reset_welcome")],
            [
                make_btn(
                    "🔴 تعطيل الاشتراك الإجباري" if is_on else "🟢 تفعيل الاشتراك الإجباري",
                    callback_data="adm_toggle_forcesub",
                    style="danger" if is_on else "success",
                )
            ],
            [
                make_btn("⬅️ رجوع", callback_data="adm_main"),
                make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"),
            ],
        ]
    )
    await query.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )


async def render_admin_cookies(query: Any) -> None:
    rows = await db.get_all_cookies()
    lines = (
        "\n".join(
            f"• 🍪 <b>{html.escape(r[0].capitalize())}</b> — <i>آخر تحديث: {r[1]}</i>"
            for r in rows
        )
        or "لا توجد ملفات كوكيز مرفوعة حالياً."
    )
    buttons = [
        [make_btn("➕ إضافة / تحديث كوكيز منصة", callback_data="adm_cookie_add", style="success")]
    ]
    if rows:
        buttons.append(
            [make_btn("🗑️ حذف كوكيز منصة", callback_data="adm_cookie_del", style="danger")]
        )
    buttons.append(
        [
            make_btn("⬅️ رجوع", callback_data="adm_main"),
            make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"),
        ]
    )
    await query.message.edit_text(
        f"🍪 <b>إدارة كوكيز المنصات (Netscape TXT):</b>\n\n{lines}\n\n"
        "💡 <i>نصيحة: صدّر كوكيز يوتيوب وإنستجرام من نافذة المتخفي (Incognito) "
        "بإضافة <b>Get cookies.txt LOCALLY</b> ثم أغلق النافذة فوراً.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    text, unreplied, arch_count = await build_admin_dashboard_text()
    markup = admin_main_keyboard(unreplied, arch_count)

    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def show_admin_user_profile(query: Any, uid: int) -> None:
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
    status = "🚫 محظور" if user["banned"] else ("🔇 موقوف سرياً" if user["stopped"] else "🟢 نشط")
    user_links_count = await db.count_archive(user_id=uid)

    text = (
        f"👤 <b>إدارة المستخدم: {html.escape(full)}</b>\n\n"
        f"🆔 <b>المعرف (ID):</b> <code>{uid}</code>\n"
        f"🔗 <b>اليوزر:</b> {html.escape(uname)}\n"
        f"📅 <b>تاريخ الانضمام:</b> <code>{user['joined'] or '—'}</code>\n"
        f"📥 <b>التحميلات الناجحة:</b> <b>{user['downloads']}</b>\n"
        f"🗂️ <b>روابطه في الأرشيف:</b> <b>{user_links_count}</b>\n"
        f"📌 <b>الحالة الحالية:</b> <b>{status}</b>"
    )

    ban_btn = (
        make_btn("🟢 فك الحظر", callback_data=f"adm_unban_{uid}", style="success")
        if user["banned"]
        else make_btn("🔴 حظر المستخدم", callback_data=f"adm_ban_{uid}", style="danger")
    )
    stop_btn = (
        make_btn("🔊 إلغاء الإيقاف السري", callback_data=f"adm_resume_{uid}", style="success")
        if user["stopped"]
        else make_btn("🔇 إيقاف سري", callback_data=f"adm_stop_{uid}", style="danger")
    )

    markup = InlineKeyboardMarkup(
        [
            [ban_btn, stop_btn],
            [
                make_btn("🗂️ روابط هذا المستخدم", callback_data=f"adm_archuser_{uid}_0", style="primary"),
                make_btn("✉️ رسالة خاصة", callback_data=f"adm_msg_{uid}", style="success"),
            ],
            [
                make_btn("⬅️ رجوع للمستخدمين", callback_data="adm_users_0"),
                make_btn("🏠 الرئيسية", callback_data="menu_home"),
            ],
        ]
    )
    await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        text, unreplied, arch_count = await build_admin_dashboard_text()
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_main_keyboard(unreplied, arch_count),
        )
        return

    # ── فحص النظام ──
    if data == "adm_health":
        await query.answer("🩺 جاري فحص أدوات السيرفر...")
        markup = InlineKeyboardMarkup(
            [
                [make_btn("🔄 إعادة الفحص", callback_data="adm_health", style="success")],
                [
                    make_btn("⬅️ رجوع", callback_data="adm_main"),
                    make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"),
                ],
            ]
        )
        await query.message.edit_text(
            get_system_health_report(), parse_mode=ParseMode.HTML, reply_markup=markup
        )
        return

    # ── الأرشيف الرقابي (Archive) ──
    if data.startswith("adm_arch_"):
        await query.answer()
        page = int(data.removeprefix("adm_arch_"))
        await render_admin_archive(query, page=page)
        return

    if data.startswith("adm_archuser_"):
        await query.answer()
        parts = data.removeprefix("adm_archuser_").split("_")
        uid, page = int(parts[0]), int(parts[1])
        await render_admin_archive(query, page=page, filter_uid=uid)
        return

    if data.startswith("adm_archview_"):
        await query.answer()
        entry_id = int(data.removeprefix("adm_archview_"))
        e = await db.get_archive_entry_by_id(entry_id)
        if not e:
            await query.message.edit_text(
                "⚠️ <b>هذا السجل غير موجود أو تم حذفه.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_arch_0"),
            )
            return

        uname = f"@{e['username']}" if e["username"] else "لا يوجد"
        target_user = await db.get_user(e["user_id"])
        is_banned_now = target_user["banned"] if target_user else False
        ban_btn = (
            make_btn("🟢 فك حظر هذا المستخدم", callback_data=f"adm_unban_{e['user_id']}", style="success")
            if is_banned_now
            else make_btn("🔴 حظر هذا المستخدم فوراً", callback_data=f"adm_ban_{e['user_id']}", style="danger")
        )

        text = (
            f"🗂️ <b>تفاصيل السجل #{e['id']} في الأرشيف:</b>\n\n"
            f"👤 <b>المستخدم:</b> {html.escape(e['user_name'])}\n"
            f"🆔 <b>المعرف (ID):</b> <code>{e['user_id']}</code>\n"
            f"🔗 <b>اليوزر:</b> {html.escape(uname)}\n"
            f"🌐 <b>المنصة / الموقع:</b> <code>{html.escape(e['platform'])}</code>\n"
            f"📌 <b>الحالة:</b> {html.escape(e['status'])}\n"
            f"🕒 <b>الوقت:</b> <code>{e['created_at']}</code>\n\n"
            f"🔗 <b>الرابط الكامل للمراجعة:</b>\n<code>{html.escape(e['url'])}</code>"
        )
        markup = InlineKeyboardMarkup(
            [
                [ban_btn],
                [
                    make_btn("👤 ملف المستخدم", callback_data=f"adm_user_{e['user_id']}", style="primary"),
                    make_btn("🗑️ حذف السجل", callback_data=f"adm_archdel_{e['id']}", style="danger"),
                ],
                [
                    make_btn("⬅️ رجوع للأرشيف", callback_data="adm_arch_0"),
                    make_btn("🏠 الرئيسية", callback_data="menu_home"),
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

    if data.startswith("adm_archdel_"):
        entry_id = int(data.removeprefix("adm_archdel_"))
        await db.delete_archive_entry(entry_id)
        await query.answer("🗑️ تم حذف السجل من الأرشيف")
        await render_admin_archive(query, page=0)
        return

    if data == "adm_archexport":
        await query.answer("📄 جاري تجهيز ملف الأرشيف...")
        txt_content = await db.export_archive_text()
        fd, tmp_name = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            tmp_path.write_text(txt_content, encoding="utf-8")
            fname = f"archive_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            with open(tmp_path, "rb") as fh:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=fh,
                    filename=fname,
                    caption="🗂️ <b>تقرير أرشيف الروابط الكامل للمراجعة</b>",
                    parse_mode=ParseMode.HTML,
                )
        finally:
            tmp_path.unlink(missing_ok=True)
        return

    if data == "adm_archclear":
        await query.answer()
        markup = InlineKeyboardMarkup(
            [
                [make_btn("⚠️ نعم، امسح الأرشيف بالكامل", callback_data="adm_archclear_yes", style="danger")],
                [make_btn("⬅️ تراجع", callback_data="adm_arch_0", style="success")],
            ]
        )
        await query.message.edit_text(
            "⚠️ <b>تأكيد مسح الأرشيف:</b>\nهل أنت متأكد أنك تريد حذف جميع السجلات المحفوظة في الأرشيف؟",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    if data == "adm_archclear_yes":
        deleted = await db.clear_archive()
        await query.answer(f"🗑️ تم مسح {deleted} سجل من الأرشيف", show_alert=True)
        await render_admin_archive(query, page=0)
        return

    # ── الإحصائيات التفصيلية ──
    if data == "adm_stats":
        await query.answer("📊 تم تحديث الإحصائيات")
        stats = await db.get_stats_summary()
        cookies_rows = await db.get_all_cookies()
        text = (
            "📊 <b>تقرير إحصائيات البوت التفصيلي:</b>\n\n"
            f"👥 <b>إجمالي المسجلين:</b> <code>{stats['total_users']}</code> مستخدم\n"
            f"🟢 <b>المستخدمون النشطون:</b> <code>{stats['active_users']}</code> مستخدم\n"
            f"🔴 <b>المحظورون:</b> <code>{stats['banned_users']}</code>  |  🔇 <b>الموقوفون:</b> <code>{stats['stopped_users']}</code>\n\n"
            f"📈 <b>النشاط اليومي ({datetime.now().strftime('%Y-%m-%d')}):</b>\n"
            f"• 💬 الرسائل اليومية: <code>{stats['today_messages']}</code> رسالة\n"
            f"• 📥 التحميلات اليوم: <code>{stats['today_downloads']}</code> عملية\n\n"
            f"🏆 <b>الإحصائيات الكلية:</b>\n"
            f"• 📥 إجمالي التحميلات الناجحة: <code>{stats['total_downloads']}</code> ملف\n"
            f"• 🗂️ إجمالي الروابط في الأرشيف: <code>{stats['archive_count']}</code> رابط\n"
            f"• 📩 رسائل دعم غير مقروءة: <code>{stats['unreplied_msgs']}</code> رسالة\n"
            f"• 🍪 منصات مضاف لها كوكيز: <code>{len(cookies_rows)}</code> منصة\n"
            f"• ⚡ روابط مخزنة في الكاش السريع: <code>{len(url_file_id_cache)}</code>"
        )
        markup = InlineKeyboardMarkup(
            [
                [make_btn("🔄 تحديث الأرقام", callback_data="adm_stats", style="primary")],
                [
                    make_btn("⬅️ رجوع", callback_data="adm_main"),
                    make_btn("🏠 الرئيسية", callback_data="menu_home"),
                ],
            ]
        )
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    # ── قائمة المستخدمين ──
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
            row.append(make_btn(f"{status_icon} {name}", callback_data=f"adm_user_{u['id']}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(make_btn("⬅️ السابق", callback_data=f"adm_users_{page - 1}"))
        nav.append(make_btn(f"📄 {page + 1}/{total_pages}", callback_data="adm_noop"))
        if start_idx + USERS_PER_PAGE < total:
            nav.append(make_btn("التالي ➡️", callback_data=f"adm_users_{page + 1}"))
        buttons.append(nav)
        buttons.append([make_btn("🔍 بحث / حظر بالـ ID", callback_data="adm_search_user", style="danger")])
        buttons.append(
            [
                make_btn("⬅️ رجوع", callback_data="adm_main"),
                make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"),
            ]
        )

        await query.message.edit_text(
            f"👥 <b>إدارة المستخدمين ({total} مستخدم) — صفحة {page + 1} من {total_pages}:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data == "adm_search_user":
        await query.answer()
        admin_search_user_pending.add(OWNER_ID)
        await query.message.edit_text(
            "🔍 <b>البحث عن مستخدم أو حظره بالـ ID:</b>\n\n"
            "أرسل الآن <b>الـ ID الخاص بالمستخدم</b> (أرقام فقط):",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_main"),
        )
        return

    if data.startswith("adm_user_"):
        await query.answer()
        await show_admin_user_profile(query, int(data.split("_")[-1]))
        return

    if data.startswith("adm_ban_"):
        uid = int(data.split("_")[-1])
        await db.set_ban(uid, True)
        await query.answer("🔴 تم حظر المستخدم")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_unban_"):
        uid = int(data.split("_")[-1])
        await db.set_ban(uid, False)
        await query.answer("🟢 تم فك الحظر")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_stop_"):
        uid = int(data.split("_")[-1])
        await db.set_stop(uid, True)
        await query.answer("🔇 تم الإيقاف السري")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_resume_"):
        uid = int(data.split("_")[-1])
        await db.set_stop(uid, False)
        await query.answer("🔊 تم استئناف الحساب")
        await show_admin_user_profile(query, uid)
        return

    if data.startswith("adm_msg_"):
        uid = int(data.split("_")[-1])
        admin_send_msg_pending[OWNER_ID] = uid
        await query.answer()
        await query.message.edit_text(
            f"✉️ <b>إرسال رسالة خاصة للمستخدم <code>{uid}</code>:</b>\n"
            "أرسل الرسالة الآن (نص، صورة، فيديو، صوت...):",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard(f"adm_user_{uid}"),
        )
        return

    if data == "adm_broadcast":
        await query.answer()
        admin_broadcast_pending.add(OWNER_ID)
        stats = await db.get_stats_summary()
        await query.message.edit_text(
            f"📢 <b>بث رسالة جماعية (Broadcast):</b>\n\n"
            f"سيتم إرسال رسالتك إلى <b>{stats['active_users']}</b> مستخدم نشط.\n"
            "أرسل الرسالة الآن (نص، صورة، فيديو، ملف صوتي...):",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_main"),
        )
        return

    # ── الإعدادات ──
    if data == "adm_settings":
        await query.answer()
        await render_admin_settings(query)
        return

    if data == "adm_edit_welcome":
        await query.answer()
        admin_welcome_edit_pending.add(OWNER_ID)
        await query.message.edit_text(
            "✏️ <b>تعديل رسالة الترحيب:</b>\n\n"
            "أرسل الآن نص رسالة الترحيب الجديدة.\n"
            "💡 <i>اكتب <code>{name}</code> في المكان الذي تريد وضع اسم المستخدم فيه تلقائياً.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_settings"),
        )
        return

    if data == "adm_reset_welcome":
        await db.set_setting("welcome_message", DEFAULT_WELCOME_MESSAGE)
        await query.answer("✅ تمت استعادة رسالة الترحيب الافتراضية", show_alert=True)
        await render_admin_settings(query)
        return

    if data == "adm_toggle_forcesub":
        curr = await db.get_setting("force_sub_enabled", "1")
        new_val = "0" if curr == "1" else "1"
        await db.set_setting("force_sub_enabled", new_val)
        await query.answer(
            "🟢 تم تفعيل الاشتراك الإجباري" if new_val == "1" else "🔴 تم تعطيل الاشتراك الإجباري"
        )
        await render_admin_settings(query)
        return

    # ── رسائل الدعم ──
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

        buttons = []
        for m in page_msgs:
            icon = "✅" if m["is_replied"] else "🆕"
            sender = (m["user_name"] or str(m["user_id"]))[:15]
            preview = m["text"][:20].replace("\n", " ")
            buttons.append(
                [make_btn(f"{icon} {sender}: {preview}...", callback_data=f"adm_viewmsg_{m['id']}")]
            )

        nav = []
        if page > 0:
            nav.append(make_btn("⬅️ السابق", callback_data=f"adm_msgs_{page - 1}"))
        nav.append(make_btn(f"📄 {page + 1}/{total_pages}", callback_data="adm_noop"))
        if start_idx + MESSAGES_PER_PAGE < total:
            nav.append(make_btn("التالي ➡️", callback_data=f"adm_msgs_{page + 1}"))
        buttons.append(nav)
        buttons.append(
            [
                make_btn("⬅️ رجوع", callback_data="adm_main"),
                make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"),
            ]
        )

        await query.message.edit_text(
            f"📩 <b>رسائل المستخدمين ({total} رسالة) — صفحة {page + 1} من {total_pages}:</b>",
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
                [make_btn("↩️ الرد على هذه الرسالة", callback_data=f"adm_replymsg_{m['id']}", style="success")],
                [make_btn("👤 فتح ملف المستخدم", callback_data=f"adm_user_{m['user_id']}", style="primary")],
                [
                    make_btn("⬅️ رجوع للرسائل", callback_data="adm_msgs_0"),
                    make_btn("🏠 الرئيسية", callback_data="menu_home"),
                ],
            ]
        )
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
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
            f"↩️ <b>الرد على {html.escape(m['user_name'])} (<code>{m['user_id']}</code>):</b>\n\n"
            f"<b>رسالته:</b> <i>{html.escape(m['text'][:200])}</i>\n\n"
            "✍️ أرسل نص الرد الآن وسيصل للمستخدم فوراً:",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard(f"adm_viewmsg_{msg_id}"),
        )
        return

    # ── إدارة الكوكيز ──
    if data == "adm_cookies":
        await query.answer()
        await render_admin_cookies(query)
        return

    if data == "adm_cookie_add":
        await query.answer()
        buttons = []
        row = []
        for display_name, platform_key in SUPPORTED_PLATFORMS_BUTTONS:
            row.append(make_btn(display_name, callback_data=f"adm_cookie_plat_{platform_key}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append(
            [
                make_btn("⬅️ رجوع", callback_data="adm_cookies"),
                make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary"),
            ]
        )
        await query.message.edit_text(
            "🍪 <b>اختر المنصة التي تريد رفع ملف الكوكيز (.txt) لها:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data == "adm_cookie_del":
        await query.answer()
        rows = await db.get_all_cookies()
        if not rows:
            await render_admin_cookies(query)
            return
        buttons = [
            [
                make_btn(
                    f"🗑️ حذف كوكيز {r[0].capitalize()}",
                    callback_data=f"adm_cookie_rm_{r[0]}",
                    style="danger",
                )
            ]
            for r in rows
        ]
        buttons.append([make_btn("⬅️ رجوع", callback_data="adm_cookies")])
        await query.message.edit_text(
            "🗑️ <b>اختر المنصة التي تريد حذف ملف الكوكيز الخاص بها:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("adm_cookie_rm_"):
        plat = data.removeprefix("adm_cookie_rm_")
        await db.delete_cookie(plat)
        await query.answer(f"🗑️ تم حذف كوكيز {plat.capitalize()}", show_alert=True)
        await render_admin_cookies(query)
        return

    if data.startswith("adm_cookie_plat_"):
        await query.answer()
        platform_key = data.removeprefix("adm_cookie_plat_")
        admin_cookie_selected_platform[OWNER_ID] = platform_key
        await query.message.edit_text(
            f"🍪 <b>رفع كوكيز لمنصة: {html.escape(platform_key.capitalize())}</b>\n\n"
            "📄 أرسل الآن <b>ملف الكوكيز بصيغة <code>.txt</code></b> (Netscape Cookies Format فقط):",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("adm_cookies"),
        )
        return


async def execute_broadcast(
    source_msg: Any, context: ContextTypes.DEFAULT_TYPE
) -> None:
    users = await db.get_all_users()
    targets = [
        u for u in users if not u["banned"] and not u["stopped"] and u["id"] != OWNER_ID
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
# 📥 معالجات الرسائل الواردة (الحارس العام، الكوكيز، الصور، الروابط، AI)
# ═══════════════════════════════════════════════════════════════════════


async def global_pre_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.effective_message
    if msg is None or msg.from_user is None:
        return

    user = msg.from_user
    user_id = user.id

    await db.register_or_update_user(user)
    await db.increment_daily_messages()

    if msg.text and msg.text.strip().split()[0].lower() in (
        "/start", "/admin", "/m", "/help", "/img", "/photo", "/audio", "/ai"
    ):
        return

    if is_user_admin(user_id):
        if user_id in admin_broadcast_pending:
            admin_broadcast_pending.discard(user_id)
            await execute_broadcast(msg, context)
            raise ApplicationHandlerStop

        if user_id in admin_welcome_edit_pending and msg.text:
            admin_welcome_edit_pending.discard(user_id)
            await db.set_setting("welcome_message", msg.text.strip())
            await msg.reply_text(
                "✅ <b>تم حفظ وتحديث رسالة الترحيب بنجاح!</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_settings"),
            )
            raise ApplicationHandlerStop

        if user_id in admin_search_user_pending and msg.text:
            raw_uid = msg.text.strip()
            if not raw_uid.isdigit():
                await msg.reply_text(
                    "⚠️ <b>يرجى إرسال أرقام فقط تمثل الـ ID:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard("adm_main"),
                )
                raise ApplicationHandlerStop
            admin_search_user_pending.discard(user_id)
            uid = int(raw_uid)
            u_info = await db.get_user(uid)
            if not u_info:
                await msg.reply_text(
                    f"⚠️ <b>المستخدم <code>{uid}</code> غير مسجل في قاعدة البيانات بعد.</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard("adm_main"),
                )
                raise ApplicationHandlerStop
            full = f"{u_info['first']} {u_info['last']}".strip() or "بدون اسم"
            ban_btn = (
                make_btn("🟢 فك الحظر", callback_data=f"adm_unban_{uid}", style="success")
                if u_info["banned"]
                else make_btn("🔴 حظر المستخدم", callback_data=f"adm_ban_{uid}", style="danger")
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
                            make_btn("🗂️ روابطه في الأرشيف", callback_data=f"adm_archuser_{uid}_0", style="primary"),
                            make_btn("📂 التفاصيل الكاملة", callback_data=f"adm_user_{uid}"),
                        ],
                        [make_btn("⬅️ رجوع للوحة", callback_data="adm_main")],
                    ]
                ),
            )
            raise ApplicationHandlerStop

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
                        "📩 <b>رد جديد من إدارة البوت على رسالتك:</b>\n\n"
                        f"💬 <b>رسالتك السابقة:</b>\n<blockquote>{html.escape(ticket['text'][:200])}</blockquote>\n\n"
                        f"↩️ <b>رد الإدارة:</b>\n<blockquote>{html.escape(reply_content)}</blockquote>"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [make_btn("📩 إرسال رد آخر للإدارة", callback_data="menu_contact_admin", style="success")],
                            [make_btn("🏠 الرئيسية", callback_data="menu_home", style="primary")],
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
                    f"❌ <b>فشل إرسال الرد:</b>\n<code>{html.escape(str(exc))}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_and_home_keyboard("adm_msgs_0"),
                )
            raise ApplicationHandlerStop

        if user_id in admin_send_msg_pending:
            target_id = admin_send_msg_pending.pop(user_id)
            try:
                await context.bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=msg.chat_id,
                    message_id=msg.message_id,
                )
                await msg.reply_text(
                    f"✅ <b>تم إرسال الرسالة بنجاح إلى <code>{target_id}</code>!</b>",
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

        if user_id in admin_cookie_selected_platform and msg.text:
            await msg.reply_text(
                "⚠️ <b>يرجى إرسال ملف بصيغة <code>.txt</code> وليس رسالة نصية!</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_cookies"),
            )
            raise ApplicationHandlerStop

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

        is_valid, validation_msg = validate_netscape_cookies(content)
        if not is_valid:
            admin_cookie_selected_platform[user_id] = platform
            await message.reply_text(
                f"❌ <b>ملف الكوكيز غير صالح!</b>\n\n📌 <b>السبب:</b> {html.escape(validation_msg)}",
                parse_mode=ParseMode.HTML,
                reply_markup=back_and_home_keyboard("adm_cookies"),
            )
            return

        saved_path = await db.save_cookie(platform, content)
        await message.reply_text(
            f"✅ <b>تم فحص وحفظ كوكيز {html.escape(platform.capitalize())} بنجاح!</b>\n"
            f"🔍 <b>الحالة:</b> {html.escape(validation_msg)}\n"
            f"📂 <b>المسار:</b> <code>{saved_path}</code>",
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
            "حمّل ملفاً صوتياً أولاً ثم اضغط على زر «🖼️ وضع غلاف للصوت» أسفله!",
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
            request_user=user,
            skip_archive=True,
        )
    finally:
        tmp.unlink(missing_ok=True)


async def text_and_url_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None or not message.text or message.from_user is None:
        return

    user = message.from_user
    if not await check_user_subscription(user.id, context):
        await send_force_sub_prompt(update)
        return

    pending_key = (message.chat_id, user.id)

    # 1. استلام طلب ترشيح ذكاء اصطناعي حر من المستخدم
    if user.id in ai_custom_pending:
        ai_custom_pending.discard(user.id)
        await send_ai_recommendations(message, custom_prompt=message.text.strip())
        return

    # 2. استلام رسالة دعم للأدمن
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
                        [make_btn("↩️ الرد على المستخدم الآن", callback_data=f"adm_replymsg_{ticket_id}", style="success")],
                        [make_btn("👤 ملف المستخدم", callback_data=f"adm_user_{user.id}", style="primary")],
                    ]
                ),
            )
        except Exception as notify_err:
            logger.debug("Could not notify admin: %s", notify_err)
        return

    # 3. إعادة تسمية الصوت
    pending_url = rename_pending.pop(pending_key, None)
    if pending_url:
        await send_downloaded_media(
            message,
            context,
            pending_url,
            mode="audio",
            custom_filename=clean_filename(message.text),
            request_user=user,
            skip_archive=True,
        )
        return

    # 4. وصف/مؤدي الصوت
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
                request_user=user,
                skip_archive=True,
            )
        else:
            await message.reply_text(
                "⚠️ <b>انتهت صلاحية الطلب، يرجى إرسال الرابط مجدداً.</b>",
                parse_mode=ParseMode.HTML,
            )
        return

    # 5. استخراج الرابط وتحميله فوراً بأقصى سرعة
    url = extract_media_url(message.text)
    if url:
        if is_youtube_playlist(url):
            await send_playlist(message, context, url)
        else:
            await send_downloaded_media(message, context, url, request_user=user)
    else:
        await message.reply_text(
            "🤖 <b>مرحباً بك في بوت التحميل الشامل PRO V2!</b>\n\n"
            "🔗 أرسل <b>أي رابط يبدأ بـ http أو https</b> لتحميله فوراً، "
            "أو اضغط على زر الذكاء الاصطناعي لترشيح فيديوهات ممتعة لك:",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(is_admin=(user.id == OWNER_ID)),
        )


async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()


async def unknown_command_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ <b>عذراً، هذا الأمر غير معروف!</b>\n\n"
            "الأوامر المتاحة:\n"
            "• /start — القائمة الرئيسية\n"
            "• /ai — ترشيح فيديوهات بالذكاء الاصطناعي\n"
            "• /audio — تحميل ملف صوتي\n"
            "• /img — سحب الصور من أي رابط\n"
            "• /help — تعليمات الاستخدام\n"
            "• /admin — لوحة تحكم الأدمن",
            parse_mode=ParseMode.HTML,
            reply_markup=back_and_home_keyboard("menu_home"),
        )


async def global_error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
    if not TOKEN or TOKEN == "ضع_التوكن_هنا":
        logger.error("❌ خطأ: يرجى وضع توكن البوت الصحيح في TOKEN أو متغير البيئة BOT_TOKEN!")
        sys.exit(1)

    logger.info(
        "FFmpeg: %s | JS Runtime: %s | gallery-dl: %s | Data Dir: %s",
        has_ffmpeg(),
        has_js_runtime(),
        has_gallery_dl(),
        DATA_DIR,
    )

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

    # 1. الحارس العام
    application.add_handler(MessageHandler(filters.ALL, global_pre_handler), group=-1)

    # 2. الأوامر
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("audio", audio_command))
    application.add_handler(CommandHandler(["img", "photo"], img_command))
    application.add_handler(CommandHandler("ai", ai_command))
    application.add_handler(CommandHandler(["admin", "M", "m"], admin_command))

    # 3. أزرار القوائم والذكاء الاصطناعي والاشتراك الإجباري
    application.add_handler(CallbackQueryHandler(check_sub_callback, pattern=r"^check_sub$"))
    application.add_handler(CallbackQueryHandler(user_menu_callbacks, pattern=r"^menu_"))
    application.add_handler(CallbackQueryHandler(ai_callbacks, pattern=r"^ai_"))
    application.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))

    # 4. أزرار الوسائط (فيديو، صوت، صورة HD)
    application.add_handler(
        CallbackQueryHandler(
            media_action_callbacks, pattern=r"^(audio|vinfo|rename|cover|desc|hdimg):"
        )
    )

    # 5. أزرار لوحة تحكم الأدمن والأرشيف
    application.add_handler(CallbackQueryHandler(admin_callbacks, pattern=r"^adm_"))

    # 6. الملفات، الصور، النصوص، والأوامر غير المعروفة
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

    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=10,
        )
    except Exception:
        pass

    logger.info("✅ بوت التحميل الشامل PRO V2 يعمل الآن بنجاح!")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


def main() -> None:
    restart_delay = 5
    while True:
        try:
            build_and_run_bot()
            break
        except KeyboardInterrupt:
            logger.info("🛑 تم إيقاف البوت يدوياً.")
            break
        except SystemExit:
            break
        except Exception as crash_err:
            logger.error(
                "⚠️ خطأ غير متوقع أدى لتوقف البوت: %s\n%s",
                crash_err,
                traceback.format_exc(),
            )
            logger.info("🔄 إعادة التشغيل تلقائياً خلال %d ثوانٍ...", restart_delay)
            time.sleep(restart_delay)


if __name__ == "__main__":
    main()
