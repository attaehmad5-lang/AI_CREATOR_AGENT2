"""Process memory caps, cgroup awareness and OOM guards."""

from __future__ import annotations

import os
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import ResourceLimitError

MB = 1024 * 1024


def cgroup_memory_limit_bytes(root: Path = Path("/sys/fs/cgroup")) -> int | None:
    """Container memory limit (cgroup v2 then v1); None when unlimited."""
    for candidate in (root / "memory.max", root / "memory" / "memory.limit_in_bytes"):
        try:
            raw = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw == "max":
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        if value <= 0 or value >= 1 << 60:
            return None
        return value
    return None


@dataclass(frozen=True)
class MemorySnapshot:
    total_bytes: int
    available_bytes: int
    rss_bytes: int


def parse_meminfo(text: str) -> dict[str, int]:
    """Parse /proc/meminfo into bytes."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if not parts or not parts[0].isdigit():
            continue
        factor = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
        values[key.strip()] = int(parts[0]) * factor
    return values


def parse_rss_from_status(text: str) -> int:
    """Extract VmRSS (bytes) from /proc/self/status."""
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    raise ResourceLimitError("VmRSS not found in process status")


def read_memory_snapshot() -> MemorySnapshot:
    try:
        import psutil

        vm = psutil.virtual_memory()
        total, available = int(vm.total), int(vm.available)
        rss = int(psutil.Process().memory_info().rss)
    except ImportError:
        try:
            meminfo = parse_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
            status = Path("/proc/self/status").read_text(encoding="utf-8")
        except OSError as exc:
            raise ResourceLimitError(f"cannot read memory state: {exc}") from exc
        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        rss = parse_rss_from_status(status)
    if total <= 0:
        raise ResourceLimitError("unable to determine total memory")
    limit = cgroup_memory_limit_bytes()
    if limit is not None and limit < total:
        total = limit
        available = max(0, min(available, limit - rss))
    return MemorySnapshot(total, available, rss)


class CapMode(StrEnum):
    RLIMIT_AS = "rlimit_as"
    RLIMIT_DATA = "rlimit_data"


@dataclass(frozen=True)
class CapResult:
    requested_bytes: int
    applied_bytes: int
    mode: CapMode
    clamped: bool


def apply_memory_cap(
    max_bytes: int,
    mode: CapMode = CapMode.RLIMIT_DATA,
    resource_module: Any | None = None,
) -> CapResult:
    """Lower soft and hard RLIMIT so the cap cannot be raised again."""
    if max_bytes <= 0:
        raise ResourceLimitError("max_bytes must be positive")
    res = resource_module
    if res is None:
        try:
            import resource
        except ImportError:
            raise ResourceLimitError("resource limits unsupported here") from None
        res = resource
    attr = "RLIMIT_AS" if mode is CapMode.RLIMIT_AS else "RLIMIT_DATA"
    which = getattr(res, attr, None)
    if which is None:
        raise ResourceLimitError(f"{attr} unsupported on this platform")
    _soft, hard = res.getrlimit(which)
    target, clamped = max_bytes, False
    if hard != res.RLIM_INFINITY and target > hard:
        target, clamped = hard, True
    try:
        res.setrlimit(which, (target, target))
    except (ValueError, OSError) as exc:
        raise ResourceLimitError(f"setrlimit failed: {exc}") from exc
    return CapResult(max_bytes, target, mode, clamped)


class GuardState(StrEnum):
    OK = "ok"
    WARN = "warn"
    EXCEEDED = "exceeded"


def _terminate_self() -> None:
    os.kill(os.getpid(), signal.SIGTERM)


class MemoryGuard:
    """RSS watchdog + pre-allocation headroom checks (OOM guard)."""

    def __init__(
        self,
        max_bytes: int,
        warn_ratio: float = 0.85,
        min_available_bytes: int = 0,
        interval_s: float = 1.0,
        reader: Callable[[], MemorySnapshot] = read_memory_snapshot,
        on_warn: Callable[[MemorySnapshot], None] | None = None,
        on_exceed: Callable[[MemorySnapshot], None] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ResourceLimitError("max_bytes must be positive")
        if not 0 < warn_ratio < 1:
            raise ResourceLimitError("warn_ratio must be within (0, 1)")
        self.max_bytes = max_bytes
        self.warn_ratio = warn_ratio
        self.min_available_bytes = min_available_bytes
        self.interval_s = interval_s
        self._reader = reader
        self._on_warn = on_warn
        self._on_exceed = on_exceed or (lambda _snap: _terminate_self())
        self._state = GuardState.OK
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> GuardState:
        return self._state

    def _classify(self, snap: MemorySnapshot) -> GuardState:
        low_system = (
            self.min_available_bytes > 0
            and snap.available_bytes < self.min_available_bytes
        )
        if snap.rss_bytes >= self.max_bytes or low_system:
            return GuardState.EXCEEDED
        if snap.rss_bytes >= self.max_bytes * self.warn_ratio:
            return GuardState.WARN
        return GuardState.OK

    def check_once(self) -> GuardState:
        snap = self._reader()
        new_state = self._classify(snap)
        previous, self._state = self._state, new_state
        if new_state is not previous:
            if new_state is GuardState.WARN and self._on_warn:
                self._on_warn(snap)
            elif new_state is GuardState.EXCEEDED:
                self._on_exceed(snap)
        return new_state

    def ensure_headroom(self, requested_bytes: int) -> None:
        """Raise before a large allocation would OOM."""
        if requested_bytes < 0:
            raise ResourceLimitError("requested_bytes must be >= 0")
        snap = self._reader()
        if snap.rss_bytes + requested_bytes > self.max_bytes:
            raise ResourceLimitError(
                f"allocation of {requested_bytes // MB} MB would exceed the "
                f"{self.max_bytes // MB} MB cap (rss {snap.rss_bytes // MB} MB)"
            )
        if (
            self.min_available_bytes
            and snap.available_bytes - requested_bytes < self.min_available_bytes
        ):
            raise ResourceLimitError("allocation would starve the host of memory")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="memory-guard", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s * 2 + 1)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.check_once()
            except ResourceLimitError:
                continue
