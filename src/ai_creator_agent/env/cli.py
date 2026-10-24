"""Command line entry point: ``python -m ai_creator_agent.env <command>``."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .errors import EnvSuiteError

HEALTH_CHECKS = ("python", "memory", "paths", "disk")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-creator-env")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("diagnose", "healthcheck", "show-settings"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--profile", default=None)
        cmd.add_argument("--root", type=Path, default=Path("."))
        if name == "diagnose":
            cmd.add_argument("--json", action="store_true")

    pre = sub.add_parser("preflight")
    pre.add_argument("--runtime", default="local", choices=["local", "ci", "container"])

    hw = sub.add_parser("hardware")
    hw.add_argument("--preference", default="auto")
    hw.add_argument("--strict", action="store_true")

    scan = sub.add_parser("scan-secrets")
    group = scan.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true")
    group.add_argument("--tracked", action="store_true")
    scan.add_argument("paths", nargs="*", type=Path)

    audit = sub.add_parser("audit")
    audit.add_argument("--project", type=Path, default=Path("."))
    audit.add_argument("--ignore", action="append", default=[])
    return parser


def _cmd_preflight(args: argparse.Namespace) -> int:
    from .preflight import requirements_for, run_preflight

    results = run_preflight(requirements_for(args.runtime), raise_on_fail=False)
    for item in results:
        print(("OK   " if item.ok else "FAIL ") + item.message)
    return 0 if all(item.ok for item in results) else 1


def _cmd_hardware(args: argparse.Namespace) -> int:
    from .hardware import detect_hardware

    report = detect_hardware(args.preference, strict=args.strict)
    for device in report.devices:
        print(f"{device.kind.value:5} {device.name} (mem={device.memory_mb} MB)")
    print(f"selected: {report.selected.torch_device} ({report.selected.name})")
    if report.fallback_reason:
        print(f"note: {report.fallback_reason}")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    from .secretscan import format_findings, scan_git, scan_paths

    if args.staged:
        findings = scan_git("staged")
    elif args.tracked:
        findings = scan_git("tracked")
    else:
        findings = scan_paths(args.paths or [Path(".")])
    if findings:
        print(format_findings(findings), file=sys.stderr)
        print(f"{len(findings)} potential secret(s) found", file=sys.stderr)
        return 1
    print("no secrets detected")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from .audit import audit_lockfile

    with tempfile.TemporaryDirectory() as tmp:
        report = audit_lockfile(
            args.project, Path(tmp) / "requirements.lock.txt", args.ignore
        )
    for vuln in report.vulnerabilities:
        fixes = ",".join(vuln.fix_versions) or "no fix"
        print(f"{vuln.package}=={vuln.version} {vuln.vuln_id} (fix: {fixes})")
    print("clean" if report.ok else f"{len(report.vulnerabilities)} vulnerabilities")
    return 0 if report.ok else 1


def _diagnostic_config(settings: object) -> object:
    from .diagnostics import DiagnosticConfig
    from .settings import Settings

    assert isinstance(settings, Settings)
    return DiagnosticConfig(
        runtime=settings.runtime,
        strict_patch=settings.profile.value in ("staging", "prod", "test"),
        min_free_disk_mb=settings.min_free_disk_mb,
        max_ram_mb=settings.max_ram_mb,
        required_dirs=(settings.data_dir, settings.tmp_root),
        strict_permissions=settings.profile.value == "prod",
        device_preference=settings.device_preference,
    )


def _cmd_settings_based(args: argparse.Namespace) -> int:
    from .diagnostics import DiagnosticConfig, DiagnosticSuite
    from .settings import Settings

    settings = Settings.from_profile(args.profile, args.root)
    if args.command == "show-settings":
        print(json.dumps(settings.safe_dict(), indent=2))
        return 0
    config = _diagnostic_config(settings)
    assert isinstance(config, DiagnosticConfig)
    suite = DiagnosticSuite(config)
    only = HEALTH_CHECKS if args.command == "healthcheck" else None
    report = suite.run(only)
    if args.command == "diagnose" and args.json:
        print(report.to_json())
    else:
        print(report.render_text())
    return report.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            return _cmd_preflight(args)
        if args.command == "hardware":
            return _cmd_hardware(args)
        if args.command == "scan-secrets":
            return _cmd_scan(args)
        if args.command == "audit":
            return _cmd_audit(args)
        return _cmd_settings_based(args)
    except EnvSuiteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
