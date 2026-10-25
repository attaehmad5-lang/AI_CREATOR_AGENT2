import pytest

from ai_creator_agent.env.errors import ConfigError
from ai_creator_agent.env.profiles import (
    PROFILE_DEFAULTS,
    Profile,
    load_profile_environment,
    profile_env_files,
    resolve_profile,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("dev", Profile.DEV),
        ("Development", Profile.DEV),
        ("testing", Profile.TEST),
        ("STAGE", Profile.STAGING),
        ("production", Profile.PROD),
    ],
)
def test_resolve_aliases(raw, expected):
    assert resolve_profile(raw, {}) is expected


def test_resolve_default_is_dev():
    assert resolve_profile(None, {}) is Profile.DEV


def test_resolve_from_environment():
    assert resolve_profile(None, {"AI_CREATOR_PROFILE": "prod"}) is Profile.PROD


def test_resolve_explicit_beats_environment():
    assert resolve_profile("test", {"AI_CREATOR_PROFILE": "prod"}) is Profile.TEST


def test_resolve_invalid_raises():
    with pytest.raises(ConfigError, match="valid"):
        resolve_profile("qa", {})


def test_resolve_enum_passthrough():
    assert resolve_profile(Profile.PROD, {}) is Profile.PROD


def test_env_files_dev_includes_local(tmp_path):
    names = [p.name for p in profile_env_files(Profile.DEV, tmp_path)]
    assert names == [".env", ".env.dev", ".env.local"]


def test_env_files_prod_excludes_local(tmp_path):
    names = [p.name for p in profile_env_files(Profile.PROD, tmp_path)]
    assert names == [".env", ".env.prod"]


def test_precedence_defaults_files_process(tmp_path):
    (tmp_path / ".env").write_text(
        "AI_CREATOR_LOG_LEVEL=ERROR\nAI_CREATOR_DEBUG=true\n"
    )
    (tmp_path / ".env.prod").write_text("AI_CREATOR_LOG_LEVEL=CRITICAL\n")
    env = {"AI_CREATOR_DEBUG": "false"}
    merged = load_profile_environment(Profile.PROD, tmp_path, env)
    assert merged["AI_CREATOR_LOG_LEVEL"] == "CRITICAL"
    assert merged["AI_CREATOR_DEBUG"] == "false"
    assert merged["AI_CREATOR_MAX_RAM_MB"] == "32768"
    assert merged["AI_CREATOR_PROFILE"] == "prod"


def test_prod_ignores_env_local(tmp_path):
    (tmp_path / ".env.local").write_text("AI_CREATOR_LOG_LEVEL=DEBUG\n")
    merged = load_profile_environment(Profile.PROD, tmp_path, {})
    assert merged["AI_CREATOR_LOG_LEVEL"] == "INFO"


def test_non_prefixed_process_env_not_leaked(tmp_path):
    merged = load_profile_environment(Profile.DEV, tmp_path, {"PATH": "/bin"})
    assert "PATH" not in merged


def test_every_profile_has_defaults():
    assert set(PROFILE_DEFAULTS) == set(Profile)


def test_malformed_profile_file_raises(tmp_path):
    (tmp_path / ".env.dev").write_text("not valid\n")
    with pytest.raises(ConfigError):
        load_profile_environment(Profile.DEV, tmp_path, {})
