"""Real-process regression tests for crash persistence and ephemeral cleanup."""

import json
import os
import subprocess
import sys
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
