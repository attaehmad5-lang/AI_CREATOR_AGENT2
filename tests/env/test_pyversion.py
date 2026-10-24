from pathlib import Path

import pytest

from ai_creator_agent.env.errors import PythonVersionError, VirtualEnvError
from ai_creator_agent.env.pyversion import (
    check_python_version, enforce_python_version, in_virtualenv,
    parse_exact_version, read_pinned_version, validate_virtualenv,
)


@pytest.mark.parametrize("text,expected", [("3.11.8", (3, 11, 8)), (" 3.12.0\n", (3, 12, 0)), ("3.10.14", (3, 10, 14))])
def test_parse_exact_valid(text, expected):
    assert parse_exact_version(text) == expected


@pytest.mark.parametrize("text", ["3.11", "3.11.*", "v3.11.8", "3.11.8rc1", "", "3.11.8.1", "three"])
def test_parse_exact_rejects_loose_pins(text):
    with pytest.raises(PythonVersionError):
        parse_exact_version(text)


def test_read_pin_skips_comments_and_blanks(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("# pinned\n\n3.11.8\n")
    assert read_pinned_version(pin) == (3, 11, 8)


def test_read_pin_empty_file(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("# nothing\n")
    with pytest.raises(PythonVersionError):
        read_pinned_version(pin)


def test_read_pin_missing_file(tmp_path):
    with pytest.raises(PythonVersionError):
        read_pinned_version(tmp_path / "absent")


def test_strict_patch_mismatch_fails():
    assert not check_python_version((3, 11, 8), (3, 11, 9)).ok


def test_strict_exact_match_passes():
    assert check_python_version((3, 11, 8), (3, 11, 8)).ok


def test_non_strict_allows_patch_drift():
    assert check_python_version((3, 11, 8), (3, 11, 2), strict_patch=False).ok


def test_non_strict_rejects_minor_drift():
    assert not check_python_version((3, 11, 8), (3, 12, 0), strict_patch=False).ok


def test_enforce_raises_on_mismatch(tmp_path):
    pin = tmp_path / "pin"
    pin.write_text("3.11.8\n")
    with pytest.raises(PythonVersionError):
        enforce_python_version(pin, running=(3, 10, 0))


def test_enforce_returns_result(tmp_path):
    pin = tmp_path / "pin"
    pin.write_text("3.11.8\n")
    assert enforce_python_version(pin, running=(3, 11, 8)).ok


def test_in_virtualenv_true_and_false(tmp_path):
    assert in_virtualenv(str(tmp_path / "v"), str(tmp_path / "base"))
    assert not in_virtualenv(str(tmp_path), str(tmp_path))


def test_validate_not_in_venv_raises(tmp_path):
    with pytest.raises(VirtualEnvError):
        validate_virtualenv(None, {}, str(tmp_path), str(tmp_path))


def test_validate_declared_mismatch_raises(tmp_path):
    env = {"VIRTUAL_ENV": str(tmp_path / "other")}
    with pytest.raises(VirtualEnvError):
        validate_virtualenv(None, env, str(tmp_path / "v"), str(tmp_path / "b"))


def test_validate_expected_mismatch_raises(tmp_path):
    with pytest.raises(VirtualEnvError):
        validate_virtualenv(tmp_path / "x", {}, str(tmp_path / "v"), str(tmp_path / "b"))


def test_validate_success_returns_prefix(tmp_path):
    venv = tmp_path / "v"
    env = {"VIRTUAL_ENV": str(venv)}
    got = validate_virtualenv(venv, env, str(venv), str(tmp_path / "b"))
    assert got == Path(venv).resolve()
