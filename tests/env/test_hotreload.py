import time

import pytest

from ai_creator_agent.env.errors import HotReloadError
from ai_creator_agent.env.hotreload import HotReloader, watched_env_files


def test_rejects_unknown_reloadable_key():
    with pytest.raises(HotReloadError, match="not in config"):
        HotReloader(lambda: {}, {"safe": 1}, {"missing"})


def test_rejects_nonpositive_poll_interval():
    with pytest.raises(HotReloadError):
        HotReloader(lambda: {}, {"x": 1}, {"x"}, poll_interval_s=0)


def test_only_allowlisted_values_change_and_subscribers_notified():
    changes = []
    r = HotReloader(lambda: {"timeout": 5, "secret": "new"}, {"timeout": 1, "secret": "old"}, {"timeout"})
    r.subscribe(lambda event: changes.append(dict(event)))
    result = r.reload()
    assert result.changed and result.applied["timeout"] == (1, 5)
    assert "secret" in result.rejected
    assert r.get("timeout") == 5 and r.get("secret") == "old"
    assert changes == [{"timeout": (1, 5)}]


def test_loader_failure_keeps_previous_configuration():
    r = HotReloader(lambda: (_ for _ in ()).throw(RuntimeError("bad config")), {"x": 1}, {"x"})
    result = r.reload()
    assert result.error and r.get("x") == 1


def test_missing_reloadable_key_is_rejected_not_deleted():
    r = HotReloader(lambda: {}, {"x": 1}, {"x"})
    result = r.reload()
    assert "x" in result.rejected and r.get("x") == 1


def test_subscriber_failure_does_not_rollback():
    r = HotReloader(lambda: {"x": 2}, {"x": 1}, {"x"})
    r.subscribe(lambda _event: (_ for _ in ()).throw(RuntimeError("observer")))
    assert r.reload().changed and r.get("x") == 2


def test_snapshot_is_read_only():
    r = HotReloader(lambda: {"x": 1}, {"x": 1}, {"x"})
    with pytest.raises(TypeError):
        r.snapshot()["x"] = 2


def test_poll_once_only_reloads_when_signature_changes(tmp_path):
    watched = tmp_path / ".env"
    watched.write_text("x=1")
    value = {"x": 1}
    r = HotReloader(lambda: value, {"x": 1}, {"x"}, [watched])
    assert r.poll_once() is None
    time.sleep(0.002)
    watched.write_text("x=2 longer")
    value["x"] = 2
    result = r.poll_once()
    assert result is not None and r.get("x") == 2


def test_watched_env_files_profile_rules(tmp_path):
    assert [p.name for p in watched_env_files(tmp_path, "prod")] == [".env", ".env.prod"]
    assert [p.name for p in watched_env_files(tmp_path, "dev")] == [".env", ".env.dev", ".env.local"]


def test_start_stop_is_idempotent():
    r = HotReloader(lambda: {}, {}, set(), poll_interval_s=0.01)
    r.start()
    r.start()
    r.stop()
    r.stop()
    assert r._thread is None
