#!/bin/bash
# ==============================================================================
# سكريبت التشغيل التلقائي للبوت على الاستضافة أو السيرفر (VPS / Linux / Panel)
# ==============================================================================

echo "🚀 جاري تجهيز بيئة التشغيل لبوت التحميل..."

# 1. التحقق من وجود برنامج ffmpeg (ضروري لدمج الفيديو العالي الجودة واستخراج MP3)
if ! command -v ffmpeg &> /dev/null; then
    echo "📦 برنامج ffmpeg غير موجود، جاري محاولة تثبيته..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -y && sudo apt-get install -y ffmpeg nodejs || apt-get update -y && apt-get install -y ffmpeg nodejs
    elif command -v apk &> /dev/null; then
        apk add --no-cache ffmpeg nodejs
    fi
fi

# 2. تثبيت وتحديث مكاتب بايثون (ومحرك yt-dlp لآخر إصدار دائماً)
echo "📦 جاري تثبيت وتحديث المكاتب المطلوبة..."
pip install --upgrade pip
pip install -U -r requirements.txt

# 3. تشغيل البوت مع إعادة التشغيل التلقائي لو السيرفر عمل ريستارت للعملية
echo "✅ جاري تشغيل البوت الآن..."
while true; do
    python3 bot.py
    echo "⚠️ توقفت العملية، جاري إعادة التشغيل خلال 5 ثوانٍ..."
    sleep 5
done
