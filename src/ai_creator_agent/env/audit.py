"""Automated dependency vulnerability scanning (pip-audit, safety)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import EnvSuiteError

Runner = Callable[[Sequence[str]], tuple[int, str, str]]


class AuditError(EnvSuiteError):
    """The scanner could not run or produced unusable output."""


@dataclass(frozen=True)
class Vulnerability:
    package: str
    version: str
    vuln_id: str
    fix_versions: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    scanner: str
    vulnerabilities: tuple[Vulnerability, ...]
    ignored: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.vulnerabilities


def _run(cmd: Sequence[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=600, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuditError(f"cannot run {cmd[0]}: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr


def parse_pip_audit_json(payload: str, ignore: Collection[str] = ()) -> AuditReport:
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise AuditError(f"pip-audit emitted invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or "dependencies" not in data:
        raise AuditError("pip-audit JSON missing 'dependencies'")
    found: list[Vulnerability] = []
    skipped: list[str] = []
    for dep in data["dependencies"]:
        for vuln in dep.get("vulns", []):
            ids = {vuln.get("id", ""), *vuln.get("aliases", [])}
            if ids & set(ignore):
                skipped.append(str(vuln.get("id", "")))
                continue
            found.append(Vulnerability(
                str(dep.get("name", "?")), str(dep.get("version", "?")),
                str(vuln.get("id", "?")), tuple(str(v) for v in vuln.get("fix_versions", [])),
            ))
    return AuditReport("pip-audit", tuple(found), tuple(skipped))


def audit_lockfile(lock_dir: Path, export_to: Path, ignore: Collection[str] = (), runner: Runner = _run) -> AuditReport:
    """Export the uv lockfile and audit exactly the pinned set (no resolver)."""
    code, _out, err = runner([
        "uv", "export", "--frozen", "--no-hashes", "--no-emit-project",
        "--project", str(lock_dir), "-o", str(export_to),
    ])
    if code != 0:
        raise AuditError(f"uv export failed: {err.strip()}")
    code, out, err = runner([
        "pip-audit", "-r", str(export_to), "--no-deps", "--disable-pip",
        "--format", "json", "--progress-spinner", "off",
    ])
    if code not in (0, 1):
        raise AuditError(f"pip-audit failed ({code}): {err.strip()}")
    return parse_pip_audit_json(out, ignore)


def run_safety(runner: Runner = _run) -> AuditReport:
    """Second-opinion scanner; exit status is the contract (0 = clean)."""
    code, _out, err = runner(["safety", "check", "--output", "json"])
    if code == 0:
        return AuditReport("safety", (), ())
    if code == 64:
        return AuditReport("safety", (Vulnerability("see safety output", "?", "SAFETY", ()),), ())
    raise AuditError(f"safety failed ({code}): {err.strip()}")
