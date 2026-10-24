"""Isolated ephemeral storage lifecycle for temporary media assets."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

from .errors import WorkspaceError

MARKER = ".aica-owner"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def assert_safe_root(root: Path) -> Path:
    """Refuse roots such as /, /tmp itself or the home directory."""
    resolved = root.resolve()
    if len(resolved.parts) < 3:
        raise WorkspaceError(f"unsafe workspace root {resolved}")
    if resolved == Path.home().resolve():
        raise WorkspaceError("workspace root must not be the home directory")
    return resolved


class EphemeralWorkspace:
    """A private 0700 directory that is removed on exit, signal or crash-sweep."""

    def __init__(self, root: Path, prefix: str = "aica-", max_bytes: int | None = None, register_atexit: bool = True) -> None:
        if not prefix or "/" in prefix or "\\" in prefix:
            raise WorkspaceError(f"invalid prefix {prefix!r}")
        if max_bytes is not None and max_bytes <= 0:
            raise WorkspaceError("max_bytes must be positive")
        self.root = root
        self.prefix = prefix
        self.max_bytes = max_bytes
        self._register = register_atexit
        self._path: Path | None = None

    @property
    def path(self) -> Path:
        if self._path is None:
            raise WorkspaceError("workspace not created")
        return self._path

    def create(self) -> Path:
        if self._path is not None:
            return self._path
        safe_root = assert_safe_root(self.root)
        safe_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._path = Path(tempfile.mkdtemp(prefix=self.prefix, dir=safe_root))
        (self._path / MARKER).write_text(str(os.getpid()), encoding="utf-8")
        if self._register:
            atexit.register(self.cleanup)
        return self._path

    def new_path(self, suffix: str = "") -> Path:
        if any(sep in suffix for sep in ("/", "\\", "\x00")):
            raise WorkspaceError(f"invalid suffix {suffix!r}")
        return self.path / f"{uuid.uuid4().hex}{suffix}"

    def usage_bytes(self) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(self.path):
            for name in files:
                try:
                    info = os.lstat(os.path.join(dirpath, name))
                except OSError:
                    continue
                total += info.st_size
        return total

    def ensure_capacity(self, extra_bytes: int) -> None:
        if extra_bytes < 0:
            raise WorkspaceError("extra_bytes must be >= 0")
        if self.max_bytes is None:
            return
        if self.usage_bytes() + extra_bytes > self.max_bytes:
            raise WorkspaceError(f"workspace cap of {self.max_bytes} bytes would be exceeded")

    def cleanup(self) -> bool:
        path, self._path = self._path, None
        if path is None:
            return True
        if self._register:
            atexit.unregister(self.cleanup)
        if path.is_symlink() or not path.name.startswith(self.prefix):
            raise WorkspaceError(f"refusing to delete unexpected path {path}")
        shutil.rmtree(path, ignore_errors=True)
        return not path.exists()

    def __enter__(self) -> Path:
        return self.create()

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        self.cleanup()


def sweep_stale(root: Path, prefix: str = "aica-", ttl_seconds: float = 86_400.0, clock: Callable[[], float] = time.time, pid_alive: Callable[[int], bool] = _pid_alive) -> list[Path]:
    """Remove workspaces left behind by crashed processes."""
    if not root.is_dir():
        return []
    assert_safe_root(root)
    removed: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_symlink() or not child.is_dir() or not child.name.startswith(prefix):
            continue
        try:
            owner = int((child / MARKER).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            owner = None
        stale = not pid_alive(owner) if owner is not None else clock() - child.stat().st_mtime > ttl_seconds
        if stale:
            shutil.rmtree(child, ignore_errors=True)
            if not child.exists():
                removed.append(child)
    return removed
