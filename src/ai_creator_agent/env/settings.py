"""Strict, type-safe settings with profile layering."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from .errors import ConfigError
from .profiles import PREFIX, Profile, load_profile_environment, resolve_profile

RELOADABLE_FIELDS: frozenset[str] = frozenset({
    "log_level", "request_timeout_s", "max_concurrent_jobs",
    "hot_reload_interval_s", "ram_warn_ratio",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=PREFIX, extra="forbid", frozen=True,
        case_sensitive=False, validate_default=True,
    )

    profile: Profile = Profile.DEV
    runtime: Literal["local", "ci", "container"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    debug: bool = False
    data_dir: Path = Path("var/data")
    tmp_root: Path = Path("var/tmp")
    max_ram_mb: int = Field(4096, ge=256, le=4_194_304)
    ram_warn_ratio: float = Field(0.85, gt=0.5, lt=1.0)
    min_free_disk_mb: int = Field(1024, ge=0)
    max_tmp_gb: float = Field(20.0, gt=0, le=10_000)
    tmp_ttl_seconds: int = Field(86_400, ge=10)
    device_preference: Literal["auto", "cuda", "rocm", "mps", "cpu"] = "auto"
    hot_reload_enabled: bool = False
    hot_reload_interval_s: float = Field(2.0, ge=0.1, le=3600)
    request_timeout_s: float = Field(60.0, gt=0, le=3600)
    max_concurrent_jobs: int = Field(4, ge=1, le=256)
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None

    @classmethod
    def settings_customise_sources(cls, settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource, env_settings: PydanticBaseSettingsSource, dotenv_settings: PydanticBaseSettingsSource, file_secret_settings: PydanticBaseSettingsSource) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)

    @field_validator("data_dir", "tmp_root", mode="after")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        if "\x00" in str(value):
            raise ValueError("path contains NUL byte")
        return Path(os.path.abspath(value.expanduser()))

    @field_validator("openai_api_key", "anthropic_api_key", "google_api_key")
    @classmethod
    def _non_blank_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            return None
        return value

    @model_validator(mode="after")
    def _cross_field_rules(self) -> Settings:
        if self.data_dir == self.tmp_root:
            raise ValueError("data_dir and tmp_root must differ")
        if self.profile in (Profile.STAGING, Profile.PROD):
            keys = (self.openai_api_key, self.anthropic_api_key, self.google_api_key)
            if not any(keys):
                raise ValueError(f"{self.profile.value} requires a provider API key")
        if self.profile is Profile.PROD:
            if self.debug:
                raise ValueError("debug must be false in prod")
            if self.log_level == "DEBUG":
                raise ValueError("log_level DEBUG is forbidden in prod")
        return self

    @classmethod
    def from_profile(cls, profile: str | Profile | None = None, root: Path | None = None, environ: Mapping[str, str] | None = None) -> Settings:
        env = dict(os.environ if environ is None else environ)
        resolved = resolve_profile(profile, env)
        merged = load_profile_environment(resolved, root or Path("."), env)
        known = set(cls.model_fields)
        values: dict[str, Any] = {}
        unknown: list[str] = []
        for key, raw in merged.items():
            if not key.startswith(PREFIX):
                continue
            name = key[len(PREFIX):].lower()
            if name == "profile":
                continue
            if name not in known:
                unknown.append(key)
                continue
            values[name] = raw
        if unknown:
            raise ConfigError(f"unknown settings: {', '.join(sorted(unknown))}")
        try:
            return cls(profile=resolved, **values)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

    def as_mapping(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in type(self).model_fields}

    def safe_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
