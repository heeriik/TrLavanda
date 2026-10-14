# syntax=docker/dockerfile:1
# Imagen Python común: el paquete trlavanda (datos, factores, bus de eventos) con sus dependencias.
# De momento sirve para crear los topics (trl-bus init); en el hito 2 los servicios ingest y
# factors arrancarán desde esta misma imagen con otro comando.

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Solo las dependencias: esta capa se reutiliza mientras no cambie uv.lock (builds rápidos).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# 2) El código y los contratos.
COPY src ./src
COPY contracts ./contracts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    TRL_DATA_DIR=/data
RUN useradd --create-home app && mkdir /data && chown app /data
USER app

CMD ["trl-bus", "--help"]
