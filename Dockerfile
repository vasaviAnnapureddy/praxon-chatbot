# =============================================================================
# Two stages, one image.
#
# Stage 1 uses Node to build the React app into static files.
# Stage 2 uses Python, copies those static files in, and runs FastAPI.
#
# Node is NOT in the final image — only the ~1 MB of built HTML/CSS/JS it
# produced. That keeps the image small, which matters because Render's free
# machine has 512 MB of RAM and a slow disk.
#
# This is also why the whole thing fits in ONE Render service: FastAPI serves
# the API and the website from the same process, so we use one of our 750 free
# instance hours per hour instead of two.
# =============================================================================

# ---------- Stage 1: build the frontend --------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /build

# package files first: Docker caches this layer, so `npm ci` only re-runs when
# dependencies actually change, not on every code edit.
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build
# -> /build/dist  (index.html, assets/, widget.js)


# ---------- Stage 2: the app --------------------------------------------------
FROM python:3.12-slim

# Standard Python-in-Docker hygiene:
#   PYTHONDONTWRITEBYTECODE - no .pyc clutter on an ephemeral disk
#   PYTHONUNBUFFERED        - logs appear in Render's log tab immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production

WORKDIR /app

# libpq is what psycopg3 talks to Postgres through. curl is for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
COPY backend/constraints.txt ./backend/constraints.txt
RUN pip install --no-cache-dir -r backend/requirements.txt -c backend/constraints.txt

COPY backend/ ./backend/
COPY client/ ./client/

# The built React files land where backend/.env expects them (../frontend/dist).
COPY --from=frontend /build/dist ./frontend/dist

# Do not run as root. If anything ever escapes the app, it escapes as nobody.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Render sets $PORT. Locally it defaults to 8000.
# One worker on purpose: 0.1 CPU cannot usefully run more, and a second worker
# would double the memory for no throughput.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir backend --workers 1 --proxy-headers --forwarded-allow-ips='*'"]

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/health || exit 1
