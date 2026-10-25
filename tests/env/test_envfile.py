import os

import pytest

from ai_creator_agent.env.envfile import (
    is_private_file,
    load_env_file,
    parse_env_text,
)
from ai_creator_agent.env.errors import EnvFileError


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A=1", {"A": "1"}),
        ("export A=1", {"A": "1"}),
        ('A="x y"', {"A": "x y"}),
        ("A='x $y'", {"A": "x $y"}),
        ('A="l\\nb"', {"A": "l\nb"}),
        ("A=val # c", {"A": "val"}),
        ("A=val#frag", {"A": "val#frag"}),
        ('A="x" # c', {"A": "x"}),
        ("A=", {"A": ""}),
        ("\ufeffA=1", {"A": "1"}),
        ("# c\n\nA=1\n", {"A": "1"}),
        ("A=1\nB=${A}2", {"A": "1", "B": "12"}),
        ("B=${NOPE:-dflt}", {"B": "dflt"}),
        ("A=1\nB='${A}'", {"A": "1", "B": "${A}"}),
    ],
)
def test_parse_valid(text, expected):
    assert parse_env_text(text, environ={}) == expected


@pytest.mark.parametrize(
    "text",
    [
        "A",
        "1A=1",
        "A B=1",
        "A=1\nA=2",
        'A="unterminated',
        "A=has space",
        'A=he"llo',
        "A='x'y",
        'A="x\\q"',
        'A="x\\"',
        "B=${NOPE}",
        "A=1\x00",
    ],
)
def test_parse_invalid_raises(text):
    with pytest.raises(EnvFileError):
        parse_env_text(text, environ={})


def test_interpolation_uses_environ():
    assert parse_env_text("A=${HOME_X}/y", environ={"HOME_X": "/h"}) == {"A": "/h/y"}


def test_interpolation_can_be_disabled():
    assert parse_env_text("A=${X}", environ={}, interpolate=False) == {"A": "${X}"}


def test_load_missing_raises(tmp_path):
    with pytest.raises(EnvFileError):
        load_env_file(tmp_path / "nope")


def test_load_missing_ok(tmp_path):
    assert load_env_file(tmp_path / "nope", missing_ok=True) == {}


def test_load_invalid_utf8(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(bytes([65, 61, 255, 254, 10]))
    with pytest.raises(EnvFileError):
        load_env_file(path)


def test_load_reports_line_numbers(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\nbad line\n")
    with pytest.raises(EnvFileError, match=r":2:"):
        load_env_file(path, environ={})


@pytest.mark.skipif(os.name != "posix", reason="posix modes")
def test_is_private_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1")
    os.chmod(path, 0o600)
    assert is_private_file(path)
    os.chmod(path, 0o644)
    assert not is_private_file(path)
    assert not is_private_file(tmp_path / "missing")
