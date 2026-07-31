# syntax=docker/dockerfile:1.9
# Multi-stage: build deps once, ship a slim non-root runtime.

FROM python:3.12-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
# Dependency layer first: source edits must not invalidate the dep cache.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY rules ./rules
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 cirquento
WORKDIR /app
COPY --from=builder --chown=cirquento:cirquento /app/.venv /app/.venv
COPY --from=builder --chown=cirquento:cirquento /app/src /app/src
COPY --from=builder --chown=cirquento:cirquento /app/rules /app/rules
USER cirquento
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"
CMD ["uvicorn", "cirquento.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
