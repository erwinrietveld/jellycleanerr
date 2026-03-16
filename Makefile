IMAGE_NAME ?= jellycleanerr:dev
DEV_IMAGE_NAME ?= jellycleanerr-dev-toolchain:latest
CONFIG ?= $(PWD)/config.toml

.PHONY: dev-image dev-shell image lint test build run-dry run-force up down logs

dev-image:
	docker build -f Dockerfile.dev -t $(DEV_IMAGE_NAME) .

dev-shell: dev-image
	docker run --rm -it -v "$(PWD):/workspace" -w /workspace $(DEV_IMAGE_NAME) bash

image:
	docker build -t $(IMAGE_NAME) .

build: dev-image
	docker run --rm -v "$(PWD):/workspace" -w /workspace $(DEV_IMAGE_NAME) cargo build --locked --release

lint: dev-image
	docker run --rm -v "$(PWD):/workspace" -w /workspace $(DEV_IMAGE_NAME) cargo clippy --all --all-targets --all-features -- -Dwarnings -Adeprecated

test: dev-image
	docker run --rm -v "$(PWD):/workspace" -w /workspace $(DEV_IMAGE_NAME) cargo test --locked --all

run-dry: image
	docker run --rm --network host \
		-v "$(CONFIG):/app/config.toml:ro" \
		--entrypoint /usr/local/bin/jellycleanerr \
		$(IMAGE_NAME) \
		--config /app/config.toml --log-level info

run-force: image
	docker run --rm --network host \
		-v "$(CONFIG):/app/config.toml:ro" \
		--entrypoint /usr/local/bin/jellycleanerr \
		$(IMAGE_NAME) \
		--config /app/config.toml --log-level info --force-delete

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=120
