# ---------- stage 1: build the SPA ----------
FROM node:20-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY web/ ./
RUN npm run build


# ---------- stage 2: runtime ----------
FROM python:3.11-slim

# ffmpeg composes the video ad; the DejaVu fonts back both Pillow's disclosure
# overlay and ffmpeg's drawtext filter (slim images ship no fonts at all).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/api/ ./services/api/
COPY --from=web /web/dist ./web/dist

# Genblaze's asset-transfer layer only reads file:// URLs from temp roots, and
# HF Spaces runs as a non-root user, so give that user a writable HOME + TMPDIR.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    PORT=7860

RUN mkdir -p /tmp/hallmark && chmod -R 777 /tmp/hallmark

EXPOSE 7860
WORKDIR /app/services/api

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",7860)}/healthz').read()" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
