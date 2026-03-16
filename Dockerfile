# syntax=docker/dockerfile:1

FROM rust:1.93-slim-trixie AS builder
WORKDIR /app

RUN apt-get update -y \
  && apt-get install -y pkg-config make g++ libssl-dev

RUN --mount=type=bind,source=src,target=src \
  --mount=type=bind,source=Cargo.toml,target=Cargo.toml \
  --mount=type=bind,source=Cargo.lock,target=Cargo.lock \
  --mount=type=cache,target=/app/target/ \
  --mount=type=cache,target=/usr/local/cargo/registry/ \
  <<EOF
set -e
cargo build --locked --release
mv ./target/release/sanitarr /app
EOF

FROM node:22-alpine AS frontend_builder
WORKDIR /app/gui
COPY gui/package.json ./package.json
COPY gui/tailwind.config.js ./tailwind.config.js
COPY gui/static ./static
RUN npm install
RUN npm run build:css

FROM debian:trixie-slim AS runtime
RUN apt-get update && \
    apt-get install -y libssl3 python3 && \
    rm -rf /var/cache/apt/archives /var/lib/apt/lists/*
COPY --from=builder /app/sanitarr /usr/local/bin
COPY gui /opt/jellycleanerr/gui
COPY --from=frontend_builder /app/gui/static/tailwind.css /opt/jellycleanerr/gui/static/tailwind.css
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV HOST=0.0.0.0 \
    PORT=8282 \
    SANITARR_CONFIG=/config/config.toml \
    DB_PATH=/data/jellycleanerr-gui.db \
    CACHE_TTL_SECONDS=60 \
    INTERVAL=1h \
    FORCE_DELETE=true \
    LOG_LEVEL=info

EXPOSE 8282

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
