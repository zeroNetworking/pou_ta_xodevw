# ──────────────────────────────────────────────────────────────────────────────
#  Που τα ξοδεύω — Dockerfile
# ──────────────────────────────────────────────────────────────────────────────
#  Two-stage build:
#    1. builder   — installs Python deps into a virtualenv
#    2. runtime   — copies the venv + app code, runs as non-root via gunicorn
#
#  Why two stages? Smaller final image (no build toolchain), and a clean
#  separation between "install" and "run" phases.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────── Stage 1: builder ────────────────
FROM python:3.12-slim AS builder

# Build-time env: don't write .pyc, don't buffer stdout, don't cache pip
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install dependencies into an isolated venv so the runtime stage can
# just COPY it over as a single directory.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


# ──────────────── Stage 2: runtime ────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Persistent data lives in /app/data — mounted as a Docker volume.
    DATABASE_PATH=/app/data/database.db \
    # Marker so app.py refuses to start with the default SECRET_KEY.
    PRODUCTION=1 \
    DEBUG=0

# Create a non-root user. Running web apps as root is a needless risk:
# if a vulnerability lets someone escape the app, they at least don't
# escape into root inside the container.
RUN groupadd --system --gid 1000 finance \
 && useradd --system --uid 1000 --gid finance --create-home finance

WORKDIR /app

# Copy the prepared venv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code. Order is intentional: requirements first
# (already in venv), then app code last so code edits don't bust
# the dependency layer cache.
COPY --chown=finance:finance . /app

# Database lives in a separate dir so volume-mounting it doesn't
# shadow the rest of the app.
RUN mkdir -p /app/data && chown -R finance:finance /app/data /app

USER finance

EXPOSE 5000

# Gunicorn config:
#   --workers 3              → handles concurrent requests; rule of thumb
#                              is (2 * CPU cores) + 1, but for a single-user
#                              personal app, 3 is plenty.
#   --threads 2              → each worker handles 2 threads. SQLite
#                              serializes writes anyway, but reads parallelize.
#   --timeout 60             → kill workers stuck >60s. PDF export can
#                              take a moment, so we give it some headroom.
#   --access-logfile -       → access log → stdout (visible via docker logs)
#   --error-logfile -        → error log  → stderr
#   --bind 0.0.0.0:5000      → listen on all interfaces inside the container.
#                              Docker maps this to 5001 on the host.
CMD ["gunicorn", \
     "--workers", "3", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--bind", "0.0.0.0:5000", \
     "app:app"]
