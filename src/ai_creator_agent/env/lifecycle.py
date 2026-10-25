"""Graceful SIGTERM/SIGINT handling and atomic crash-safe state persistence."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType, TracebackType
from typing import Any


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("state root must be an object")
    except ValueError:
        with contextlib.suppress(OSError):
            os.replace(path, path.with_suffix(".corrupt"))
        return None
    return parsed


@dataclass(frozen=True)
class ShutdownReport:
    reason: str
    state_saved: bool
    hooks_run: tuple[str, ...]
    hook_errors: Mapping[str, str]
    duration_s: float


Hook = Callable[[], None]


class ShutdownCoordinator:
    """Persist state and run cleanup hooks once, on signal or unhandled error."""

    def __init__(
        self,
        state_path: Path,
        snapshot: Callable[[], Mapping[str, Any]] = dict,
        signals: Sequence[signal.Signals] | None = None,
        force_exit: Callable[[int], Any] = os._exit,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.state_path = state_path
        self._snapshot = snapshot
        self._signals = tuple(signals or (signal.SIGTERM, signal.SIGINT))
        self._force_exit = force_exit
        self._clock = clock
        self._hooks: list[tuple[int, int, str, Hook]] = []
        self._event = threading.Event()
        self._report: ShutdownReport | None = None
        self._lock = threading.Lock()
        self._previous_handlers: dict[signal.Signals, Any] = {}
        self._previous_excepthook: Callable[..., Any] | None = None

    @property
    def shutting_down(self) -> bool:
        return self._event.is_set()

    def add_hook(self, name: str, func: Hook, priority: int = 50) -> None:
        self._hooks.append((priority, len(self._hooks), name, func))

    def install(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("signal handlers can only be installed from main thread")
        for sig in self._signals:
            self._previous_handlers[sig] = signal.signal(sig, self._on_signal)
        self._previous_excepthook = sys.excepthook
        sys.excepthook = self._on_exception

    def uninstall(self) -> None:
        for sig, handler in self._previous_handlers.items():
            signal.signal(sig, handler)
        self._previous_handlers.clear()
        if self._previous_excepthook is not None:
            sys.excepthook = self._previous_excepthook
            self._previous_excepthook = None

    def shutdown(self, reason: str) -> ShutdownReport:
        with self._lock:
            if self._report is not None:
                return self._report
            self._event.set()
            started = self._clock()
            try:
                state: Mapping[str, Any] = self._snapshot()
            except Exception as exc:
                state = {"snapshot_error": repr(exc)}
            payload = {
                "reason": reason,
                "pid": os.getpid(),
                "timestamp": time.time(),
                "state": dict(state),
            }
            try:
                atomic_write_json(self.state_path, payload)
                saved = True
            except OSError:
                saved = False
            ran: list[str] = []
            errors: dict[str, str] = {}
            for _prio, _order, name, func in sorted(
                self._hooks, key=lambda item: (item[0], item[1])
            ):
                ran.append(name)
                try:
                    func()
                except Exception as exc:
                    errors[name] = repr(exc)
            self._report = ShutdownReport(
                reason, saved, tuple(ran), errors, self._clock() - started
            )
            return self._report

    def _on_signal(self, signum: int, _frame: FrameType | None) -> None:
        if self._event.is_set():
            self._force_exit(128 + signum)
            return
        name = signal.Signals(signum).name
        self.shutdown(f"signal:{name}")
        raise SystemExit(128 + signum)

    def _on_exception(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        previous = self._previous_excepthook or sys.__excepthook__
        if not issubclass(exc_type, KeyboardInterrupt):
            self.shutdown(f"unhandled:{exc_type.__name__}")
        previous(exc_type, exc, tb)
