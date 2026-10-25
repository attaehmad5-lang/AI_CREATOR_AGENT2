#!/usr/bin/env bash
# Runs every gate and prints one PASS/FAIL table. Exit 0 only if all pass.
set -uo pipefail
cd "$(dirname "$0")/.."
declare -a NAMES RESULTS
run() {
  local name="$1"; shift
  if "$@" >"/tmp/verify_${name// /_}.log" 2>&1; then RESULTS+=("PASS"); else RESULTS+=("FAIL"); fi
  NAMES+=("$name")
}
run "uv lock is current"   uv lock --check
run "locked sync"          uv sync --frozen --all-groups
run "python pin"           uv run --frozen python -c "import platform,sys; sys.exit(platform.python_version() != open('.python-version').read().strip())"
run "ruff lint"            uv run --frozen ruff check src tests
run "ruff format"          uv run --frozen ruff format --check src tests
run "mypy strict"          uv run --frozen mypy src
run "pytest + coverage"    uv run --frozen pytest
run "secret scan"          uv run --frozen python -m ai_creator_agent.env scan-secrets --tracked
run "pip-audit"            uv run --frozen python -m ai_creator_agent.env audit --project .
run "preflight"            uv run --frozen python -m ai_creator_agent.env preflight
run "diagnose"             uv run --frozen python -m ai_creator_agent.env diagnose
run "docker test stage"    docker build --target test -t ai-creator-agent:test .
run "docker runtime"       docker build --target runtime -t ai-creator-agent:latest .
run "container diagnose"   docker run --rm -e AI_CREATOR_OPENAI_API_KEY=ci-placeholder-key ai-creator-agent:latest diagnose
fail=0
printf '\n%-24s %s\n' CHECK RESULT
for i in "${!NAMES[@]}"; do
  printf '%-24s %s\n' "${NAMES[$i]}" "${RESULTS[$i]}"
  [[ "${RESULTS[$i]}" == "FAIL" ]] && fail=1 && echo "   log: /tmp/verify_${NAMES[$i]// /_}.log"
done
exit "$fail"
