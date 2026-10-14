# syntax=docker/dockerfile:1
# Servicio ingest. Se construye desde la RAÍZ del repo (necesita el paquete core y los contratos):
#   docker compose build ingest

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Dependencias (capa cacheada mientras no cambie uv.lock).
#    --frozen: usa uv.lock tal cual (el resto de servicios del workspace no se copian).
COPY pyproject.toml uv.lock README.md ./
COPY services/ingest/pyproject.toml services/ingest/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package trlavanda-ingest --no-install-workspace

# 2) Código: core + contratos + servicio.
COPY src ./src
COPY contracts ./contracts
COPY services/ingest/src services/ingest/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package trlavanda-ingest

ENV PATH="/app/.venv/bin:$PATH" \
    TRL_DATA_DIR=/data
# La caché de zonas horarias de yfinance se crea con varios hilos a la vez y a veces choca: se
# deja creada de antemano.
RUN useradd --create-home app && mkdir /data && chown app /data \
    && mkdir -p /home/app/.cache/py-yfinance && chown -R app /home/app/.cache
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["trl-ingest", "--host", "0.0.0.0", "--port", "8000"]
