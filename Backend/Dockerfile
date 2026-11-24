# PillCare Backend: one long-running process (device sockets, /ws/app and command acks live in
# memory, so never more than one worker or instance). Used by Render (render.yaml at the repo root)
# and by Railway, which builds a Dockerfile it finds in the service's root directory.
# Deploy guide: docs/DEPLOY_BACKEND.md.
FROM python:3.11-slim

# uv installs exactly what uv.lock pins.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first: this layer is reused while only the code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 pillcare && chown -R pillcare /app
USER pillcare

# Hosts set PORT (Render: 10000 by default); 8000 locally. One worker on purpose (Backend/CLAUDE.md).
# --proxy-headers: the host's proxy terminates TLS, so the app sees the real scheme and client IP.
EXPOSE 8000
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
