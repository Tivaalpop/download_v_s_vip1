#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🎬 واجهة الويب الاحترافية بنظام تيك توك — مربوطة تلقائياً بقاعدة بيانات البوت
التثبيت: pip install -U flask yt-dlp
التشغيل: python web_app.py
"""

import os
import re
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from flask import Flask, Response, jsonify, render_template_string, request, send_file

app = Flask(__name__)

# نفس مسار قاعدة بيانات البوت
DATA_DIR = Path(os.environ.get("DATA_DIR", ".")).resolve()
DB_PATH = DATA_DIR / "bot_database.db"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Ell_Hoot")  # غيّره ليوزر بوتك بدون @


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_likes (
            video_id INTEGER PRIMARY KEY,
            likes INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    return conn


def extract_youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "youtu.be" in host:
        return parsed.path.lstrip("/").split("/")[0] or None
    if "youtube.com" in host:
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("/")[0]
        qs = parse_qs(parsed.query)
        if qs.get("v"):
            return qs["v"][0]
    return None


HTML_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>PRO Video Feed — مثل تيك توك</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }
  body { background: #000; color: #fff; overflow: hidden; height: 100dvh; width: 100vw; }

  /* الشريط العلوي الزجاجي */
  .top-bar {
    position: fixed; top: 0; left: 0; right: 0; z-index: 50;
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 16px;
    background: linear-gradient(to bottom, rgba(0,0,0,0.85), transparent);
  }
  .logo { font-size: 18px; font-weight: 800; letter-spacing: 0.5px; display: flex; align-items: center; gap: 6px; }
  .logo span { color: #fe2c55; }
  .top-actions { display: flex; gap: 8px; }
  .pill-btn {
    border: none; border-radius: 999px; padding: 8px 14px; font-size: 13px; font-weight: 700;
    cursor: pointer; color: #fff; text-decoration: none; display: inline-flex; align-items: center; gap: 5px;
    backdrop-filter: blur(10px);
  }
  .btn-pink { background: #fe2c55; box-shadow: 0 4px 15px rgba(254,44,85,0.4); }
  .btn-glass { background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.2); }

  /* حاوية تيك توك الطولية */
  .feed {
    height: 100dvh; width: 100vw; overflow-y: scroll;
    scroll-snap-type: y mandatory; scroll-behavior: smooth;
  }
  .feed::-webkit-scrollbar { display: none; }

  .slide {
    position: relative; height: 100dvh; width: 100vw;
    scroll-snap-align: start; scroll-snap-stop: always;
    background: #0a0a0a; display: flex; align-items: center; justify-content: center;
    overflow: hidden;
  }

  .media-box { width: 100%; height: 100%; max-width: 520px; position: relative; background: #000; }
  .media-box video, .media-box iframe {
    width: 100%; height: 100%; object-fit: cover; border: none; background: #000;
  }

  /* تدرج سفلي لوضوح النص */
  .gradient-bottom {
    position: absolute; bottom: 0; left: 0; right: 0; height: 35%;
    background: linear-gradient(to top, rgba(0,0,0,0.9), transparent);
    pointer-events: none; z-index: 10;
  }

  /* معلومات الفيديو أسفل اليمين */
  .video-info {
    position: absolute; bottom: 24px; right: 16px; left: 82px; z-index: 20;
  }
  .badge {
    display: inline-block; background: rgba(254,44,85,0.9); color: #fff;
    font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 6px; margin-bottom: 8px;
  }
  .author { font-size: 16px; font-weight: 800; margin-bottom: 4px; }
  .desc { font-size: 13px; color: #ddd; line-height: 1.4; word-break: break-all; }

  /* شريط الأزرار الجانبي مثل تيك توك */
  .side-bar {
    position: absolute; bottom: 28px; left: 12px; z-index: 25;
    display: flex; flex-direction: column; align-items: center; gap: 18px;
  }
  .action-btn {
    background: none; border: none; color: #fff; cursor: pointer;
    display: flex; flex-direction: column; align-items: center; gap: 4px;
    font-size: 12px; font-weight: 600; text-decoration: none;
  }
  .icon-circle {
    width: 46px; height: 46px; border-radius: 50%;
    background: rgba(255,255,255,0.14); backdrop-filter: blur(8px);
    display: flex; align-items: center; justify-content: center; font-size: 20px;
    transition: transform 0.15s, background 0.15s;
  }
  .action-btn:active .icon-circle { transform: scale(0.88); }
  .liked .icon-circle { background: #fe2c55; }

  /* شاشة التحميل */
  .loader-overlay {
    position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 10px;
    background: #111; color: #aaa; font-size: 14px; z-index: 5;
  }
  .spinner {
    width: 34px; height: 34px; border: 3px solid rgba(255,255,255,0.2);
    border-top-color: #fe2c55; border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* نافذة التحميل السريع */
  .modal {
    position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,0.75);
    backdrop-filter: blur(6px); display: none; align-items: center; justify-content: center; padding: 16px;
  }
  .modal.open { display: flex; }
  .modal-card {
    width: 100%; max-width: 420px; background: #161823; border: 1px solid #2b2e3d;
    border-radius: 18px; padding: 20px;
  }
  .modal-card h3 { margin-bottom: 12px; font-size: 17px; }
  .modal-card input {
    width: 100%; padding: 12px; border-radius: 12px; border: 1px solid #333;
    background: #0d0e14; color: #fff; font-size: 14px; margin-bottom: 14px; outline: none;
  }
  .modal-row { display: flex; gap: 8px; }
  .modal-row button { flex: 1; padding: 11px; border: none; border-radius: 12px; font-weight: 700; cursor: pointer; color: #fff; }
  .btn-blue { background: #2563eb; }
  .btn-green { background: #16a34a; }
  .btn-close { margin-top: 10px; width: 100%; padding: 9px; background: transparent; border: 1px solid #333; color: #aaa; border-radius: 10px; cursor: pointer; }
  .empty-state {
    height: 100dvh; display: flex; flex-direction: column; align-items: center;
    justify-content: center; text-align: center; padding: 24px; gap: 12px; color: #ccc;
  }
</style>
</head>
<body>

<div class="top-bar">
  <div class="logo">🎬 PRO <span>FEED</span></div>
  <div class="top-actions">
    <button class="pill-btn btn-pink" onclick="openModal()">➕ تحميل رابط</button>
    <a class="pill-btn btn-glass" href="https://t.me/{{ bot_username }}" target="_blank">🤖 البوت</a>
  </div>
</div>

<div class="feed" id="feed">
  <div class="empty-state">
    <div class="spinner"></div>
    <p>جاري تجهيز الفيديوهات...</p>
  </div>
</div>

<!-- نافذة تحميل أي رابط مباشرة -->
<div class="modal" id="dlModal">
  <div class="modal-card">
    <h3>⚡ تحميل فوري من أي منصة</h3>
    <input type="url" id="quickUrl" placeholder="الصق رابط يوتيوب، تيك توك، إنستجرام..." />
    <div class="modal-row">
      <button class="btn-blue" onclick="quickDownload('video')">🎬 تحميل فيديو</button>
      <button class="btn-green" onclick="quickDownload('audio')">🎵 صوت MP3</button>
    </div>
    <button class="btn-close" onclick="closeModal()">إغلاق</button>
  </div>
</div>

<script>
const feedEl = document.getElementById('feed');

function openModal() { document.getElementById('dlModal').classList.add('open'); }
function closeModal() { document.getElementById('dlModal').classList.remove('open'); }

function quickDownload(mode) {
  const url = document.getElementById('quickUrl').value.trim();
  if (!url) return alert('يرجى لصق رابط صحيح أولاً!');
  window.open(`/api/download?mode=${mode}&url=${encodeURIComponent(url)}`, '_blank');
  closeModal();
}

async function likeVideo(id, btn) {
  btn.classList.add('liked');
  const res = await fetch(`/api/like/${id}`, { method: 'POST' });
  const data = await res.json();
  btn.querySelector('.cnt').textContent = data.likes;
}

function shareVideo(url) {
  if (navigator.share) {
    navigator.share({ title: 'شاهد هذا الفيديو', url });
  } else {
    navigator.clipboard.writeText(url);
    alert('✅ تم نسخ رابط الفيديو!');
  }
}

async function resolveNativeVideo(slide, url) {
  if (slide.dataset.loaded) return;
  slide.dataset.loaded = '1';
  const box = slide.querySelector('.media-box');
  try {
    const res = await fetch(`/api/resolve?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    if (data.stream_url) {
      box.innerHTML = `<video src="${data.stream_url}" playsinline loop controls autoplay></video>`;
    } else {
      box.innerHTML = `<div class="loader-overlay"><p>⚠️ اضغط زر التحميل الجانبي لمشاهدة هذا الفيديو</p></div>`;
    }
  } catch {
    box.innerHTML = `<div class="loader-overlay"><p>⚠️ تعذّر التشغيل المباشر — استخدم زر التحميل</p></div>`;
  }
}

async function loadFeed() {
  const res = await fetch('/api/feed');
  const items = await res.json();

  if (!items.length) {
    feedEl.innerHTML = `
      <div class="empty-state">
        <h2>📭 لا توجد فيديوهات في الأرشيف بعد</h2>
        <p>أرسل أي رابط في بوت تيليجرام وسيظهر هنا فوراً بنظام تيك توك!</p>
        <button class="pill-btn btn-pink" onclick="openModal()">➕ جرّب تحميل رابط الآن</button>
      </div>`;
    return;
  }

  feedEl.innerHTML = '';
  items.forEach(item => {
    const slide = document.createElement('section');
    slide.className = 'slide';
    slide.dataset.url = item.url;
    slide.dataset.yt = item.yt_id || '';

    const mediaHtml = item.yt_id
      ? `<iframe src="https://www.youtube.com/embed/${item.yt_id}?playsinline=1&rel=0" allow="autoplay; encrypted-media" allowfullscreen></iframe>`
      : `<div class="loader-overlay"><div class="spinner"></div><span>جاري تجهيز البث...</span></div>`;

    slide.innerHTML = `
      <div class="media-box">${mediaHtml}</div>
      <div class="gradient-bottom"></div>
      <div class="video-info">
        <div class="badge">${item.platform}</div>
        <div class="author">@${item.user_name}</div>
        <div class="desc">${item.created_at}</div>
      </div>
      <div class="side-bar">
        <button class="action-btn" onclick="likeVideo(${item.id}, this)">
          <div class="icon-circle">❤️</div>
          <span class="cnt">${item.likes}</span>
        </button>
        <a class="action-btn" href="/api/download?mode=video&url=${encodeURIComponent(item.url)}" target="_blank">
          <div class="icon-circle">⬇️</div>
          <span>فيديو</span>
        </a>
        <a class="action-btn" href="/api/download?mode=audio&url=${encodeURIComponent(item.url)}" target="_blank">
          <div class="icon-circle">🎵</div>
          <span>MP3</span>
        </a>
        <button class="action-btn" onclick="shareVideo('${item.url.replace(/'/g, '')}')">
          <div class="icon-circle">🔗</div>
          <span>مشاركة</span>
        </button>
      </div>
    `;
    feedEl.appendChild(slide);
  });

  // تشغيل وإيقاف الفيديو تلقائياً مع السحب مثل تيك توك
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      const slide = entry.target;
      const vid = slide.querySelector('video');
      if (entry.isIntersecting) {
        if (!slide.dataset.yt) resolveNativeVideo(slide, slide.dataset.url);
        if (vid) vid.play().catch(() => {});
      } else {
        if (vid) vid.pause();
      }
    });
  }, { threshold: 0.7 });

  document.querySelectorAll('.slide').forEach(s => observer.observe(s));
}

loadFeed();
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML_PAGE, bot_username=BOT_USERNAME)


@app.route("/api/feed")
def api_feed():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT a.id, a.user_name, a.platform, a.url, a.created_at,
               COALESCE(l.likes, 0) AS likes
        FROM url_archive a
        LEFT JOIN web_likes l ON l.video_id = a.id
        ORDER BY a.id DESC LIMIT 40
        """
    ).fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "user_name": r["user_name"] or "مستخدم",
                "platform": r["platform"] or "فيديو",
                "url": r["url"],
                "yt_id": extract_youtube_id(r["url"]),
                "created_at": r["created_at"],
                "likes": r["likes"],
            }
        )
    return jsonify(items)


@app.route("/api/like/<int:vid_id>", methods=["POST"])
def api_like(vid_id: int):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO web_likes (video_id, likes) VALUES (?, 1)
        ON CONFLICT(video_id) DO UPDATE SET likes = likes + 1
        """,
        (vid_id,),
    )
    conn.commit()
    likes = conn.execute(
        "SELECT likes FROM web_likes WHERE video_id = ?", (vid_id,)
    ).fetchone()[0]
    conn.close()
    return jsonify({"likes": likes})


@app.route("/api/resolve")
def api_resolve():
    """جلب رابط البث المباشر MP4 لتشغيله داخل مشغل تيك توك بدون تحميل على السيرفر."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "missing url"}), 400
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "socket_timeout": 15,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get("url")
            if not stream_url and info.get("formats"):
                for f in reversed(info["formats"]):
                    if f.get("ext") == "mp4" and f.get("url"):
                        stream_url = f["url"]
                        break
            return jsonify({"stream_url": stream_url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/download")
def api_download():
    """تحميل مباشر للفيديو أو الصوت MP3 من المتصفح."""
    url = request.args.get("url", "").strip()
    mode = request.args.get("mode", "video")
    if not url:
        return Response("الرابط غير صالح", status=400)

    tmp_dir = tempfile.mkdtemp(prefix="web-dl-")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": os.path.join(tmp_dir, "%(title).60s.%(ext)s"),
        "format": "bestaudio/best" if mode == "audio" else "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "restrictfilenames": True,
    }
    if mode == "audio":
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        files = [f for f in Path(tmp_dir).iterdir() if f.is_file()]
        if not files:
            return Response("تعذّر تجهيز الملف", status=500)
        target = files[0]
        return send_file(target, as_attachment=True, download_name=target.name)
    except Exception as exc:
        return Response(f"خطأ في التحميل: {exc}", status=500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 الويب سايت يعمل الآن على: http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
