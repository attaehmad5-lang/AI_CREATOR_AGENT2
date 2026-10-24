"""Strict .env parser.

Grammar: one assignment per line, KEY=VALUE. Double quotes support escapes;
single quotes are literal; bare values may not contain whitespace or quotes.
${VAR} and ${VAR:-default} are interpolated in bare and double-quoted values.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

from .errors import EnvFileError

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTERP_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


def _find_closing_quote(raw: str, quote: str) -> int:
    index = 1
    while index < len(raw):
        char = raw[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            return index
        index += 1
    return -1


def _unescape(inner: str, where: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(inner):
        char = inner[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= len(inner):
            raise EnvFileError(f"{where}: dangling backslash")
        escaped = inner[index + 1]
        if escaped not in _ESCAPES:
            raise EnvFileError(f"{where}: unknown escape \\{escaped}")
        out.append(_ESCAPES[escaped])
        index += 2
    return "".join(out)


def _parse_value(raw: str, where: str) -> tuple[str, bool]:
    if not raw:
        return "", False
    quote = raw[0]
    if quote in "\"'":
        end = _find_closing_quote(raw, quote)
        if end == -1:
            raise EnvFileError(f"{where}: unterminated quote")
        rest = raw[end + 1 :].strip()
        if rest and not rest.startswith("#"):
            raise EnvFileError(f"{where}: unexpected text after closing quote")
        inner = raw[1:end]
        if quote == '"':
            return _unescape(inner, where), True
        return inner, False
    comment = re.search(r"\s#", raw)
    bare = raw[: comment.start()] if comment else raw
    bare = bare.strip()
    if any(char in bare for char in "\"'"):
        raise EnvFileError(f"{where}: quote inside unquoted value")
    if re.search(r"\s", bare):
        raise EnvFileError(f"{where}: whitespace in unquoted value; add quotes")
    return bare, True


def _interpolate(
    value: str, resolved: Mapping[str, str], environ: Mapping[str, str], where: str
) -> str:
    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in resolved:
            return resolved[name]
        if name in environ:
            return environ[name]
        if default is not None:
            return default
        raise EnvFileError(f"{where}: undefined variable ${{{name}}}")

    return _INTERP_RE.sub(replace, value)


def parse_env_text(
    text: str,
    source: str = "<string>",
    environ: Mapping[str, str] | None = None,
    interpolate: bool = True,
) -> dict[str, str]:
    env = os.environ if environ is None else environ
    if "\x00" in text:
        raise EnvFileError(f"{source}: NUL byte in input")
    if text.startswith("\ufeff"):
        text = text[1:]
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        where = f"{source}:{lineno}"
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw = stripped.partition("=")
        if not separator:
            raise EnvFileError(f"{where}: expected KEY=VALUE")
        key = key.strip()
        if not _KEY_RE.match(key):
            raise EnvFileError(f"{where}: invalid key {key!r}")
        if key in result:
            raise EnvFileError(f"{where}: duplicate key {key}")
        value, can_interpolate = _parse_value(raw.strip(), where)
        if can_interpolate and interpolate:
            value = _interpolate(value, result, env, where)
        result[key] = value
    return result


def load_env_file(
    path: Path,
    environ: Mapping[str, str] | None = None,
    missing_ok: bool = False,
) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise EnvFileError(f"{path}: file not found") from None
    except OSError as exc:
        raise EnvFileError(f"{path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EnvFileError(f"{path}: not valid UTF-8: {exc}") from exc
    return parse_env_text(text, source=str(path), environ=environ)


def is_private_file(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0
