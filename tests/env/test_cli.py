import pytest

from ai_creator_agent.env.cli import main


def test_scan_secrets_clean_directory(tmp_path):
    (tmp_path / "ok.py").write_text("print('hello')\n")
    assert main(["scan-secrets", str(tmp_path)]) == 0


def test_scan_secrets_detects_leak(tmp_path):
    (tmp_path / "leak.py").write_text("k = '" + "AKIA" + "ZQ4M7XK2PL9TB3WN" + "'\n")
    assert main(["scan-secrets", str(tmp_path)]) == 1


def test_hardware_command_runs():
    assert main(["hardware"]) == 0


def test_hardware_invalid_preference_returns_2():
    assert main(["hardware", "--preference", "tpu"]) == 2


def test_hardware_strict_unavailable_returns_2():
    assert main(["hardware", "--preference", "mps", "--strict"]) == 2


def test_unknown_runtime_rejected_by_argparse():
    with pytest.raises(SystemExit) as info:
        main(["preflight", "--runtime", "mainframe"])
    assert info.value.code == 2


def test_missing_subcommand_rejected():
    with pytest.raises(SystemExit):
        main([])
