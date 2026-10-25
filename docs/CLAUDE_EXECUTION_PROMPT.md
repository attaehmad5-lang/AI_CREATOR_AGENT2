# Copy-paste execution prompt for Claude Code

Read the repository-root `CLAUDE.md` completely and follow it as binding project guidance.

You are working in `attaehmad5-lang/AI_CREATOR_AGENT2`, branch `env-suite`. Your goal is to finish the environment-management features to a verifiable, production-grade standard—not merely to propose a plan.

## Required execution
1. Inspect the current Git status, branch and HEAD; inspect the open/closed PR state and the latest GitHub Actions runs. Do not assume prior reports are current.
2. Inventory the complete repository: every source module, test, CLI command, configuration, workflow, Docker stage, and documentation. Build a feature matrix with implementation evidence, test evidence, and gaps.
3. If the supplied original project ZIP exists in the workspace, safely inventory it and compare every relevant source/test/config/document against the branch. Restore missing behavior and meaningful tests without blindly overwriting newer or safer code. If the archive is not accessible, record this explicitly and do not claim parity.
4. Prioritize the highest-risk gaps first: security and secrets, subprocess/process lifecycle and cleanup, resource limits and recovery, path and permission safety, diagnostics, platform handling, concurrency, CLI behavior, and regression coverage.
5. For each gap, implement the fix, add tests for normal behavior, invalid input, boundaries, failures, and recovery, then run the focused tests. Fix failures rather than weakening assertions or adding broad skips.
6. Run the canonical repository gates: `uv sync --frozen --all-groups`, `make lint`, `make typecheck`, `make test`, `make secrets`, `make audit`, and where supported `make diagnose`, `make docker-test`, `make docker-build`. Finish with `make ci` and the Docker gates. Use the pinned dependencies.
7. Inspect the actual logs and summaries. Verify that the latest successful GitHub Actions run is for the exact final HEAD SHA and that every required job succeeded. A cancelled, stale, or unrelated run is not evidence.
8. Update `VERIFICATION_RESULTS.md` with exact evidence: final SHA, CI URLs, test counts, coverage, skips and why, security/audit results, container results, archive parity findings, and any unresolved blockers.
9. Commit each tested unit with a descriptive message. Keep credentials private; never commit secrets, tokens, local environment files, or generated sensitive data. Do not force-push, merge, or change PR review state without explicit authorization.
10. Continue through all actionable work without pausing for routine approval or sending progress/status messages. If blocked by a missing credential, unavailable archive, unavailable platform, or external service, document the precise blocker and continue with other work that can be completed safely.

## Definition of done
Do not claim completion until every identified in-scope gap is fixed or individually documented with evidence and a defensible blocker; all relevant tests and quality/security gates pass; container test/build pass; docs reflect reality; changes are committed; and CI passes on the exact final SHA. Clearly separate completed items from blockers. Never invent test results or claim 100% completion while a required gate is unresolved.

## Final response format
Provide a concise evidence-based summary only after reaching a completion gate:
- completed feature groups and commit(s)
- test count, coverage and skips from the final run
- lint/type/security/dependency/container gate outcomes
- links to the exact successful CI run and PR
- remaining blockers, if any

If the work is not fully complete, say so plainly and keep working on the remaining actionable items.
