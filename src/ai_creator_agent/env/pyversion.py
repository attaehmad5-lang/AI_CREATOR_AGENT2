"""Exact Python patch pinning and virtual-environment validation."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import PythonVersionError, VirtualEnvError

Version = tuple[int, int, int]
_EXACT = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_exact_version(text: str) -> Version:
    """Parse X.Y.Z; anything looser is rejected."""
    match = _EXACT.match(text.strip())
    if match is None:
        raise PythonVersionError(
            f"Python pin must be an exact X.Y.Z version, got {text!r}"
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def read_pinned_version(path: Path) -> Version:
    """Read the first non-comment line of a .python-version file."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PythonVersionError(f"cannot read pin file {path}: {exc}") from exc
    for line in content.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            return parse_exact_version(candidate)
    raise PythonVersionError(f"pin file {path} contains no version")


def running_version() -> Version:
    info = sys.version_info
    return info[0], info[1], info[2]


@dataclass(frozen=True)
class VersionCheck:
    ok: bool
    pinned: Version
    running: Version
    message: str


def _fmt(version: Version) -> str:
    return ".".join(str(part) for part in version)


def check_python_version(
    pinned: Version,
    running: Version | None = None,
    *,
    strict_patch: bool = True,
) -> VersionCheck:
    """Compare the interpreter to the pin."""
    actual = running if running is not None else running_version()
    ok = actual == pinned if strict_patch else actual[:2] == pinned[:2]
    message = (
        f"python {_fmt(actual)} matches pin {_fmt(pinned)}"
        if ok
        else f"python {_fmt(actual)} does not match pin {_fmt(pinned)}"
    )
    return VersionCheck(ok, pinned, actual, message)


def enforce_python_version(
    pin_file: Path,
    *,
    strict_patch: bool = True,
    running: Version | None = None,
) -> VersionCheck:
    result = check_python_version(
        read_pinned_version(pin_file), running, strict_patch=strict_patch
    )
    if not result.ok:
        raise PythonVersionError(result.message)
    return result


def in_virtualenv(prefix: str | None = None, base_prefix: str | None = None) -> bool:
    """True when sys.prefix differs from the base interpreter prefix."""
    current = sys.prefix if prefix is None else prefix
    base = getattr(sys, "base_prefix", current) if base_prefix is None else base_prefix
    return os.path.realpath(current) != os.path.realpath(base)


def validate_virtualenv(
    expected: Path | None = None,
    environ: Mapping[str, str] | None = None,
    prefix: str | None = None,
    base_prefix: str | None = None,
) -> Path:
    """Fail unless running inside a venv (optionally a specific one)."""
    env = os.environ if environ is None else environ
    current = sys.prefix if prefix is None else prefix
    if not in_virtualenv(current, base_prefix):
        raise VirtualEnvError("not running inside a virtual environment")
    active = Path(os.path.realpath(current))
    declared = env.get("VIRTUAL_ENV")
    if declared and Path(os.path.realpath(declared)) != active:
        raise VirtualEnvError(
            f"VIRTUAL_ENV={declared} does not match interpreter prefix {active}"
        )
    if expected is not None and Path(os.path.realpath(expected)) != active:
        raise VirtualEnvError(f"expected venv {expected}, running in {active}")
    return active
