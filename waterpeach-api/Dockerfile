FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Apply migrations + load demo seed (only when empty), then serve.
# Cloud Run injects PORT; local docker compose uses the default 8000.
# Set RUN_MIGRATIONS_ON_START=false to skip the migration/seed step.
ENV RUN_MIGRATIONS_ON_START=true
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS_ON_START\" = true ]; then uv run --no-dev alembic upgrade head && uv run --no-dev python -m app.seed; fi && exec uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
