import pytest

from ai_creator_agent.env.errors import HardwareError
from ai_creator_agent.env.hardware import (
    DeviceInfo,
    DeviceKind,
    Probes,
    cpu_device,
    detect_cuda,
    detect_hardware,
    detect_mps,
    detect_rocm,
    parse_nvidia_smi,
    parse_rocminfo,
    select_device,
)


def test_parse_nvidia_smi():
    devices = parse_nvidia_smi("NVIDIA A10, 23028, 550.54\nNVIDIA T4, bad, 535.1")
    assert len(devices) == 2 and devices[0].memory_mb == 23028
    assert devices[1].memory_mb is None and devices[1].index == 1


def test_parse_rocminfo():
    devices = parse_rocminfo("Marketing Name: AMD MI210\nDevice Type: GPU\nDevice Type: CPU")
    assert len(devices) == 1 and devices[0].name == "AMD MI210"


def test_visible_devices_can_disable_cuda():
    p = Probes(environ={"CUDA_VISIBLE_DEVICES": "-1"}, torch=lambda: None)
    assert detect_cuda(p) == []


def test_cuda_fallback_to_nvidia_smi():
    p = Probes(torch=lambda: None, which=lambda n: "/usr/bin/nvidia-smi" if n == "nvidia-smi" else None,
               run=lambda cmd: "NVIDIA A10, 23028, 550.54")
    assert detect_cuda(p)[0].kind is DeviceKind.CUDA


def test_rocm_fallback_to_rocminfo():
    p = Probes(torch=lambda: None, which=lambda n: "/usr/bin/rocminfo" if n == "rocminfo" else None,
               run=lambda cmd: "Marketing Name: MI210\nDevice Type: GPU")
    assert detect_rocm(p)[0].kind is DeviceKind.ROCM


def test_mps_only_on_apple_silicon():
    p = Probes(system=lambda: "Darwin", machine=lambda: "arm64", torch=lambda: None,
               run=lambda cmd: "Apple M2")
    assert detect_mps(p)[0].kind is DeviceKind.MPS
    assert detect_mps(Probes(system=lambda: "Linux", machine=lambda: "x86_64", torch=lambda: None)) == []


def test_auto_prefers_accelerator():
    cpu = DeviceInfo(DeviceKind.CPU, "CPU")
    gpu = DeviceInfo(DeviceKind.CUDA, "GPU")
    assert select_device([cpu, gpu])[0] == gpu


def test_cpu_preference():
    cpu = DeviceInfo(DeviceKind.CPU, "CPU")
    gpu = DeviceInfo(DeviceKind.CUDA, "GPU")
    assert select_device([cpu, gpu], "cpu")[0] == cpu


def test_missing_accelerator_falls_back_unless_strict():
    cpu = DeviceInfo(DeviceKind.CPU, "CPU")
    assert select_device([cpu], "cuda")[0] == cpu
    with pytest.raises(HardwareError):
        select_device([cpu], "cuda", strict=True)


def test_unknown_preference():
    with pytest.raises(HardwareError):
        select_device([cpu_device()], "tpu")


def test_detect_hardware_report_uses_cpu_fallback():
    p = Probes(system=lambda: "Linux", machine=lambda: "x86_64", torch=lambda: None,
               which=lambda _name: None, environ={})
    report = detect_hardware(probes=p)
    assert report.selected.kind is DeviceKind.CPU and report.cpu_count >= 1
