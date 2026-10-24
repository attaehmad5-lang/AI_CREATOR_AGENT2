import json
import signal
import sys
import threading

import pytest

from ai_creator_agent.env.lifecycle import (
    ShutdownCoordinator,
    atomic_write_json,
    load_state,
)


def test_atomic_roundtrip_leaves_no_temp_files(tmp_path):
    path = tmp_path / "s" / "state.json"
    atomic_write_json(path, {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_failed_write_preserves_previous_state(tmp_path):
    path = tmp_path / "state.json"
    atomic_write_json(path, {"ok": True})
    circular = {}
    circular["self"] = circular
    with pytest.raises(ValueError):
        atomic_write_json(path, circular)
    assert json.loads(path.read_text()) == {"ok": True}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_load_state_missing(tmp_path):
    assert load_state(tmp_path / "none.json") is None


def test_load_state_corrupt_is_quarantined(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken")
    assert load_state(path) is None
    assert (tmp_path / "state.corrupt").exists() and not path.exists()


def test_load_state_non_object_rejected(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2]")
    assert load_state(path) is None


def test_shutdown_persists_state_and_orders_hooks(tmp_path):
    calls = []
    c = ShutdownCoordinator(tmp_path / "st.json", lambda: {"jobs": 3})
    c.add_hook("late", lambda: calls.append("late"), priority=90)
    c.add_hook("early", lambda: calls.append("early"), priority=10)
    c.add_hook("mid-a", lambda: calls.append("mid-a"))
    c.add_hook("mid-b", lambda: calls.append("mid-b"))
    report = c.shutdown("test")
    assert calls == ["early", "mid-a", "mid-b", "late"]
    saved = json.loads((tmp_path / "st.json").read_text())
    assert saved["state"] == {"jobs": 3} and saved["reason"] == "test"
    assert report.state_saved and c.shutting_down


def test_hook_errors_are_isolated(tmp_path):
    ran = []
    def bad():
        raise RuntimeError("x")
    c = ShutdownCoordinator(tmp_path / "st.json")
    c.add_hook("bad", bad, 1)
    c.add_hook("good", lambda: ran.append(1), 2)
    report = c.shutdown("r")
    assert ran == [1] and "bad" in report.hook_errors


def test_shutdown_is_idempotent(tmp_path):
    count = []
    c = ShutdownCoordinator(tmp_path / "st.json")
    c.add_hook("h", lambda: count.append(1))
    assert c.shutdown("a") is c.shutdown("b")
    assert count == [1]


def test_snapshot_failure_is_recorded(tmp_path):
    def boom():
        raise RuntimeError("no state")
    c = ShutdownCoordinator(tmp_path / "st.json", boom)
    c.shutdown("r")
    assert "snapshot_error" in json.loads((tmp_path / "st.json").read_text())["state"]


def test_unwritable_state_path_reports_not_saved(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    c = ShutdownCoordinator(blocker / "state.json")
    assert c.shutdown("r").state_saved is False


def test_signal_handler_saves_and_exits_with_128_plus_signum(tmp_path):
    c = ShutdownCoordinator(tmp_path / "st.json")
    with pytest.raises(SystemExit) as info:
        c._on_signal(signal.SIGTERM, None)
    assert info.value.code == 128 + signal.SIGTERM
    assert json.loads((tmp_path / "st.json").read_text())["reason"] == "signal:SIGTERM"


def test_second_signal_forces_exit(tmp_path):
    codes = []
    c = ShutdownCoordinator(tmp_path / "st.json", force_exit=codes.append)
    c.shutdown("first")
    c._on_signal(signal.SIGINT, None)
    assert codes == [128 + signal.SIGINT]


def test_install_requires_main_thread(tmp_path):
    c = ShutdownCoordinator(tmp_path / "st.json")
    errors = []
    def attempt():
        try:
            c.install()
        except RuntimeError as exc:
            errors.append(exc)
    t = threading.Thread(target=attempt)
    t.start()
    t.join()
    assert len(errors) == 1


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="requires SIGUSR1")
def test_install_real_signal_roundtrip(tmp_path):
    c = ShutdownCoordinator(tmp_path / "st.json", signals=(signal.SIGUSR1,))
    before = signal.getsignal(signal.SIGUSR1)
    c.install()
    try:
        with pytest.raises(SystemExit):
            signal.raise_signal(signal.SIGUSR1)
    finally:
        c.uninstall()
    assert signal.getsignal(signal.SIGUSR1) == before


def test_excepthook_persists_then_delegates(tmp_path):
    seen = []
    original = sys.excepthook
    sys.excepthook = lambda *a: seen.append(a[0])
    c = ShutdownCoordinator(tmp_path / "st.json", signals=())
    c.install()
    try:
        sys.excepthook(ValueError, ValueError("x"), None)
    finally:
        c.uninstall()
        sys.excepthook = original
    assert seen == [ValueError]
    assert json.loads((tmp_path / "st.json").read_text())["reason"] == "unhandled:ValueError"


def test_keyboard_interrupt_does_not_trigger_shutdown(tmp_path):
    original = sys.excepthook
    sys.excepthook = lambda *a: None
    c = ShutdownCoordinator(tmp_path / "st.json", signals=())
    c.install()
    try:
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    finally:
        c.uninstall()
        sys.excepthook = original
    assert not c.shutting_down
