"""Dynamic native-library and C-extension resolution (.so / .dll / .dylib)."""

from __future__ import annotations

import ctypes
import ctypes.util
import importlib
import importlib.machinery
import os
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .errors import BinaryResolutionError


def platform_lib_names(stem: str, system: str | None = None) -> list[str]:
    if not stem or any(sep in stem for sep in ("/", "\\", "\x00")):
        raise BinaryResolutionError(f"invalid library stem {stem!r}")
    name = system or platform.system()
    if name == "Windows":
        return [f"{stem}.dll", f"lib{stem}.dll"]
    if name == "Darwin":
        return [f"lib{stem}.dylib", f"{stem}.dylib"]
    return [f"lib{stem}.so", f"{stem}.so"]


def _versioned_matches(directory: Path, names: Sequence[str]) -> list[Path]:
    matches: list[Path] = []
    for name in names:
        exact = directory / name
        if exact.is_file():
            matches.append(exact)
        matches.extend(sorted(p for p in directory.glob(f"{name}.*") if p.is_file()))
    return matches


def find_library(
    stem: str,
    search_dirs: Sequence[Path] = (),
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
) -> Path | None:
    env = os.environ if environ is None else environ
    names = platform_lib_names(stem, system)
    override = env.get(f"AI_CREATOR_LIB_{stem.upper().replace('-', '_')}")
    if override:
        path = Path(override)
        if not path.is_file():
            raise BinaryResolutionError(f"override for {stem} not a file: {path}")
        return path
    for directory in search_dirs:
        if directory.is_dir():
            found = _versioned_matches(directory, names)
            if found:
                return found[0]
    located = ctypes.util.find_library(stem)
    return Path(located) if located else None


@dataclass(frozen=True)
class LoadedLibrary:
    path: Path
    handle: Any


def load_library(
    stem: str,
    search_dirs: Sequence[Path] = (),
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
    loader: Callable[[str], Any] = ctypes.CDLL,
) -> LoadedLibrary:
    path = find_library(stem, search_dirs, environ, system)
    if path is None:
        raise BinaryResolutionError(f"native library {stem!r} not found")
    if (system or platform.system()) == "Windows" and hasattr(os, "add_dll_directory"):
        parent = path.parent
        if parent.is_dir():
            os.add_dll_directory(str(parent))
    try:
        return LoadedLibrary(path, loader(str(path)))
    except OSError as exc:
        raise BinaryResolutionError(f"cannot load {path}: {exc}") from exc


def extension_suffixes() -> list[str]:
    return sorted(importlib.machinery.EXTENSION_SUFFIXES, key=len, reverse=True)


def find_extension_module(name: str, search_dirs: Sequence[Path]) -> Path | None:
    if not name.isidentifier():
        raise BinaryResolutionError(f"invalid module name {name!r}")
    for directory in search_dirs:
        for suffix in extension_suffixes():
            candidate = directory / f"{name}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def import_optional(
    module: str, fallback: str | None = None
) -> tuple[ModuleType | None, str | None]:
    reasons: list[str] = []
    for candidate in (module, fallback):
        if candidate is None:
            continue
        try:
            return importlib.import_module(candidate), None
        except Exception as exc:
            reasons.append(f"{candidate}: {exc}")
    return None, "; ".join(reasons)
