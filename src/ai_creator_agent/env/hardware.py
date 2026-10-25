"""Hardware acceleration detection: CUDA, ROCm, Apple MPS, CPU fallback."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import HardwareError

_MB = 1024 * 1024


class DeviceKind(StrEnum):
    CUDA = "cuda"
    ROCM = "rocm"
    MPS = "mps"
    CPU = "cpu"


@dataclass(frozen=True)
class DeviceInfo:
    kind: DeviceKind
    name: str
    index: int = 0
    memory_mb: int | None = None
    driver: str | None = None
    source: str = "system"

    @property
    def torch_device(self) -> str:
        if self.kind in (DeviceKind.CUDA, DeviceKind.ROCM):
            return f"cuda:{self.index}"
        return self.kind.value


@dataclass(frozen=True)
class HardwareReport:
    devices: tuple[DeviceInfo, ...]
    selected: DeviceInfo
    preference: str
    fallback_reason: str | None
    cpu_count: int
    torch_version: str | None


def _safe_run(cmd: Sequence[str], timeout: float = 10.0) -> str | None:
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _import_torch() -> Any | None:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return None
    return torch


@dataclass
class Probes:
    """Injectable system probes so every branch is testable without hardware."""

    system: Callable[[], str] = platform.system
    machine: Callable[[], str] = platform.machine
    which: Callable[[str], str | None] = shutil.which
    run: Callable[[Sequence[str]], str | None] = _safe_run
    torch: Callable[[], Any | None] = _import_torch
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)


def _disabled(value: str | None) -> bool:
    return value is not None and value.strip() in ("", "-1")


def _torch_devices(
    torch: Any, kind: DeviceKind, driver: str | None
) -> list[DeviceInfo]:
    found: list[DeviceInfo] = []
    for index in range(int(torch.cuda.device_count())):
        props = torch.cuda.get_device_properties(index)
        found.append(
            DeviceInfo(
                kind,
                str(props.name),
                index,
                int(props.total_memory) // _MB,
                driver,
                "torch",
            )
        )
    return found


def parse_nvidia_smi(output: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3 or not parts[0]:
            continue
        try:
            memory: int | None = int(float(parts[1]))
        except ValueError:
            memory = None
        devices.append(
            DeviceInfo(
                DeviceKind.CUDA, parts[0], len(devices), memory, parts[2], "nvidia-smi"
            )
        )
    return devices


def parse_rocminfo(output: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    last_name = "AMD GPU"
    for line in output.splitlines():
        text = line.strip()
        if text.startswith("Marketing Name:"):
            last_name = text.split(":", 1)[1].strip() or last_name
        elif text.startswith("Device Type:") and "GPU" in text:
            devices.append(
                DeviceInfo(
                    DeviceKind.ROCM, last_name, len(devices), None, None, "rocminfo"
                )
            )
    return devices


def detect_cuda(probes: Probes) -> list[DeviceInfo]:
    if _disabled(probes.environ.get("CUDA_VISIBLE_DEVICES")):
        return []
    torch = probes.torch()
    if torch is not None:
        try:
            is_hip = getattr(torch.version, "hip", None) is not None
            if not is_hip and torch.cuda.is_available():
                return _torch_devices(torch, DeviceKind.CUDA, None)
        except Exception:
            return []
        return []
    if probes.which("nvidia-smi") is None:
        return []
    output = probes.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    return parse_nvidia_smi(output) if output else []


def detect_rocm(probes: Probes) -> list[DeviceInfo]:
    env = probes.environ
    if _disabled(env.get("HIP_VISIBLE_DEVICES")) or _disabled(
        env.get("ROCR_VISIBLE_DEVICES")
    ):
        return []
    torch = probes.torch()
    if torch is not None:
        try:
            hip = getattr(torch.version, "hip", None)
            if hip and torch.cuda.is_available():
                return _torch_devices(torch, DeviceKind.ROCM, str(hip))
        except Exception:
            return []
        return []
    if probes.which("rocminfo") is None:
        return []
    output = probes.run(["rocminfo"])
    return parse_rocminfo(output) if output else []


def detect_mps(probes: Probes) -> list[DeviceInfo]:
    if probes.system() != "Darwin" or probes.machine() not in ("arm64", "aarch64"):
        return []
    torch = probes.torch()
    if torch is not None:
        try:
            if not torch.backends.mps.is_available():
                return []
        except Exception:
            return []
    brand = probes.run(["sysctl", "-n", "machdep.cpu.brand_string"])
    name = brand.strip() if brand and brand.strip() else "Apple Silicon"
    return [DeviceInfo(DeviceKind.MPS, name, 0, None, None, "platform")]


def cpu_device(probes: Probes | None = None) -> DeviceInfo:
    name = platform.processor() or platform.machine() or "cpu"
    return DeviceInfo(DeviceKind.CPU, name, 0, None, None, "platform")


def detect_devices(probes: Probes | None = None) -> list[DeviceInfo]:
    active = probes or Probes()
    devices = detect_cuda(active) + detect_rocm(active) + detect_mps(active)
    devices.append(cpu_device(active))
    return devices


def select_device(
    devices: Sequence[DeviceInfo], preference: str = "auto", strict: bool = False
) -> tuple[DeviceInfo, str | None]:
    cpu = next((d for d in devices if d.kind is DeviceKind.CPU), cpu_device())
    if preference == "auto":
        for kind in (DeviceKind.CUDA, DeviceKind.ROCM, DeviceKind.MPS):
            match = next((d for d in devices if d.kind is kind), None)
            if match is not None:
                return match, None
        return cpu, "no accelerator detected; using cpu"
    try:
        wanted = DeviceKind(preference)
    except ValueError:
        raise HardwareError(f"unknown device preference {preference!r}") from None
    if wanted is DeviceKind.CPU:
        return cpu, None
    match = next((d for d in devices if d.kind is wanted), None)
    if match is not None:
        return match, None
    if strict:
        raise HardwareError(f"requested device {preference} is not available")
    return cpu, f"requested {preference} unavailable; falling back to cpu"


def detect_hardware(
    preference: str = "auto", strict: bool = False, probes: Probes | None = None
) -> HardwareReport:
    active = probes or Probes()
    devices = detect_devices(active)
    selected, reason = select_device(devices, preference, strict)
    torch = active.torch()
    version = str(getattr(torch, "__version__", "")) or None if torch else None
    return HardwareReport(
        tuple(devices), selected, preference, reason, os.cpu_count() or 1, version
    )
