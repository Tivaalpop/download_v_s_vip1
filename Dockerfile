FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# تثبيت ffmpeg و nodejs (ضروريين جداً ليوتيوب)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg nodejs ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -U -r requirements.txt

COPY . .

RUN mkdir -p cookies

CMD ["python3", "download_v_s_vip1.py"]
