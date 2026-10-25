# Single source of truth: local, GitHub Actions and Docker all call these targets.
.PHONY: sync lint format typecheck test audit secrets diagnose ci docker-test docker-build

sync:
	uv sync --frozen --all-groups

lint:
	uv run --frozen ruff check src tests
	uv run --frozen ruff format --check src tests

format:
	uv run --frozen ruff check --fix src tests
	uv run --frozen ruff format src tests

typecheck:
	uv run --frozen mypy src

test:
	uv run --frozen pytest

audit:
	uv run --frozen python -m ai_creator_agent.env audit --project .

secrets:
	uv run --frozen python -m ai_creator_agent.env scan-secrets --tracked

diagnose:
	uv run --frozen python -m ai_creator_agent.env preflight
	uv run --frozen python -m ai_creator_agent.env diagnose

ci: lint typecheck test secrets audit

docker-test:
	docker build --target test -t ai-creator-agent:test .

docker-build:
	docker build --target runtime -t ai-creator-agent:latest .
