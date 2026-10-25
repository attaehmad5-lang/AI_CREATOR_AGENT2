#!/usr/bin/env bash
# One-shot developer/CI bootstrap: pinned Python, locked deps, hooks, diagnostics.
set -euo pipefail
cd "$(dirname "$0")/.."

PIN="$(tr -d '[:space:]' < .python-version)"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv python install "${PIN}"
uv venv --python "${PIN}" .venv
uv sync --frozen --all-groups
uv run --frozen pre-commit install --install-hooks

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "created .env from template - fill in provider keys" >&2
fi

uv run --frozen python -m ai_creator_agent.env preflight
uv run --frozen python -m ai_creator_agent.env diagnose
echo "bootstrap complete (python ${PIN})"
