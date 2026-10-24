import os
import time
from pathlib import Path
import pytest
from ai_creator_agent.env.errors import WorkspaceError
from ai_creator_agent.env.ephemeral import MARKER, EphemeralWorkspace, sweep_stale

def ws(tmp_path, **kw):
    return EphemeralWorkspace(tmp_path / "root", register_atexit=False, **kw)

def test_create_is_private_and_marked(tmp_path):
    w = ws(tmp_path)
    path = w.create()
    assert (path / MARKER).read_text() == str(os.getpid())
    assert (path.stat().st_mode & 0o077) == 0
    w.cleanup()

def test_cleanup_removes_and_is_idempotent(tmp_path):
    w = ws(tmp_path)
    path = w.create()
    (path / "a.bin").write_bytes(b"x" * 10)
    assert w.cleanup() is True and not path.exists()
    assert w.cleanup() is True

def test_context_manager_cleans_on_exception(tmp_path):
    w = ws(tmp_path)
    with pytest.raises(RuntimeError):
        with w as path:
            created = path
            raise RuntimeError("boom")
    assert not created.exists()

def test_path_before_create_raises(tmp_path):
    with pytest.raises(WorkspaceError):
        ws(tmp_path).path

def test_create_twice_returns_same(tmp_path):
    w = ws(tmp_path)
    assert w.create() == w.create()
    w.cleanup()

def test_new_path_unique_and_rejects_separators(tmp_path):
    w = ws(tmp_path)
    w.create()
    assert w.new_path(".png") != w.new_path(".png")
    for bad in ("/x", "..\\x"):
        with pytest.raises(WorkspaceError):
            w.new_path(bad)
    w.cleanup()

def test_usage_and_capacity(tmp_path):
    w = ws(tmp_path, max_bytes=100)
    path = w.create()
    (path / "f").write_bytes(b"x" * 60)
    assert w.usage_bytes() >= 60
    w.ensure_capacity(10)
    with pytest.raises(WorkspaceError):
        w.ensure_capacity(50)
    w.cleanup()

def test_no_cap_never_raises(tmp_path):
    w = ws(tmp_path)
    w.create()
    w.ensure_capacity(10**12)
    w.cleanup()

@pytest.mark.parametrize("root", ["/", "/tmp"])
def test_unsafe_roots_rejected(root):
    with pytest.raises(WorkspaceError):
        EphemeralWorkspace(Path(root), register_atexit=False).create()

def test_invalid_constructor_args(tmp_path):
    with pytest.raises(WorkspaceError):
        EphemeralWorkspace(tmp_path / "r", prefix="a/b")
    with pytest.raises(WorkspaceError):
        EphemeralWorkspace(tmp_path / "r", max_bytes=0)

def make_dir(root, name, owner=None, age=0):
    d = root / name
    d.mkdir(parents=True)
    if owner is not None:
        (d / MARKER).write_text(str(owner))
    if age:
        old = time.time() - age
        os.utime(d, (old, old))
    return d

def test_sweep_removes_dead_owner_keeps_live(tmp_path):
    root = tmp_path / "root"
    dead = make_dir(root, "aica-dead", owner=111)
    live = make_dir(root, "aica-live", owner=222)
    removed = sweep_stale(root, pid_alive=lambda pid: pid == 222)
    assert removed == [dead] and live.exists()

def test_sweep_unknown_owner_respects_ttl(tmp_path):
    root = tmp_path / "root"
    old = make_dir(root, "aica-old", age=1000)
    young = make_dir(root, "aica-young", age=1)
    removed = sweep_stale(root, ttl_seconds=100)
    assert removed == [old] and young.exists()

def test_sweep_ignores_foreign_names_and_files(tmp_path):
    root = tmp_path / "root"
    foreign = make_dir(root, "other-dir", owner=1)
    (root / "aica-file").write_text("x")
    assert sweep_stale(root, pid_alive=lambda p: False) == [] and foreign.exists()

def test_sweep_ignores_symlinks(tmp_path):
    root = tmp_path / "root"
    target = make_dir(tmp_path, "precious", owner=1)
    root.mkdir()
    os.symlink(target, root / "aica-link")
    assert sweep_stale(root, pid_alive=lambda p: False) == [] and target.exists()

def test_sweep_missing_root(tmp_path):
    assert sweep_stale(tmp_path / "nope") == []

def test_sweep_corrupt_marker_treated_unknown(tmp_path):
    root = tmp_path / "root"
    d = make_dir(root, "aica-bad")
    (d / MARKER).write_text("not-a-pid")
    old = time.time() - 1000
    os.utime(d, (old, old))
    assert sweep_stale(root, ttl_seconds=100) == [d]
