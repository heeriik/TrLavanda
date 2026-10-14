# syntax=docker/dockerfile:1
# Servicio factors. Se construye desde la RAÍZ del repo (necesita el paquete core y los contratos):
#   docker compose build factors

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Dependencias (capa cacheada mientras no cambie uv.lock).
COPY pyproject.toml uv.lock README.md ./
COPY services/factors/pyproject.toml services/factors/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package trlavanda-factors --no-install-workspace

# 2) Código: core + contratos + servicio.
COPY src ./src
COPY contracts ./contracts
COPY services/factors/src services/factors/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package trlavanda-factors

ENV PATH="/app/.venv/bin:$PATH" \
    TRL_DATA_DIR=/data
RUN useradd --create-home app && mkdir /data && chown app /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["trl-factors", "--host", "0.0.0.0", "--port", "8000"]
