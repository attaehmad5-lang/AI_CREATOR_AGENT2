"""Zero-secret-leakage guard: regex + entropy scanner for files and git."""

from __future__ import annotations

import fnmatch
import math
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import SecretLeakError

ALLOW_PRAGMA = "secret-scan: allow"
MAX_FILE_BYTES = 1_000_000
MAX_LINE_CHARS = 20_000
SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache"})
FORBIDDEN_NAMES = (".env", ".env.local", ".env.dev", ".env.test", ".env.staging", ".env.prod", "*.pem", "*.p12", "id_rsa", "id_ed25519")
PLACEHOLDER_HINTS = ("example", "changeme", "change_me", "placeholder", "your_", "your-", "dummy", "sample", "xxxx", "****", "<", "${", "todo", "redacted")


@dataclass(frozen=True)
class SecretRule:
    name: str
    pattern: re.Pattern[str]
    min_entropy: float | None = None
    group: int = 0


def _rule(name: str, regex: str, entropy: float | None = None, group: int = 0) -> SecretRule:
    return SecretRule(name, re.compile(regex), entropy, group)


RULES: tuple[SecretRule, ...] = (
    _rule("private-key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"),
    _rule("aws-access-key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    _rule("github-token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    _rule("slack-token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    _rule("google-api-key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    _rule("anthropic-key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    _rule("openai-key", r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    _rule("stripe-key", r"\b[sr]k_live_[0-9A-Za-z]{24,}\b"),
    _rule("jwt", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    _rule("generic-assignment", r"(?i)[\w.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|credential)[\w.-]*\s*[:=]\s*[\"']?([A-Za-z0-9/+=_\-]{16,})[\"']?", 3.5, 1),
)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    snippet: str


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def redact(value: str) -> str:
    return f"{value[:4]}***" if len(value) > 4 else "***"


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(hint in lowered for hint in PLACEHOLDER_HINTS)


def scan_text(text: str, path: str = "<memory>") -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if len(line) > MAX_LINE_CHARS or ALLOW_PRAGMA in line:
            continue
        taken: list[tuple[int, int]] = []
        for rule in RULES:
            for match in rule.pattern.finditer(line):
                span = match.span(rule.group)
                if any(span[0] < end and start < span[1] for start, end in taken):
                    continue
                value = match.group(rule.group)
                if rule.min_entropy is not None:
                    if shannon_entropy(value) < rule.min_entropy or value.isalpha() or _is_placeholder(value):
                        continue
                elif _is_placeholder(value) and rule.name != "private-key":
                    continue
                taken.append(span)
                findings.append(Finding(rule.name, path, lineno, redact(value)))
    return findings


def _looks_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def scan_file(path: Path) -> list[Finding]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    if _looks_binary(data[:8192]):
        return []
    return scan_text(data.decode("utf-8", errors="replace"), str(path))


def iter_files(paths: Iterable[Path]) -> Iterator[Path]:
    for entry in paths:
        if entry.is_dir():
            for child in sorted(entry.rglob("*")):
                if any(part in SKIP_DIRS for part in child.parts):
                    continue
                if child.is_file() and not child.is_symlink():
                    yield child
        elif entry.is_file() and not entry.is_symlink():
            yield entry


def forbidden_file_findings(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path.name == ".env.example":
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in FORBIDDEN_NAMES):
            findings.append(Finding("forbidden-file", str(path), 0, path.name))
    return findings


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for file_path in iter_files(paths):
        findings.extend(scan_file(file_path))
    return findings


GitRunner = Callable[[Sequence[str]], str]


def _git(args: Sequence[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False, timeout=30)
    if proc.returncode != 0:
        raise SecretLeakError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def git_files(mode: str, runner: GitRunner = _git) -> list[Path]:
    if mode == "staged":
        out = runner(["diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"])
    elif mode == "tracked":
        out = runner(["ls-files", "-z"])
    else:
        raise SecretLeakError(f"unknown git mode {mode!r}")
    return [Path(name) for name in out.split("\x00") if name]


def scan_git(mode: str, runner: GitRunner = _git) -> list[Finding]:
    files = git_files(mode, runner)
    return forbidden_file_findings(files) + scan_paths(files)


def format_findings(findings: Sequence[Finding]) -> str:
    return "\n".join(f"{item.path}:{item.line}: [{item.rule}] {item.snippet}" for item in findings)
