FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 1. تثبيت ffmpeg والأدوات المساعدة
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# 2. تثبيت Node.js الإصدار 20 (مطلوب لحل تحديات يوتيوب)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

WORKDIR /app

COPY requirements.txt .

# 3. تثبيت yt-dlp مع الملحقات (لتحميل سكربتات EJS)
# وتثبيت باقي المكتبات من requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "yt-dlp[default]" && \
    pip install --no-cache-dir -U -r requirements.txt

COPY . .

RUN mkdir -p cookies

CMD ["python3", "download_v_s_vip1.py"]
