"""Automated boot-cycle diagnostic suite (RAM, disk, paths, GPU, permissions)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple

from .errors import EnvSuiteError
from .hardware import Probes, detect_hardware
from .preflight import _run_version, requirements_for, run_preflight
from .pyversion import check_python_version, in_virtualenv, read_pinned_version
from .resources import MB, MemorySnapshot, read_memory_snapshot


class Status(StrEnum):
    PASS = "pass"  # noqa: S105
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    message: str
    duration_ms: float = 0.0


@dataclass(frozen=True)
class DiagnosticReport:
    results: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(item.status is not Status.FAIL for item in self.results)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "results": [{"name": item.name, "status": item.status.value, "message": item.message, "duration_ms": round(item.duration_ms, 2)} for item in self.results]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def render_text(self) -> str:
        marks = {Status.PASS: "PASS", Status.WARN: "WARN", Status.FAIL: "FAIL"}
        lines = [f"[{marks[r.status]}] {r.name}: {r.message}" for r in self.results]
        lines.append("RESULT: " + ("healthy" if self.ok else "UNHEALTHY"))
        return "\n".join(lines)


@dataclass(frozen=True)
class DiagnosticConfig:
    pin_file: Path = Path(".python-version")
    runtime: str = "local"
    strict_patch: bool = True
    require_venv: bool = True
    min_free_ram_mb: int = 512
    min_free_disk_mb: int = 1024
    max_ram_mb: int | None = None
    required_dirs: tuple[Path, ...] = ()
    secret_files: tuple[Path, ...] = ()
    create_missing_dirs: bool = True
    strict_permissions: bool = False
    device_preference: str = "auto"
    require_accelerator: bool = False
    probes: Probes | None = field(default=None, compare=False)


class _Check(NamedTuple):
    name: str
    func: Callable[[], tuple[Status, str]]


class DiagnosticSuite:
    def __init__(
        self,
        config: DiagnosticConfig,
        memory_reader: Callable[[], MemorySnapshot] = read_memory_snapshot,
        disk_usage: Callable[[str], Any] = shutil.disk_usage,
        which: Callable[[str], str | None] = shutil.which,
        cli_runner: Callable[[str, Sequence[str]], str | None] = _run_version,
    ) -> None:
        self.config = config
        self._memory_reader = memory_reader
        self._disk_usage = disk_usage
        self._which = which
        self._cli_runner = cli_runner

    def _checks(self) -> list[_Check]:
        return [
            _Check("python", self._python), _Check("virtualenv", self._venv),
            _Check("cli", self._cli), _Check("memory", self._memory),
            _Check("paths", self._paths), _Check("disk", self._disk),
            _Check("permissions", self._permissions), _Check("hardware", self._hardware),
        ]

    def run(self, only: Sequence[str] | None = None) -> DiagnosticReport:
        results: list[CheckResult] = []
        for check in self._checks():
            if only is not None and check.name not in only:
                continue
            started = time.perf_counter()
            try:
                status, message = check.func()
            except (EnvSuiteError, OSError, ValueError) as exc:
                status, message = Status.FAIL, f"{type(exc).__name__}: {exc}"
            elapsed = (time.perf_counter() - started) * 1000
            results.append(CheckResult(check.name, status, message, elapsed))
        return DiagnosticReport(tuple(results))

    def _python(self) -> tuple[Status, str]:
        pinned = read_pinned_version(self.config.pin_file)
        result = check_python_version(pinned, strict_patch=self.config.strict_patch)
        return (Status.PASS if result.ok else Status.FAIL), result.message

    def _venv(self) -> tuple[Status, str]:
        active = in_virtualenv()
        if active:
            return Status.PASS, "running inside a virtual environment"
        if self.config.require_venv:
            return Status.FAIL, "not running inside a virtual environment"
        return Status.WARN, "no virtual environment (not required)"

    def _cli(self) -> tuple[Status, str]:
        reqs = requirements_for(self.config.runtime)
        checks = run_preflight(reqs, which=self._which, runner=self._cli_runner, raise_on_fail=False)
        bad = [c.message for c in checks if not c.ok]
        if bad:
            return Status.FAIL, "; ".join(bad)
        return Status.PASS, f"{len(checks)} CLI tools verified"

    def _memory(self) -> tuple[Status, str]:
        snap = self._memory_reader()
        free_mb = snap.available_bytes // MB
        total_mb = snap.total_bytes // MB
        need = self.config.min_free_ram_mb
        if free_mb < need:
            return Status.FAIL, f"{free_mb} MB free < required {need} MB"
        cap = self.config.max_ram_mb
        if cap is not None and cap > total_mb:
            return Status.WARN, f"RAM cap {cap} MB exceeds physical {total_mb} MB"
        if free_mb < need * 2:
            return Status.WARN, f"{free_mb} MB free is close to minimum {need} MB"
        return Status.PASS, f"{free_mb} MB free of {total_mb} MB"

    def _paths(self) -> tuple[Status, str]:
        problems: list[str] = []
        for directory in self.config.required_dirs:
            if not directory.exists():
                if not self.config.create_missing_dirs:
                    problems.append(f"missing {directory}")
                    continue
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not directory.is_dir():
                problems.append(f"not a directory: {directory}")
                continue
            try:
                with tempfile.TemporaryFile(dir=directory):
                    pass
            except OSError as exc:
                problems.append(f"not writable {directory}: {exc.strerror or exc}")
        if problems:
            return Status.FAIL, "; ".join(problems)
        return Status.PASS, f"{len(self.config.required_dirs)} directories writable"

    def _disk(self) -> tuple[Status, str]:
        need = self.config.min_free_disk_mb
        worst: int | None = None
        for directory in self.config.required_dirs:
            probe = directory
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            free_mb = int(self._disk_usage(str(probe)).free) // MB
            worst = free_mb if worst is None else min(worst, free_mb)
        if worst is None:
            return Status.PASS, "no directories to check"
        if worst < need:
            return Status.FAIL, f"{worst} MB free < required {need} MB"
        return Status.PASS, f"{worst} MB free"

    def _permissions(self) -> tuple[Status, str]:
        if os.name != "posix":
            return Status.PASS, "permission model not applicable on this OS"
        issues: list[str] = []
        for path in self.config.secret_files:
            if path.exists() and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                issues.append(f"{path} is accessible by group/others")
        for directory in self.config.required_dirs:
            if directory.exists() and directory.stat().st_mode & stat.S_IWOTH:
                issues.append(f"{directory} is world-writable")
        if not issues:
            return Status.PASS, "file permissions are restrictive"
        level = Status.FAIL if self.config.strict_permissions else Status.WARN
        return level, "; ".join(issues)

    def _hardware(self) -> tuple[Status, str]:
        report = detect_hardware(self.config.device_preference, probes=self.config.probes)
        label = f"{report.selected.kind.value}: {report.selected.name}"
        accelerated = report.selected.kind.value != "cpu"
        if self.config.require_accelerator and not accelerated:
            return Status.FAIL, "accelerator required but only cpu available"
        if report.fallback_reason and self.config.device_preference != "auto":
            return Status.WARN, f"{label} ({report.fallback_reason})"
        return Status.PASS, label
