import os
from pathlib import Path

import pytest

from ai_creator_agent.env.errors import SecretLeakError
from ai_creator_agent.env.secretscan import (
    forbidden_file_findings,
    format_findings,
    git_files,
    iter_files,
    redact,
    scan_file,
    scan_git,
    scan_paths,
    scan_text,
    shannon_entropy,
)

AWS = "AKIA" + "ZQ4M7XK2PL9TB3WN"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SLACK = "xoxb-" + "123456789012-abcdefghijklmnop"
GOOGLE = "AIza" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx"[:35]
OPENAI = "sk-" + "proj-A1b2C3d4E5f6G7h8I9j0K1"
ANTHROPIC = "sk-ant-" + "api03-A1b2C3d4E5f6G7h8I9j0K1"
STRIPE = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
JWT = (
    "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".dBjftJeZ4CVPmB92K27uhb"
)
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"


def test_google_fixture_length():
    assert len(GOOGLE) == 39


@pytest.mark.parametrize(
    "secret,rule",
    [
        (AWS, "aws-access-key"),
        (GITHUB, "github-token"),
        (SLACK, "slack-token"),
        (GOOGLE, "google-api-key"),
        (OPENAI, "openai-key"),
        (ANTHROPIC, "anthropic-key"),
        (STRIPE, "stripe-key"),
        (JWT, "jwt"),
        (PEM, "private-key"),
    ],
)
def test_detects_known_formats(secret, rule):
    findings = scan_text(f"value = {secret}\n")
    assert [f.rule for f in findings] == [rule]


def test_findings_never_contain_full_secret():
    findings = scan_text(f"token {GITHUB}")
    assert GITHUB not in format_findings(findings)
    assert findings[0].snippet == "ghp_***"


def test_line_numbers_are_accurate():
    findings = scan_text(f"ok\nok\nx = {AWS}\n")
    assert findings[0].line == 3


def test_generic_assignment_high_entropy_flagged():
    line = 'api_key = "Zk3p9Qw7Lm2Xv8Rt4Yb6Nc1Hd5"'
    assert scan_text(line)[0].rule == "generic-assignment"


@pytest.mark.parametrize(
    "line",
    [
        'api_key = "your_key_here_please_1234"',
        'password = "aaaaaaaaaaaaaaaaaaaa"',
        "token: short",
        'secret = "changeme-changeme-123"',
        "API_KEY=<paste-key-here-1234567890>",
        "password = ${DB_PASSWORD_VALUE_123}",
    ],
)
def test_placeholders_and_low_entropy_ignored(line):
    assert scan_text(line) == []


def test_allow_pragma_suppresses():
    assert scan_text(f"x = {AWS}  # secret-scan: allow") == []


def test_multiple_findings_on_separate_lines():
    assert len(scan_text(f"{AWS}\n{GITHUB}\n")) == 2


def test_entropy_values():
    assert shannon_entropy("") == 0.0
    assert shannon_entropy("aaaa") == 0.0
    assert abs(shannon_entropy("ab") - 1.0) < 1e-9


def test_redact_short_values():
    assert redact("abc") == "***" and redact("abcdefgh") == "abcd***"


def test_scan_file_skips_binary(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x00\x01" + AWS.encode())
    assert scan_file(path) == []


def test_scan_file_skips_oversized(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text(AWS + "\n" + "a" * 1_000_100)
    assert scan_file(path) == []


def test_scan_file_reports_path(tmp_path):
    path = tmp_path / "cfg.py"
    path.write_text(f"KEY = '{AWS}'\n")
    assert scan_file(path)[0].path == str(path)


def test_iter_files_skips_vcs_and_venv_and_symlinks(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text(AWS)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text(AWS)
    (tmp_path / "real.py").write_text("x")
    os.symlink(tmp_path / "real.py", tmp_path / "link.py")
    assert [p.name for p in iter_files([tmp_path])] == ["real.py"]


def test_scan_paths_directory(tmp_path):
    (tmp_path / "a.py").write_text(f"k='{GITHUB}'")
    (tmp_path / "b.py").write_text("print('hi')")
    assert len(scan_paths([tmp_path])) == 1


@pytest.mark.parametrize(
    "name,flagged",
    [
        (".env", True),
        (".env.prod", True),
        ("server.pem", True),
        ("id_rsa", True),
        (".env.example", False),
        ("config.py", False),
    ],
)
def test_forbidden_filenames(name, flagged):
    assert bool(forbidden_file_findings([Path(name)])) is flagged


def test_git_files_parses_nul_separated_output():
    def runner(args):
        return "a.py\x00dir/b.py\x00"

    assert git_files("staged", runner) == [Path("a.py"), Path("dir/b.py")]


def test_git_unknown_mode():
    with pytest.raises(SecretLeakError):
        git_files("bogus", lambda a: "")


def test_scan_git_flags_forbidden_file_even_if_clean(tmp_path):
    findings = scan_git("tracked", lambda a: ".env\x00")
    assert findings[0].rule == "forbidden-file"


def test_type_annotations_are_not_secrets():
    line = "    file_secret_settings: PydanticBaseSettingsSource,"
    assert scan_text(line) == []


def test_project_source_scans_clean():
    root = Path(__file__).resolve().parents[2]
    assert scan_paths([root / "src"]) == []
