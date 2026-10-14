# syntax=docker/dockerfile:1
# Gateway (Go). Se construye desde la RAÍZ del repo (necesita contracts/):
#   docker compose build gateway
# Binario estático (CGO_ENABLED=0): la misma receta sirve para ARM (VM de Oracle) con buildx.

FROM golang:1.27-alpine AS build
WORKDIR /src
COPY services/gateway/go.mod services/gateway/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY services/gateway/ ./
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /gateway ./cmd/gateway

FROM alpine:3.22
RUN adduser -D app
COPY --from=build /gateway /usr/local/bin/gateway
COPY contracts /contracts
ENV TRL_CONTRACTS_DIR=/contracts \
    GATEWAY_ADDR=0.0.0.0:8000
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD wget -qO- http://127.0.0.1:8000/healthz > /dev/null || exit 1
CMD ["gateway"]
