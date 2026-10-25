from types import SimpleNamespace

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
    devices = parse_rocminfo(
        "Marketing Name: AMD MI210\nDevice Type: GPU\nDevice Type: CPU"
    )
    assert len(devices) == 1 and devices[0].name == "AMD MI210"


def test_visible_devices_can_disable_cuda():
    p = Probes(environ={"CUDA_VISIBLE_DEVICES": "-1"}, torch=lambda: None)
    assert detect_cuda(p) == []


def test_cuda_fallback_to_nvidia_smi():
    p = Probes(
        torch=lambda: None,
        which=lambda n: "/usr/bin/nvidia-smi" if n == "nvidia-smi" else None,
        run=lambda cmd: "NVIDIA A10, 23028, 550.54",
    )
    assert detect_cuda(p)[0].kind is DeviceKind.CUDA


def test_rocm_fallback_to_rocminfo():
    p = Probes(
        torch=lambda: None,
        which=lambda n: "/usr/bin/rocminfo" if n == "rocminfo" else None,
        run=lambda cmd: "Marketing Name: MI210\nDevice Type: GPU",
    )
    assert detect_rocm(p)[0].kind is DeviceKind.ROCM


def test_mps_only_on_apple_silicon():
    p = Probes(
        system=lambda: "Darwin",
        machine=lambda: "arm64",
        torch=lambda: None,
        run=lambda cmd: "Apple M2",
    )
    assert detect_mps(p)[0].kind is DeviceKind.MPS
    assert (
        detect_mps(
            Probes(system=lambda: "Linux", machine=lambda: "x86_64", torch=lambda: None)
        )
        == []
    )


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
    p = Probes(
        system=lambda: "Linux",
        machine=lambda: "x86_64",
        torch=lambda: None,
        which=lambda _name: None,
        environ={},
    )
    report = detect_hardware(probes=p)
    assert report.selected.kind is DeviceKind.CPU and report.cpu_count >= 1

MB = 1024 * 1024


def fake_torch(cuda=False, hip=None, mps=False, devices=()):
    props = [SimpleNamespace(name=name, total_memory=memory * MB) for name, memory in devices]
    return SimpleNamespace(
        __version__="2.3.0",
        version=SimpleNamespace(hip=hip),
        cuda=SimpleNamespace(
            is_available=lambda: cuda,
            device_count=lambda: len(props),
            get_device_properties=lambda index: props[index],
        ),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )


def make_probes(system="Linux", machine="x86_64", torch=None, which=None, run=None, env=None):
    which = which or {}
    run = run or {}
    return Probes(
        system=lambda: system,
        machine=lambda: machine,
        which=lambda name: which.get(name),
        run=lambda command: run.get(command[0]),
        torch=lambda: torch,
        environ=env or {},
    )


def test_cuda_via_torch_reports_device_metadata():
    found = detect_cuda(
        make_probes(torch=fake_torch(cuda=True, devices=[("RTX 4090", 24000)]))
    )
    assert found[0].name == "RTX 4090"
    assert found[0].memory_mb == 24000
    assert found[0].torch_device == "cuda:0"


@pytest.mark.parametrize("value", ["", "-1", " -1 "])
def test_cuda_visible_devices_disables_all_devices(value):
    torch = fake_torch(cuda=True, devices=[("GPU", 1)])
    assert detect_cuda(make_probes(torch=torch, env={"CUDA_VISIBLE_DEVICES": value})) == []


def test_cpu_only_torch_overrides_nvidia_smi():
    probes = make_probes(
        torch=fake_torch(cuda=False),
        which={"nvidia-smi": "/x"},
        run={"nvidia-smi": "RTX, 100, 1.0\\n"},
    )
    assert detect_cuda(probes) == []


def test_nvidia_smi_discovers_multiple_gpus_without_torch():
    output = "NVIDIA A, 24564, 550.1\\nNVIDIA B, 24576, 550.1\\n"
    found = detect_cuda(make_probes(which={"nvidia-smi": "/x"}, run={"nvidia-smi": output}))
    assert [device.index for device in found] == [0, 1]
    assert found[1].driver == "550.1"


def test_nvidia_smi_skips_garbage_lines():
    assert len(parse_nvidia_smi("junk\\n,,\\nGPU, notnum, 1.0\\n")) == 1
    assert parse_nvidia_smi("GPU, notnum, 1.0")[0].memory_mb is None


def test_nvidia_smi_failure_and_missing_binary_return_empty():
    assert detect_cuda(make_probes(which={"nvidia-smi": "/x"}, run={})) == []
    assert detect_cuda(make_probes()) == []


def test_torch_cuda_probe_exceptions_are_contained():
    torch = fake_torch()
    torch.cuda.is_available = lambda: (_ for _ in ()).throw(RuntimeError("driver"))
    assert detect_cuda(make_probes(torch=torch)) == []


def test_rocm_via_torch_hip_is_not_misreported_as_cuda():
    torch = fake_torch(cuda=True, hip="6.0", devices=[("MI250X", 65536)])
    found = detect_rocm(make_probes(torch=torch))
    assert found[0].kind is DeviceKind.ROCM
    assert found[0].driver == "6.0"
    assert found[0].torch_device == "cuda:0"
    assert detect_cuda(make_probes(torch=torch)) == []


def test_rocminfo_keeps_only_gpu_agents():
    output = (
        "Agent 1\\n Marketing Name: AMD Ryzen 9\\n Device Type: CPU\\n"
        "Agent 2\\n Marketing Name: AMD Instinct MI250X\\n Device Type: GPU\\n"
    )
    found = parse_rocminfo(output)
    assert [device.name for device in found] == ["AMD Instinct MI250X"]


def test_rocm_missing_binary_and_hidden_devices_return_empty():
    assert detect_rocm(make_probes()) == []
    torch = fake_torch(cuda=True, hip="6.0", devices=[("GPU", 1)])
    assert detect_rocm(make_probes(torch=torch, env={"HIP_VISIBLE_DEVICES": "-1"})) == []


def test_mps_torch_and_platform_fallbacks():
    found = detect_mps(
        make_probes("Darwin", "arm64", torch=fake_torch(mps=True), run={"sysctl": "Apple M3"})
    )
    assert found[0].name == "Apple M3"
    assert found[0].torch_device == "mps"
    assert detect_mps(make_probes("Darwin", "arm64", torch=fake_torch(mps=False))) == []
    assert detect_mps(make_probes("Darwin", "arm64"))[0].source == "platform"


@pytest.mark.parametrize(
    "system,machine",
    [("Darwin", "x86_64"), ("Linux", "arm64"), ("Windows", "AMD64")],
)
def test_mps_is_rejected_on_other_platforms(system, machine):
    assert detect_mps(make_probes(system, machine)) == []


def test_auto_prefers_cuda_then_rocm_then_mps():
    cpu = DeviceInfo(DeviceKind.CPU, "CPU")
    devices = [
        DeviceInfo(DeviceKind.MPS, "MPS"),
        DeviceInfo(DeviceKind.ROCM, "ROCm"),
        cpu,
    ]
    assert select_device(devices)[0].kind is DeviceKind.ROCM
    devices.append(DeviceInfo(DeviceKind.CUDA, "CUDA"))
    assert select_device(devices)[0].kind is DeviceKind.CUDA


def test_auto_and_explicit_fallback_reasons_are_explained():
    cpu = DeviceInfo(DeviceKind.CPU, "CPU")
    selected, reason = select_device([cpu])
    assert selected.kind is DeviceKind.CPU and "no accelerator" in reason
    selected, reason = select_device([cpu], "cuda")
    assert selected.kind is DeviceKind.CPU and "falling back" in reason
    assert select_device([cpu], "cpu")[1] is None


def test_detect_hardware_reports_torch_version_and_cpu():
    torch = fake_torch(cuda=True, devices=[("RTX", 8000)])
    report = detect_hardware("auto", probes=make_probes(torch=torch))
    assert report.selected.kind is DeviceKind.CUDA
    assert report.torch_version == "2.3.0"
    assert report.cpu_count >= 1
    assert report.devices[-1].kind is DeviceKind.CPU
