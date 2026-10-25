import json
import os
import sys
from types import SimpleNamespace

import pytest

from ai_creator_agent.env.diagnostics import DiagnosticConfig, DiagnosticSuite, Status
from ai_creator_agent.env.errors import ResourceLimitError
from ai_creator_agent.env.hardware import Probes
from ai_creator_agent.env.resources import MemorySnapshot

MB = 1024 * 1024
RUNNING = ".".join(str(p) for p in sys.version_info[:3])


def cpu_probes():
    return Probes(
        system=lambda: "Linux",
        machine=lambda: "x86_64",
        which=lambda n: None,
        run=lambda c: None,
        torch=lambda: None,
        environ={},
    )


def pin_file(tmp_path, text=RUNNING):
    path = tmp_path / ".python-version"
    path.write_text(text + "\n")
    return path


def suite(tmp_path, free_mb=8000, disk_mb=50_000, **cfg):
    base = {
        "pin_file": cfg.pop("pin_file", None) or pin_file(tmp_path),
        "required_dirs": (tmp_path / "data", tmp_path / "tmp"),
        "probes": cpu_probes(),
        "require_venv": False,
    }
    base.update(cfg)
    return DiagnosticSuite(
        DiagnosticConfig(**base),
        memory_reader=lambda: MemorySnapshot(16000 * MB, free_mb * MB, 100 * MB),
        disk_usage=lambda p: SimpleNamespace(free=disk_mb * MB),
        which=lambda n: f"/usr/bin/{n}",
        cli_runner=lambda p, a: "tool version 99.0.0",
    )


def one(report, name):
    return next(r for r in report.results if r.name == name)


def test_healthy_system_passes(tmp_path):
    report = suite(tmp_path).run()
    assert report.ok and report.exit_code == 0
    assert "healthy" in report.render_text()


def test_python_pin_mismatch_fails(tmp_path):
    assert (
        one(
            suite(tmp_path, pin_file=pin_file(tmp_path, "2.7.18")).run(), "python"
        ).status
        is Status.FAIL
    )


def test_python_patch_drift_tolerated_when_not_strict(tmp_path):
    major, minor, patch = sys.version_info[:3]
    s = suite(
        tmp_path,
        pin_file=pin_file(tmp_path, f"{major}.{minor}.{patch + 1}"),
        strict_patch=False,
    )
    assert one(s.run(), "python").status is Status.PASS


def test_missing_pin_file_is_failure_not_crash(tmp_path):
    assert (
        one(suite(tmp_path, pin_file=tmp_path / "absent").run(), "python").status
        is Status.FAIL
    )


def test_venv_not_required_warns_or_passes(tmp_path):
    assert one(suite(tmp_path).run(), "virtualenv").status in (Status.PASS, Status.WARN)


def test_venv_required_fails_outside_venv(tmp_path, monkeypatch):
    import ai_creator_agent.env.diagnostics as diag

    monkeypatch.setattr(diag, "in_virtualenv", lambda: False)
    assert (
        one(suite(tmp_path, require_venv=True).run(), "virtualenv").status
        is Status.FAIL
    )


def test_memory_fail_below_minimum(tmp_path):
    assert one(suite(tmp_path, free_mb=100).run(), "memory").status is Status.FAIL


def test_memory_warn_when_close_to_minimum(tmp_path):
    assert one(suite(tmp_path, free_mb=800).run(), "memory").status is Status.WARN


def test_memory_warn_when_cap_exceeds_physical(tmp_path):
    assert one(suite(tmp_path, max_ram_mb=64_000).run(), "memory").status is Status.WARN


def test_memory_reader_error_becomes_fail(tmp_path):
    s = suite(tmp_path)
    s._memory_reader = lambda: (_ for _ in ()).throw(ResourceLimitError("no /proc"))
    assert one(s.run(), "memory").status is Status.FAIL


def test_paths_created_and_writable(tmp_path):
    report = suite(tmp_path).run()
    assert one(report, "paths").status is Status.PASS and (tmp_path / "data").is_dir()


def test_paths_missing_not_created_fails(tmp_path):
    assert (
        one(suite(tmp_path, create_missing_dirs=False).run(), "paths").status
        is Status.FAIL
    )


def test_paths_file_in_place_of_directory(tmp_path):
    (tmp_path / "data").write_text("x")
    assert one(suite(tmp_path).run(), "paths").status is Status.FAIL


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs non-root")
def test_paths_unwritable_directory(tmp_path):
    (tmp_path / "data").mkdir()
    os.chmod(tmp_path / "data", 0o500)
    assert one(suite(tmp_path).run(), "paths").status is Status.FAIL
    os.chmod(tmp_path / "data", 0o700)


def test_disk_fail_when_low(tmp_path):
    assert one(suite(tmp_path, disk_mb=10).run(), "disk").status is Status.FAIL


def test_disk_with_no_dirs(tmp_path):
    assert one(suite(tmp_path, required_dirs=()).run(), "disk").status is Status.PASS


def test_disk_uses_nearest_existing_parent(tmp_path):
    probed = []
    s = suite(tmp_path, required_dirs=(tmp_path / "a" / "b" / "c",))
    s._disk_usage = lambda p: probed.append(p) or SimpleNamespace(free=10**12)
    s.run(only=["disk"])
    assert probed == [str(tmp_path)]


@pytest.mark.skipif(os.name != "posix", reason="posix modes")
def test_permissions_secret_file_levels(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("A=1")
    os.chmod(secret, 0o644)
    assert (
        one(suite(tmp_path, secret_files=(secret,)).run(), "permissions").status
        is Status.WARN
    )
    strict = suite(tmp_path, secret_files=(secret,), strict_permissions=True)
    assert one(strict.run(), "permissions").status is Status.FAIL
    os.chmod(secret, 0o600)
    assert (
        one(suite(tmp_path, secret_files=(secret,)).run(), "permissions").status
        is Status.PASS
    )


@pytest.mark.skipif(os.name != "posix", reason="posix modes")
def test_permissions_world_writable_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    os.chmod(d, 0o777)  # noqa: S103
    assert one(suite(tmp_path).run(), "permissions").status is Status.WARN


def test_hardware_cpu_only_passes(tmp_path):
    assert one(suite(tmp_path).run(), "hardware").status is Status.PASS


def test_hardware_required_accelerator_fails(tmp_path):
    assert (
        one(suite(tmp_path, require_accelerator=True).run(), "hardware").status
        is Status.FAIL
    )


def test_hardware_unavailable_preference_warns(tmp_path):
    assert (
        one(suite(tmp_path, device_preference="cuda").run(), "hardware").status
        is Status.WARN
    )


def test_cli_missing_tools_fail(tmp_path):
    s = suite(tmp_path)
    s._which = lambda n: None
    assert one(s.run(), "cli").status is Status.FAIL


def test_container_runtime_checks_only_ffmpeg(tmp_path):
    seen = []
    s = suite(tmp_path, runtime="container")
    s._which = lambda n: seen.append(n) or f"/bin/{n}"
    s.run(only=["cli"])
    assert seen == ["ffmpeg"]


def test_report_json_and_unhealthy_text(tmp_path):
    report = suite(tmp_path, free_mb=1).run()
    data = json.loads(report.to_json())
    assert data["ok"] is False and report.exit_code == 1
    assert "UNHEALTHY" in report.render_text()


def test_only_filter_limits_checks(tmp_path):
    report = suite(tmp_path).run(only=["python", "memory"])
    assert [r.name for r in report.results] == ["python", "memory"]
