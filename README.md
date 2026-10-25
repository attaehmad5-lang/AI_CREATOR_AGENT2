# AI_CREATOR_AGENT — Python Environment Suite

A Python environment management and diagnostics package for validating runtime prerequisites, inspecting host resources, managing environment settings, checking executable availability, and scanning tracked files for likely secrets.

## Requirements

- Python version specified in `.python-version`
- `uv` for dependency management
- `ffmpeg` for media-related environment checks
- Docker (optional, for container verification)

## Quick start

```bash
./scripts/bootstrap.sh
uv run python -m ai_creator_agent.env diagnose
```

Run the complete local quality and security gate:

```bash
make ci
# or
./scripts/verify_all.sh
```

## Common commands

```bash
uv run python -m ai_creator_agent.env diagnose
uv run python -m ai_creator_agent.env scan-secrets --tracked
uv run python -m ai_creator_agent.env audit --project .
```

Use `uv run python -m ai_creator_agent.env --help` to see the supported CLI commands and options.

## Development and testing

```bash
uv sync --frozen --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

The test suite includes unit and subprocess integration tests. The container suite skips checks that specifically require a non-root user when the container is running as root.

## Dependency lock

`uv.lock` is committed. CI validates dependency resolution and syncs the locked environment; the Docker build uses frozen dependencies. When changing dependencies, regenerate and review the lock file, then commit it with the corresponding `pyproject.toml` change.

## Security notes

- Keep real API keys, tokens, and credentials out of source control.
- Use environment variables or a local, ignored secrets file for local credentials.
- Run `scan-secrets --tracked` before pushing changes.
- Review dependency audit output and CI results before releasing.

## Verification

GitHub Actions runs lint, formatting, strict typing, tests and coverage, tracked-secret scanning, dependency auditing, and container build checks. Passing CI confirms the configured gates for that commit; review the [verification record](VERIFICATION_RESULTS.md) for the latest evidence and any explicitly listed release limitations.
