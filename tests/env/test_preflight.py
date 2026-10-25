import pytest

from ai_creator_agent.env.errors import PreflightError
from ai_creator_agent.env.preflight import (
    CliRequirement,
    check_cli,
    parse_version,
    requirements_for,
    run_preflight,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("git version 2.43.0", (2, 43, 0)),
        ("ffmpeg version 6.1.1-3ubuntu5", (6, 1, 1)),
        ("tar (GNU tar) 1.35", (1, 35)),
        ("curl 7.81.0 (x86_64)", (7, 81, 0)),
        ("nothing here", None),
        ("", None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def _which(known):
    return lambda name: known.get(name)


def test_missing_tool():
    result = check_cli(CliRequirement("git", (2, 30)), _which({}), lambda p, a: "")
    assert not result.ok and "not found" in result.message


def test_too_old():
    result = check_cli(
        CliRequirement("git", (2, 30)),
        _which({"git": "/usr/bin/git"}),
        lambda p, a: "git version 2.20.1",
    )
    assert not result.ok and result.version == (2, 20, 1)


def test_version_ok():
    result = check_cli(
        CliRequirement("git", (2, 30)),
        _which({"git": "/g"}),
        lambda p, a: "git version 2.30.0",
    )
    assert result.ok


def test_unparseable_with_minimum_fails():
    result = check_cli(
        CliRequirement("ffmpeg", (4, 4)),
        _which({"ffmpeg": "/f"}),
        lambda p, a: "ffmpeg version N-1234-gabc",
    )
    assert not result.ok


def test_runner_failure_is_reported():
    result = check_cli(CliRequirement("tar"), _which({"tar": "/t"}), lambda p, a: None)
    assert not result.ok


def test_no_minimum_only_needs_presence():
    result = check_cli(CliRequirement("tar"), _which({"tar": "/t"}), lambda p, a: "x")
    assert result.ok


def test_run_preflight_raises_with_all_failures():
    with pytest.raises(PreflightError, match=r"git.*ffmpeg|ffmpeg.*git"):
        run_preflight(
            (CliRequirement("git"), CliRequirement("ffmpeg")),
            _which({}),
            lambda p, a: "",
        )


def test_run_preflight_collects_without_raising():
    out = run_preflight(
        (CliRequirement("git"),), _which({}), lambda p, a: "", raise_on_fail=False
    )
    assert len(out) == 1 and not out[0].ok


def test_requirements_for_container_is_ffmpeg_only():
    assert [r.name for r in requirements_for("container")] == ["ffmpeg"]


def test_requirements_for_local_has_four_tools():
    assert {r.name for r in requirements_for("local")} == {
        "git",
        "ffmpeg",
        "curl",
        "tar",
    }


def test_requirements_for_unknown_runtime():
    with pytest.raises(PreflightError):
        requirements_for("mainframe")


def test_ffmpeg_uses_single_dash_version_flag():
    from ai_creator_agent.env.preflight import FULL_REQUIREMENTS

    ffmpeg = next(r for r in FULL_REQUIREMENTS if r.name == "ffmpeg")
    assert ffmpeg.version_args == ("-version",)
    assert requirements_for("container")[0].version_args == ("-version",)


def test_real_ffmpeg_reports_version_when_installed():
    import shutil

    if shutil.which("ffmpeg") is None:
        return
    assert check_cli(requirements_for("container")[0]).ok
