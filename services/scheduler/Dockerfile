# syntax=docker/dockerfile:1
# Servicio scheduler (Go). Se construye desde la RAÍZ del repo (necesita libs/go y contracts/):
#   docker compose build scheduler
# Binario estático (CGO_ENABLED=0): la misma receta sirve para ARM (VM de Oracle) con buildx.

FROM golang:1.27-alpine AS build
WORKDIR /src
COPY libs/go libs/go
COPY services/scheduler/go.mod services/scheduler/go.sum services/scheduler/
WORKDIR /src/services/scheduler
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY services/scheduler/ ./
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /scheduler ./cmd/scheduler

FROM alpine:3.22
RUN adduser -D app
COPY --from=build /scheduler /usr/local/bin/scheduler
COPY contracts /contracts
ENV TRL_CONTRACTS_DIR=/contracts
USER app
ENV SCHEDULER_ADDR=0.0.0.0:8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD wget -qO- http://127.0.0.1:8000/healthz > /dev/null || exit 1
CMD ["scheduler"]
