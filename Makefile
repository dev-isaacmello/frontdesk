# The same checks CI runs. `make check` before every push.

.PHONY: up down check check-backend check-web latency

up:
	docker compose up --build

down:
	docker compose down

check: check-backend check-web

check-backend:
	cd backend && uv run ruff format --check .
	cd backend && uv run ruff check .
	cd backend && uv run mypy
	cd backend && uv run pytest

check-web:
	cd web && pnpm lint
	cd web && pnpm typecheck
	cd web && pnpm test
	cd web && pnpm build

# Needs the stack running (`make up`).
latency:
	cd backend && uv run python scripts/latency.py --messages 200 --concurrency 1
	cd backend && uv run python scripts/latency.py --messages 200 --concurrency 10
