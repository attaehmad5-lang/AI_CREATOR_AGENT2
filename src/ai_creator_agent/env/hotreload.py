"""Hot-reloadable configuration: apply non-critical changes without restart."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .errors import HotReloadError

log = logging.getLogger(__name__)
Change = tuple[Any, Any]
Subscriber = Callable[[Mapping[str, Change]], None]
Signature = tuple[tuple[str, int, int] | None, ...]


@dataclass(frozen=True)
class ReloadResult:
    applied: Mapping[str, Change] = field(default_factory=dict)
    rejected: tuple[str, ...] = ()
    error: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.applied)


class HotReloader:
    """Reload configuration while rejecting changes to non-whitelisted keys."""

    def __init__(
        self,
        loader: Callable[[], Mapping[str, Any]],
        initial: Mapping[str, Any],
        reloadable: Iterable[str],
        watch_files: Iterable[Path] = (),
        poll_interval_s: float = 2.0,
    ) -> None:
        reloadable_set = frozenset(reloadable)
        unknown = reloadable_set - set(initial)
        if unknown:
            raise HotReloadError(f"reloadable keys not in config: {sorted(unknown)}")
        if poll_interval_s <= 0:
            raise HotReloadError("poll_interval_s must be positive")
        self._loader = loader
        self._config: dict[str, Any] = dict(initial)
        self._reloadable = reloadable_set
        self._files = tuple(watch_files)
        self._interval = poll_interval_s
        self._lock = threading.RLock()
        self._subscribers: list[Subscriber] = []
        self._signature = self._compute_signature()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType(dict(self._config))

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._config.get(key, default)

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)

    def _compute_signature(self) -> Signature:
        parts: list[tuple[str, int, int] | None] = []
        for path in self._files:
            try:
                info = path.stat()
            except OSError:
                parts.append(None)
            else:
                parts.append((str(path), info.st_mtime_ns, info.st_size))
        return tuple(parts)

    def reload(self) -> ReloadResult:
        try:
            fresh = dict(self._loader())
        except Exception as exc:
            log.warning("hot reload failed, keeping current config: %s", exc)
            return ReloadResult(error=f"{type(exc).__name__}: {exc}")
        applied: dict[str, Change] = {}
        rejected: list[str] = []
        with self._lock:
            for key in sorted(set(fresh) | set(self._config)):
                old = self._config.get(key)
                new = fresh.get(key)
                if key in fresh and key in self._config and old == new:
                    continue
                if key in self._reloadable and key in fresh:
                    applied[key] = (old, new)
                else:
                    rejected.append(key)
            for key, (_old, new) in applied.items():
                self._config[key] = new
        if applied:
            for callback in list(self._subscribers):
                try:
                    callback(MappingProxyType(applied))
                except Exception:
                    log.exception("hot reload subscriber failed")
        return ReloadResult(MappingProxyType(applied), tuple(rejected))

    def poll_once(self) -> ReloadResult | None:
        current = self._compute_signature()
        if current == self._signature:
            return None
        self._signature = current
        return self.reload()

    def install_sighup(self) -> None:
        if not hasattr(signal, "SIGHUP"):
            raise HotReloadError("SIGHUP is unavailable on this platform")
        signal.signal(signal.SIGHUP, lambda _s, _f: self.reload())

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="hot-reload", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval * 2 + 1)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.poll_once()
            except Exception:
                log.exception("hot reload poll failed")


def watched_env_files(root: Path, profile_value: str) -> list[Path]:
    names = [".env", f".env.{profile_value}"]
    if profile_value == "dev":
        names.append(".env.local")
    return [root / name for name in names]
