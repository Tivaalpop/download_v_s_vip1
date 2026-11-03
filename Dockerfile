# استخدام بيئة بايثون الرسمية الخفيفة
FROM python:3.11-slim

# تثبيت الحزم الأساسية والنظامية (FFmpeg و Node.js لتشغيل يوتيوب وإنستجرام بدون أخطاء)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المتطلبات أولاً للاستفادة من تخزين الكاش (Caching)
COPY requirements.txt .

# تثبيت مكتبات البايثون المطلوبة
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع إلى المجلد
COPY . .

# أمر تشغيل البوت تلقائياً عند بدء الحاوية
CMD ["python", "download_v_s_vip1.py"]
