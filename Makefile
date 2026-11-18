# The same checks CI runs. `make check` before every push.

.PHONY: up down check check-backend check-web latency guardrail evals

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

# The reply checks on the labelled set. No model, no cost.
guardrail:
	cd backend && uv run python scripts/guardrail_rates.py

# The golden set against a real model. Costs money: needs the model key in .env and
# refuses to start when the estimate passes what is left of the budget.
evals:
	cd backend && uv run python scripts/run_evals.py --model gpt-oss-120b
