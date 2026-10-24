import pytest
from pydantic import ValidationError

pytest.importorskip("pydantic_settings")

from ai_creator_agent.env.errors import ConfigError
from ai_creator_agent.env.settings import RELOADABLE_FIELDS, Settings

KEY = {"AI_CREATOR_OPENAI_API_KEY": "k-test-value-1234567890"}


def test_dev_defaults(tmp_path):
    s = Settings.from_profile("dev", tmp_path, {})
    assert s.log_level == "DEBUG" and s.debug is True and s.max_ram_mb == 8192


def test_unknown_key_rejected(tmp_path):
    with pytest.raises(ConfigError, match="unknown settings"):
        Settings.from_profile("dev", tmp_path, {"AI_CREATOR_LOG_LVL": "INFO"})


def test_bounds_enforced(tmp_path):
    with pytest.raises(ConfigError):
        Settings.from_profile("dev", tmp_path, {"AI_CREATOR_MAX_RAM_MB": "10"})


def test_invalid_literal_rejected(tmp_path):
    with pytest.raises(ConfigError):
        Settings.from_profile("dev", tmp_path, {"AI_CREATOR_DEVICE_PREFERENCE": "tpu"})


def test_prod_requires_provider_key(tmp_path):
    with pytest.raises(ConfigError, match="API key"):
        Settings.from_profile("prod", tmp_path, {})


def test_prod_with_key_ok(tmp_path):
    assert Settings.from_profile("prod", tmp_path, dict(KEY)).profile.value == "prod"


def test_prod_rejects_debug(tmp_path):
    env = {**KEY, "AI_CREATOR_DEBUG": "true"}
    with pytest.raises(ConfigError, match="debug"):
        Settings.from_profile("prod", tmp_path, env)


def test_prod_rejects_debug_log_level(tmp_path):
    env = {**KEY, "AI_CREATOR_LOG_LEVEL": "DEBUG"}
    with pytest.raises(ConfigError):
        Settings.from_profile("prod", tmp_path, env)


def test_blank_secret_counts_as_missing(tmp_path):
    with pytest.raises(ConfigError):
        Settings.from_profile("staging", tmp_path, {"AI_CREATOR_OPENAI_API_KEY": "  "})


def test_same_dirs_rejected(tmp_path):
    env = {"AI_CREATOR_DATA_DIR": "/srv/x", "AI_CREATOR_TMP_ROOT": "/srv/x"}
    with pytest.raises(ConfigError):
        Settings.from_profile("dev", tmp_path, env)


def test_secrets_masked_in_safe_dict(tmp_path):
    s = Settings.from_profile("prod", tmp_path, dict(KEY))
    assert "k-test-value" not in str(s.safe_dict())


def test_settings_are_frozen(tmp_path):
    s = Settings.from_profile("dev", tmp_path, {})
    with pytest.raises((ValidationError, TypeError)):
        s.log_level = "ERROR"


def test_process_env_overrides_file(tmp_path):
    (tmp_path / ".env").write_text("AI_CREATOR_MAX_CONCURRENT_JOBS=2\n")
    s = Settings.from_profile("dev", tmp_path, {"AI_CREATOR_MAX_CONCURRENT_JOBS": "9"})
    assert s.max_concurrent_jobs == 9


def test_paths_become_absolute(tmp_path):
    s = Settings.from_profile("dev", tmp_path, {})
    assert s.data_dir.is_absolute() and s.tmp_root.is_absolute()


def test_reloadable_fields_are_real_fields():
    assert set(Settings.model_fields) >= RELOADABLE_FIELDS


def test_as_mapping_contains_all_fields(tmp_path):
    s = Settings.from_profile("dev", tmp_path, {})
    assert set(s.as_mapping()) == set(Settings.model_fields)
