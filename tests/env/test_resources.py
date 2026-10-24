import pytest

from ai_creator_agent.env.errors import ResourceLimitError
from ai_creator_agent.env.resources import (
    CapMode,
    GuardState,
    MemoryGuard,
    MemorySnapshot,
    apply_memory_cap,
    cgroup_memory_limit_bytes,
    parse_meminfo,
    parse_rss_from_status,
)
MB = 1024 * 1024

def test_parse_meminfo_converts_kb():
    got = parse_meminfo("MemTotal:  1000 kB\nMemFree: 5\ngarbage\nX: abc kB\n")
    assert got == {"MemTotal": 1000 * 1024, "MemFree": 5}

def test_parse_rss_ok_and_missing():
    assert parse_rss_from_status("Name:\tx\nVmRSS:\t  2048 kB\n") == 2048 * 1024
    with pytest.raises(ResourceLimitError):
        parse_rss_from_status("Name:\tx\n")

def test_cgroup_v2_numeric(tmp_path):
    (tmp_path / "memory.max").write_text("536870912\n")
    assert cgroup_memory_limit_bytes(tmp_path) == 536870912

def test_cgroup_v2_max_means_unlimited(tmp_path):
    (tmp_path / "memory.max").write_text("max\n")
    assert cgroup_memory_limit_bytes(tmp_path) is None

def test_cgroup_v1_fallback(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "memory.limit_in_bytes").write_text("1073741824")
    assert cgroup_memory_limit_bytes(tmp_path) == 1073741824

@pytest.mark.parametrize("raw", ["9223372036854771712", "0", "-5", "junk"])
def test_cgroup_bogus_values_ignored(tmp_path, raw):
    (tmp_path / "memory.max").write_text(raw)
    assert cgroup_memory_limit_bytes(tmp_path) is None

def test_cgroup_missing(tmp_path):
    assert cgroup_memory_limit_bytes(tmp_path) is None

class FakeRes:
    RLIMIT_DATA = 2
    RLIMIT_AS = 9
    RLIM_INFINITY = -1
    def __init__(self, hard=-1, fail=False):
        self.hard, self.fail, self.set_to = hard, fail, None
    def getrlimit(self, which):
        return (self.hard, self.hard)
    def setrlimit(self, which, pair):
        if self.fail:
            raise ValueError("denied")
        self.set_to = (which, pair)

def test_cap_applies_soft_and_hard():
    res = FakeRes()
    result = apply_memory_cap(100 * MB, CapMode.RLIMIT_DATA, res)
    assert res.set_to == (2, (100 * MB, 100 * MB)) and not result.clamped

def test_cap_as_mode_uses_rlimit_as():
    res = FakeRes()
    apply_memory_cap(MB, CapMode.RLIMIT_AS, res)
    assert res.set_to[0] == 9

def test_cap_clamped_to_existing_hard_limit():
    res = FakeRes(hard=50 * MB)
    result = apply_memory_cap(100 * MB, resource_module=res)
    assert result.clamped and result.applied_bytes == 50 * MB

def test_cap_setrlimit_failure_wrapped():
    with pytest.raises(ResourceLimitError):
        apply_memory_cap(MB, resource_module=FakeRes(fail=True))

@pytest.mark.parametrize("value", [0, -1])
def test_cap_rejects_non_positive(value):
    with pytest.raises(ResourceLimitError):
        apply_memory_cap(value, resource_module=FakeRes())

def test_cap_unsupported_attribute():
    class Bare:
        RLIM_INFINITY = -1
    with pytest.raises(ResourceLimitError):
        apply_memory_cap(MB, resource_module=Bare())

def snap(rss, avail=10_000 * MB):
    return MemorySnapshot(20_000 * MB, avail, rss)

def make_guard(sequence, **kw):
    items = iter(sequence)
    events = []
    guard = MemoryGuard(1000 * MB, reader=lambda: next(items), on_warn=lambda s: events.append("warn"), on_exceed=lambda s: events.append("exceed"), **kw)
    return guard, events

def test_guard_transitions_fire_once():
    guard, events = make_guard([snap(100 * MB), snap(900 * MB), snap(950 * MB), snap(1000 * MB), snap(1100 * MB)])
    states = [guard.check_once() for _ in range(5)]
    assert states == [GuardState.OK, GuardState.WARN, GuardState.WARN, GuardState.EXCEEDED, GuardState.EXCEEDED]
    assert events == ["warn", "exceed"]

def test_guard_rearms_after_recovery():
    guard, events = make_guard([snap(900 * MB), snap(10 * MB), snap(900 * MB)])
    for _ in range(3):
        guard.check_once()
    assert events == ["warn", "warn"]

def test_guard_low_system_memory_is_exceeded():
    guard, events = make_guard([snap(10 * MB, avail=50 * MB)], min_available_bytes=100 * MB)
    assert guard.check_once() is GuardState.EXCEEDED and events == ["exceed"]

def test_guard_invalid_arguments():
    with pytest.raises(ResourceLimitError):
        MemoryGuard(0)
    with pytest.raises(ResourceLimitError):
        MemoryGuard(MB, warn_ratio=1.0)

def test_headroom_allows_and_blocks():
    guard = MemoryGuard(1000 * MB, reader=lambda: snap(500 * MB))
    guard.ensure_headroom(400 * MB)
    with pytest.raises(ResourceLimitError, match="exceed"):
        guard.ensure_headroom(600 * MB)

def test_headroom_protects_host():
    guard = MemoryGuard(1000 * MB, min_available_bytes=100 * MB, reader=lambda: snap(1, avail=150 * MB))
    with pytest.raises(ResourceLimitError, match="starve"):
        guard.ensure_headroom(100 * MB)

def test_headroom_rejects_negative():
    guard = MemoryGuard(MB, reader=lambda: snap(0))
    with pytest.raises(ResourceLimitError):
        guard.ensure_headroom(-1)

def test_guard_thread_start_stop():
    guard = MemoryGuard(1000 * MB, interval_s=0.01, reader=lambda: snap(MB))
    guard.start()
    guard.start()
    guard.stop()
    assert guard.state is GuardState.OK
