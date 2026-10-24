"""Multi-profile environment engine (dev / test / staging / prod)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from .envfile import load_env_file
from .errors import ConfigError, EnvFileError

PREFIX = "AI_CREATOR_"


class Profile(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


_ALIASES = {
    "development": "dev",
    "testing": "test",
    "stage": "staging",
    "production": "prod",
}


def _defaults(**values: str) -> dict[str, str]:
    return {f"{PREFIX}{key.upper()}": value for key, value in values.items()}


PROFILE_DEFAULTS: dict[Profile, dict[str, str]] = {
    Profile.DEV: _defaults(log_level="DEBUG", debug="true", max_ram_mb="8192", hot_reload_enabled="true"),
    Profile.TEST: _defaults(log_level="WARNING", debug="false", max_ram_mb="2048", tmp_ttl_seconds="60", hot_reload_enabled="false"),
    Profile.STAGING: _defaults(log_level="INFO", debug="false", max_ram_mb="16384", hot_reload_enabled="true"),
    Profile.PROD: _defaults(log_level="INFO", debug="false", max_ram_mb="32768", hot_reload_enabled="true"),
}


def resolve_profile(value: str | Profile | None = None, environ: Mapping[str, str] | None = None) -> Profile:
    """Resolve explicit value > AI_CREATOR_PROFILE > dev."""
    if isinstance(value, Profile):
        return value
    env = os.environ if environ is None else environ
    raw = value or env.get(f"{PREFIX}PROFILE") or "dev"
    name = _ALIASES.get(raw.strip().lower(), raw.strip().lower())
    try:
        return Profile(name)
    except ValueError:
        valid = ", ".join(item.value for item in Profile)
        raise ConfigError(f"unknown profile {raw!r}; valid: {valid}") from None


def profile_env_files(profile: Profile, root: Path) -> list[Path]:
    """Ascending precedence: .env < .env.<profile> < .env.local (dev only)."""
    files = [root / ".env", root / f".env.{profile.value}"]
    if profile is Profile.DEV:
        files.append(root / ".env.local")
    return files


def load_profile_environment(profile: Profile, root: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """defaults < files < real process environment (AI_CREATOR_* only)."""
    env = os.environ if environ is None else environ
    merged: dict[str, str] = dict(PROFILE_DEFAULTS[profile])
    for path in profile_env_files(profile, root):
        try:
            merged.update(load_env_file(path, environ=env, missing_ok=True))
        except EnvFileError as exc:
            raise ConfigError(f"invalid profile environment file {path}: {exc}") from exc
    for key, value in env.items():
        if key.startswith(PREFIX):
            merged[key] = value
    merged[f"{PREFIX}PROFILE"] = profile.value
    return merged
