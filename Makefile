.PHONY: help up down logs ps build rebuild migrate revision shell psql redis-cli \
	test lint format typecheck check sreality-discover-praha

help:
	@echo "Common commands:"
	@echo "  make up                       - bring up the dev stack"
	@echo "  make down                     - stop the dev stack"
	@echo "  make logs                     - tail all logs"
	@echo "  make ps                       - show service status"
	@echo "  make build                    - build images"
	@echo "  make rebuild                  - rebuild without cache"
	@echo "  make migrate                  - run alembic upgrade head"
	@echo "  make revision m='message'     - generate alembic revision"
	@echo "  make shell                    - shell into the api container"
	@echo "  make psql                     - psql into the dev DB"
	@echo "  make redis-cli                - redis-cli into the dev Redis"
	@echo "  make test                     - run pytest"
	@echo "  make lint                     - ruff lint"
	@echo "  make format                   - ruff format"
	@echo "  make typecheck                - mypy"
	@echo "  make check                    - lint + typecheck + test"
	@echo "  make sreality-discover-praha  - trigger one discovery run"

up:
	docker compose up -d
	@echo "API:    http://localhost:8000/healthz"
	@echo "MinIO:  http://localhost:9001  (user: minioadmin / pass: minioadmin)"

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

build:
	docker compose build

rebuild:
	docker compose build --no-cache

migrate:
	docker compose run --rm api alembic upgrade head

revision:
	@test -n "$(m)" || (echo "usage: make revision m='message'" && exit 1)
	docker compose run --rm api alembic revision --autogenerate -m "$(m)"

shell:
	docker compose exec api bash

psql:
	docker compose exec postgres psql -U realitni -d realitni

redis-cli:
	docker compose exec redis redis-cli

test:
	docker compose run --rm api pytest

lint:
	docker compose run --rm api ruff check src tests

format:
	docker compose run --rm api ruff format src tests

typecheck:
	docker compose run --rm api mypy src

check: lint typecheck test

sreality-discover-praha:
	docker compose exec worker python -c "from worker.tasks.ingest import discover; \
		discover.delay('sreality', {'region': 10, 'category_main': 1, 'category_type': 1})"
