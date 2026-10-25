import pytest

from ai_creator_agent.env.cli import main


def test_scan_secrets_clean_directory(tmp_path):
    (tmp_path / "ok.py").write_text("print('hello')\n")
    assert main(["scan-secrets", str(tmp_path)]) == 0


def test_scan_secrets_detects_leak(tmp_path):
    (tmp_path / "leak.py").write_text("k = '" + "AKIA" + "ZQ4M7XK2PL9TB3WN" + "'\n")
    assert main(["scan-secrets", str(tmp_path)]) == 1


def test_hardware_command_runs():
    assert main(["hardware"]) == 0


def test_hardware_invalid_preference_returns_2():
    assert main(["hardware", "--preference", "tpu"]) == 2


def test_hardware_strict_unavailable_returns_2():
    assert main(["hardware", "--preference", "mps", "--strict"]) == 2


def test_unknown_runtime_rejected_by_argparse():
    with pytest.raises(SystemExit) as info:
        main(["preflight", "--runtime", "mainframe"])
    assert info.value.code == 2


def test_missing_subcommand_rejected():
    with pytest.raises(SystemExit):
        main([])



def test_show_settings_emits_safe_json(tmp_path, capsys):
    import json

    assert main(["show-settings", "--profile", "dev", "--root", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "dev"
    assert "openai_api_key" in output


def test_diagnose_json_renders_report(monkeypatch, tmp_path, capsys):
    from ai_creator_agent.env.diagnostics import DiagnosticSuite

    class Report:
        exit_code = 1

        def to_json(self):
            return '{"status":"warning"}'

        def render_text(self):
            return "diagnostic report"

    monkeypatch.setattr(DiagnosticSuite, "run", lambda self, only=None: Report())
    assert main(["diagnose", "--json", "--profile", "dev", "--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out.strip() == '{"status":"warning"}'


def test_healthcheck_runs_only_health_checks(monkeypatch, tmp_path, capsys):
    from ai_creator_agent.env.cli import HEALTH_CHECKS
    from ai_creator_agent.env.diagnostics import DiagnosticSuite

    calls = []

    class Report:
        exit_code = 0

        def render_text(self):
            return "healthy"

    def fake_run(self, only=None):
        calls.append(only)
        return Report()

    monkeypatch.setattr(DiagnosticSuite, "run", fake_run)
    assert main(["healthcheck", "--profile", "dev", "--root", str(tmp_path)]) == 0
    assert calls == [HEALTH_CHECKS]
    assert capsys.readouterr().out.strip() == "healthy"


def test_preflight_returns_failure_when_requirement_missing(monkeypatch, capsys):
    from types import SimpleNamespace

    from ai_creator_agent.env import preflight

    monkeypatch.setattr(preflight, "requirements_for", lambda runtime: [])
    monkeypatch.setattr(
        preflight,
        "run_preflight",
        lambda requirements, raise_on_fail=False: [
            SimpleNamespace(ok=False, message="missing ffmpeg")
        ],
    )
    assert main(["preflight", "--runtime", "ci"]) == 1
    assert "FAIL missing ffmpeg" in capsys.readouterr().out


def test_audit_command_reports_vulnerabilities(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from ai_creator_agent.env import audit

    monkeypatch.setattr(
        audit,
        "audit_lockfile",
        lambda project, output, ignore: SimpleNamespace(
            ok=False,
            vulnerabilities=[
                SimpleNamespace(
                    package="demo",
                    version="1.0",
                    vuln_id="TEST-0001",
                    fix_versions=("1.1",),
                )
            ],
        ),
    )
    assert main(["audit", "--project", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "demo==1.0 TEST-0001 (fix: 1.1)" in output
    assert "1 vulnerabilities" in output
