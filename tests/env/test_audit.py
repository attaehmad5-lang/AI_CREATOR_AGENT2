import json

import pytest

from ai_creator_agent.env.audit import (
    AuditError,
    audit_lockfile,
    parse_pip_audit_json,
    run_safety,
)

REPORT = {"dependencies": [
    {"name": "ok-pkg", "version": "1.0", "vulns": []},
    {"name": "bad-pkg", "version": "0.1", "vulns": [
        {"id": "PYSEC-1", "fix_versions": ["0.2"], "aliases": ["CVE-2024-1"]},
        {"id": "PYSEC-2", "fix_versions": [], "aliases": []},
    ]},
]}


def test_parse_collects_vulnerabilities():
    report = parse_pip_audit_json(json.dumps(REPORT))
    assert not report.ok
    assert [v.vuln_id for v in report.vulnerabilities] == ["PYSEC-1", "PYSEC-2"]
    assert report.vulnerabilities[0].fix_versions == ("0.2",)


def test_ignore_by_id_or_alias():
    report = parse_pip_audit_json(json.dumps(REPORT), ignore={"CVE-2024-1", "PYSEC-2"})
    assert report.ok and set(report.ignored) == {"PYSEC-1", "PYSEC-2"}


def test_clean_report():
    assert parse_pip_audit_json('{"dependencies": []}').ok


@pytest.mark.parametrize("payload", ["not json", "[]", '{"x": 1}'])
def test_invalid_payload_raises(payload):
    with pytest.raises(AuditError):
        parse_pip_audit_json(payload)


def make_runner(uv_code=0, audit_code=0, out="{}"):
    def runner(cmd):
        if cmd[0] == "uv":
            return uv_code, "", "uv boom"
        return audit_code, out, "audit boom"
    return runner


def test_audit_lockfile_clean(tmp_path):
    assert audit_lockfile(tmp_path, tmp_path / "r.txt", runner=make_runner(out='{"dependencies": []}')).ok


def test_audit_lockfile_reports_vulns_on_exit_1(tmp_path):
    assert not audit_lockfile(tmp_path, tmp_path / "r.txt", runner=make_runner(audit_code=1, out=json.dumps(REPORT))).ok


def test_uv_export_failure(tmp_path):
    with pytest.raises(AuditError, match="uv export"):
        audit_lockfile(tmp_path, tmp_path / "r.txt", runner=make_runner(uv_code=2))


def test_pip_audit_crash(tmp_path):
    with pytest.raises(AuditError, match="pip-audit failed"):
        audit_lockfile(tmp_path, tmp_path / "r.txt", runner=make_runner(audit_code=3))


def test_safety_exit_codes():
    assert run_safety(lambda c: (0, "", "")).ok
    assert not run_safety(lambda c: (64, "", "")).ok
    with pytest.raises(AuditError):
        run_safety(lambda c: (2, "", "crash"))
