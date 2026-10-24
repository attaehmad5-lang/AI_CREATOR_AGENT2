"""Pre-flight verification of system CLI dependencies."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .errors import PreflightError

VersionTuple = tuple[int, ...]
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class CliRequirement:
    name: str
    min_version: VersionTuple | None = None
    version_args: tuple[str, ...] = ("--version",)


FULL_REQUIREMENTS: tuple[CliRequirement, ...] = (
    CliRequirement("git", (2, 30)),
    CliRequirement("ffmpeg", (4, 4), ("-version",)),
    CliRequirement("curl", (7, 68)),
    CliRequirement("tar"),
)
CONTAINER_REQUIREMENTS: tuple[CliRequirement, ...] = (
    CliRequirement("ffmpeg", (4, 4), ("-version",)),
)


@dataclass(frozen=True)
class CliCheck:
    name: str
    ok: bool
    path: str | None
    version: VersionTuple | None
    message: str


def parse_version(text: str) -> VersionTuple | None:
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    return tuple(int(group) for group in match.groups() if group is not None)


def _run_version(path: str, args: Sequence[str]) -> str | None:
    try:
        proc = subprocess.run(
            [path, *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    output = (proc.stdout or proc.stderr).strip()
    return output.splitlines()[0] if output else ""


def requirements_for(runtime: str) -> tuple[CliRequirement, ...]:
    if runtime == "container":
        return CONTAINER_REQUIREMENTS
    if runtime in ("local", "ci"):
        return FULL_REQUIREMENTS
    raise PreflightError(f"unknown runtime {runtime!r}")


def check_cli(
    requirement: CliRequirement,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[[str, Sequence[str]], str | None] = _run_version,
) -> CliCheck:
    name = requirement.name
    path = which(name)
    if path is None:
        return CliCheck(name, False, None, None, f"{name}: not found on PATH")
    output = runner(path, requirement.version_args)
    if output is None:
        return CliCheck(name, False, path, None, f"{name}: failed to report version")
    version = parse_version(output)
    minimum = requirement.min_version
    if minimum is None:
        return CliCheck(name, True, path, version, f"{name}: ok ({path})")
    if version is None:
        return CliCheck(name, False, path, None, f"{name}: unparseable version")
    wanted = ".".join(str(part) for part in minimum)
    found = ".".join(str(part) for part in version)
    if version < minimum:
        return CliCheck(name, False, path, version, f"{name}: {found} < {wanted}")
    return CliCheck(name, True, path, version, f"{name}: {found} >= {wanted}")


def run_preflight(
    requirements: Sequence[CliRequirement] = FULL_REQUIREMENTS,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[[str, Sequence[str]], str | None] = _run_version,
    raise_on_fail: bool = True,
) -> list[CliCheck]:
    results = [check_cli(req, which, runner) for req in requirements]
    failures = [item.message for item in results if not item.ok]
    if failures and raise_on_fail:
        raise PreflightError("; ".join(failures))
    return results
