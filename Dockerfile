==============================================================================
Dockerfile لتشغيل البوت مباشرة على استضافات السحابة (Railway, Render, Koyeb, Fly.io, VPS)
يثبت بايثون + ffmpeg + nodejs تلقائياً لضمان عمل التحميل والصوتيات بأعلى جودة
==============================================================================
FROM python:3.11-slim
منع بايثون من كتابة ملفات .pyc وتفعيل الطباعة الفورية في اللوج
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
تثبيت ffmpeg و nodejs الضروريين لمحرك yt-dlp
RUN apt-get update && 
apt-get install -y --no-install-recommends ffmpeg nodejs ca-certificates && 
rm -rf /var/lib/apt/lists/*
تحديد مجلد العمل داخل الحاوية
WORKDIR /app
نسخ ملف المكاتب وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && 
pip install --no-cache-dir -U -r requirements.txt
نسخ باقي ملفات البوت
COPY . .
إنشاء مجلد الكوكيز لضمان صلاحيات الكتابة
RUN mkdir -p cookies
أمر تشغيل البوت
CMD ["python3", "bot.py"]
