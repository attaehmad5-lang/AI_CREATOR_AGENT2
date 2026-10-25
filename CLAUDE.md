# CLAUDE.md — AI_CREATOR_AGENT2 Engineering Contract

## Mission
Complete the environment-management suite to production-grade quality. Work continuously through implementation, tests, verification, and safe commits; do not stop after writing code or merely making CI green. The source of truth is repository code/tests plus any explicitly supplied original archive. Do not claim parity with an archive that has not been inspected.

## Working rules
1. Inspect the current branch, working tree, PR, CI workflow, docs, source modules, and tests before editing. Do not overwrite working implementation blindly.
2. For every change: inspect → implement → run focused tests → run all relevant gates → inspect results/logs → fix failures → rerun.
3. Continue ordinary repository work without asking permission at each step. Do not send progress/status messages to the user; report only at a meaningful completion gate or when a genuine external blocker needs user action.
4. A feature is not complete merely because code was added. Completion requires documented behavior, tests for success/failure/edge/security cases, relevant gates passing, and a commit.
5. Never weaken assertions, lower coverage thresholds, skip failing tests to make CI green, or change production behavior solely to satisfy tests. Platform-dependent skips must be narrow and justified.
6. Preserve public APIs and compatibility unless requirements say otherwise. Prefer minimal, maintainable, typed changes.
7. Keep the pull request Draft until source parity, all required tests, security checks, and container checks are verified. Do not merge or mark ready without explicit user authorization.
8. Commit tested units to the current working branch with descriptive messages. Never rewrite shared history or force-push.
9. Never expose, copy, log, or commit API keys, tokens, .env contents, private credentials, or user data. Keep secret scanning enabled. No destructive actions or remote-setting changes without explicit authorization.
10. Report verified facts only. Distinguish assumptions, skips, known gaps, and external blockers. Never fabricate test counts, coverage, CI success, or source parity.

## Canonical verification commands
Use the project's pinned environment and canonical targets:
- `uv sync --frozen --all-groups`
- `make lint`
- `make typecheck`
- `make test`
- `make secrets`
- `make audit`
- `make diagnose` (when host prerequisites are available)
- `make docker-test`
- `make docker-build`
- Final gate: `make ci`, then both Docker targets and inspect GitHub Actions for the exact HEAD SHA.

When a command fails, capture the exact failure, find root cause, fix properly, and rerun the failed command plus the full relevant gate. A cancelled or stale run is not a pass. Confirm the latest successful workflow's commit SHA equals current branch HEAD.

## Feature-completion checklist
For every module/feature, verify all applicable items:
- [ ] Requirements and current behavior understood from source, docs, and tests.
- [ ] Inputs, outputs, types, exceptions, and CLI/API behavior are defined.
- [ ] Happy path, invalid input, boundaries, failures, and recovery are tested.
- [ ] Security: secrets, path traversal, permissions, unsafe subprocess calls, injection, and data leakage are considered.
- [ ] Resource behavior: timeouts, cleanup, child processes, signals, concurrency, and stale state are tested where relevant.
- [ ] Platform behavior is tested or documented (Linux/macOS/Windows; root/non-root; CPU/CUDA/ROCm/MPS as applicable).
- [ ] Diagnostics are actionable and never disclose secrets.
- [ ] Type checks, lint, formatting, coverage, and regression tests pass.
- [ ] Docs/examples match actual behavior.
- [ ] Change is committed and CI is verified on that exact commit.

## Original archive / parity requirement
If an original project ZIP or baseline is available:
1. Inventory it safely without executing archive contents.
2. Compare every relevant source module, test, config, workflow, and document with this repository.
3. Produce a file-by-file parity matrix: identical, intentionally changed (with rationale), missing functionality, missing tests, or obsolete.
4. Port missing behavior and meaningful regression tests; preserve stronger existing protections.
5. Run the full suite and record actual counts, skips, and coverage.
If the archive is unavailable, record it as a blocker and continue improving this repository, but do not claim archive parity.

## Previous verification context — re-check before relying on it
A previous GitHub Actions run on commit `a3a1c12e3e39c43807b927966247f1b7f2eab5d6` passed the verify job with **326 passed** and **93.21% coverage**; the container stage passed with **325 passed, 1 skipped** and **92.78% coverage**. These figures apply only to that historical run. Fetch current runs and verify the HEAD SHA before reporting current status. Original-archive parity was still incomplete at that time; do not declare the overall project complete until resolved or explicitly documented as an external blocker.

## Final delivery requirements
Report completion only after:
1. Identified feature gaps are addressed or individually documented with evidence and a reason they cannot be closed.
2. Focused tests and the full suite pass.
3. Lint, format, strict type check, secret scan, dependency audit, and container test/build pass.
4. Latest CI run matches the final commit SHA and all required jobs succeed.
5. Verification docs include exact links, SHA, counts, coverage, skips, and remaining limitations.
6. Work is committed to the correct branch and the PR remains Draft unless explicitly authorized otherwise.

Final response: concise and truthful. Include branch/PR and latest CI links, exact verified results, and remaining blockers. Never claim 100% completion while any required gate remains unresolved.
