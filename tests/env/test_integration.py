"""Real-process regression tests for crash persistence and ephemeral cleanup."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[2] / "src")


def child_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_unhandled_child_exception_persists_shutdown_state(tmp_path):
    state = tmp_path / "state.json"
    code = """
import pathlib
from ai_creator_agent.env.lifecycle import ShutdownCoordinator
c = ShutdownCoordinator(pathlib.Path(__import__('sys').argv[1]), lambda: {'phase': 'render'})
c.install()
raise RuntimeError('expected test crash')
"""
    proc = subprocess.run(
        [sys.executable, "-c", code, str(state)],
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1, proc.stderr
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["reason"] == "unhandled:RuntimeError"
    assert saved["state"] == {"phase": "render"}


def test_ephemeral_workspace_is_removed_after_normal_child_exit(tmp_path):
    root = tmp_path / "workspaces"
    code = """
import pathlib, sys
from ai_creator_agent.env.ephemeral import EphemeralWorkspace
workspace = EphemeralWorkspace(pathlib.Path(sys.argv[1]))
path = workspace.create()
(path / 'frame.bin').write_bytes(b'test')
print(path, flush=True)
"""
    proc = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    created = Path(proc.stdout.strip())
    assert created.is_absolute()
    assert not created.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal semantics")
def test_sigterm_child_persists_state_and_runs_cleanup_hook(tmp_path):
    import signal

    state, marker = tmp_path / "state.json", tmp_path / "hook.txt"
    code = """
import pathlib, sys, time
from ai_creator_agent.env.lifecycle import ShutdownCoordinator
state, marker = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
coordinator = ShutdownCoordinator(state, lambda: {'active_jobs': 2})
coordinator.add_hook('cleanup', lambda: marker.write_text('done', encoding='utf-8'))
coordinator.install()
print('ready', flush=True)
time.sleep(30)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(state), str(marker)],
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 128 + signal.SIGTERM
        assert marker.read_text(encoding="utf-8") == "done"
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["reason"] == "signal:SIGTERM"
        assert saved["state"] == {"active_jobs": 2}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal semantics")
@pytest.mark.parametrize("sig", [2, 15])
def test_signal_exit_persists_state_and_runs_cleanup(tmp_path, sig):
    import signal

    state, marker = tmp_path / "state.json", tmp_path / "marker.txt"
    signal_name = signal.Signals(sig).name
    code = """
import pathlib, sys, time
from ai_creator_agent.env.lifecycle import ShutdownCoordinator
state, marker = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
c = ShutdownCoordinator(state, lambda: {'jobs': 7})
c.add_hook('mark', lambda: marker.write_text('hook-ran', encoding='utf-8'))
c.install()
print('ready', flush=True)
time.sleep(30)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(state), str(marker)],
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        proc.send_signal(sig)
        assert proc.wait(timeout=10) == 128 + sig
        assert marker.read_text(encoding="utf-8") == "hook-ran"
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["state"] == {"jobs": 7}
        assert saved["reason"] == f"signal:{signal_name}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_crashed_child_leaves_workspace_for_stale_sweep(tmp_path):
    from ai_creator_agent.env.ephemeral import sweep_stale

    root = tmp_path / "workspaces"
    code = """
import os, pathlib, sys
from ai_creator_agent.env.ephemeral import EphemeralWorkspace
workspace = EphemeralWorkspace(pathlib.Path(sys.argv[1]))
path = workspace.create()
(path / 'frame.bin').write_bytes(b'test')
print(path, flush=True)
os._exit(9)
"""
    proc = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 9
    leftover = Path(proc.stdout.strip())
    assert leftover.is_dir()
    assert sweep_stale(root) == [leftover]
    assert not leftover.exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux /proc and RLIMIT semantics"
)
def test_real_memory_snapshot_and_guard_detect_growth():
    from ai_creator_agent.env.resources import (
        GuardState,
        MemoryGuard,
        read_memory_snapshot,
    )

    before = read_memory_snapshot()
    assert before.total_bytes > 0
    assert 0 < before.rss_bytes < before.total_bytes
    ballast = bytearray(24 * 1024 * 1024)
    for offset in range(0, len(ballast), 4096):
        ballast[offset] = 1
    fired = []
    guard = MemoryGuard(
        before.rss_bytes + 8 * 1024 * 1024,
        reader=read_memory_snapshot,
        on_exceed=fired.append,
    )
    assert guard.check_once() is GuardState.EXCEEDED
    assert len(fired) == 1
    del ballast

def test_unhandled_exception_persists_shutdown_state(tmp_path):
    state = tmp_path / "shutdown.json"
    code = """
import pathlib, sys
from ai_creator_agent.env.lifecycle import ShutdownCoordinator
coordinator = ShutdownCoordinator(pathlib.Path(sys.argv[1]), lambda: {"phase": "render"})
coordinator.install()
raise RuntimeError("expected child failure")
"""
    proc = subprocess.run(
        [sys.executable, "-c", code, str(state)],
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["reason"] == "unhandled:RuntimeError"
    assert saved["state"] == {"phase": "render"}


def test_real_cli_secret_scan_exit_codes(tmp_path):
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    (clean / "plain.py").write_text("value = 1\\n", encoding="utf-8")
    (dirty / "credential.py").write_text(
        "key = '" + "AKIA" + "ZQ4M7XK2PL9TB3WN" + "'\\n", encoding="utf-8"
    )
    command = [sys.executable, "-m", "ai_creator_agent.env", "scan-secrets"]
    good = subprocess.run(
        [*command, str(clean)], env=child_env(), capture_output=True, timeout=10
    )
    bad = subprocess.run(
        [*command, str(dirty)], env=child_env(), capture_output=True, timeout=10
    )
    assert good.returncode == 0
    assert bad.returncode == 1


def test_hot_reload_only_changes_allowlisted_environment_values(tmp_path):
    from ai_creator_agent.env.envfile import load_env_file
    from ai_creator_agent.env.hotreload import HotReloader

    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=INFO\\nPORT=8000\\n", encoding="utf-8")
    def loader():
        return load_env_file(env_file, environ={})
    reloader = HotReloader(loader, loader(), {"LOG_LEVEL"}, watch_files=[env_file])
    env_file.write_text("LOG_LEVEL=DEBUG\\nPORT=9000\\n", encoding="utf-8")
    os.utime(env_file, (time.time() + 5, time.time() + 5))
    result = reloader.poll_once()
    assert reloader.get("LOG_LEVEL") == "DEBUG"
    assert reloader.get("PORT") == "8000"
    assert result.rejected == ("PORT",)
    env_file.write_text('LOG_LEVEL="unterminated\\n', encoding="utf-8")
    os.utime(env_file, (time.time() + 10, time.time() + 10))
    broken = reloader.poll_once()
    assert broken.error
    assert reloader.get("LOG_LEVEL") == "DEBUG"

