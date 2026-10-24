#!/usr/bin/env bash
# Generate a real uv.lock with the repository's pinned toolchain.
# Requires network access to the package index and Python download host.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

required_uv="0.5.11"
required_python="$(tr -d '[:space:]' < .python-version)"

command -v uv >/dev/null 2>&1 || {
  echo "ERROR: uv is not installed. Install uv $required_uv first." >&2
  exit 2
}
actual_uv="$(uv --version | awk '{print $2}')"
if [[ "$actual_uv" != "$required_uv" ]]; then
  echo "ERROR: expected uv $required_uv, found $actual_uv" >&2
  exit 2
fi

[[ -f pyproject.toml ]] || { echo "ERROR: pyproject.toml missing" >&2; exit 2; }
[[ -f .python-version ]] || { echo "ERROR: .python-version missing" >&2; exit 2; }

echo "Installing pinned Python $required_python (network access may be required)..."
uv python install "$required_python"

echo "Resolving and writing uv.lock using uv $required_uv and Python $required_python..."
uv lock --python "$required_python"

echo "Checking that the committed-style lockfile is valid and current..."
uv lock --check --python "$required_python"

echo "Lockfile generated successfully: $ROOT/uv.lock"
echo "Next: review 'git diff -- uv.lock', then run 'uv sync --frozen --all-groups' and 'make ci'."
