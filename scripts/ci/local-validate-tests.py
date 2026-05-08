#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, cwd=str(_repo_root()), env=env)


def _command_available(command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            command + ["--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.returncode == 0
    except FileNotFoundError:
        return False


def _resolve_pytest_command() -> list[str]:
    candidates: list[list[str]] = [
        [sys.executable, "-m", "pytest"],
        ["python3", "-m", "pytest"],
    ]

    for candidate in candidates:
        if _command_available(candidate):
            return candidate

    if shutil.which("pipx"):
        pipx_candidate = ["pipx", "run", "--spec", "pytest", "pytest"]
        if _command_available(pipx_candidate):
            return pipx_candidate

    raise RuntimeError(
        "Could not find pytest. Install it (e.g. pip install .[test]) or install pipx."
    )


def _sample_path_from_args(args: argparse.Namespace) -> str:
    if args.hifi_sample:
        return str(Path(args.hifi_sample).expanduser())
    return os.environ.get("VHSDECODE_HIFI_RF_SAMPLE", "").strip()


def _run_unit_tests(pytest_cmd: list[str]) -> None:
    unit_path = _repo_root() / "tests" / "unit"
    _run(pytest_cmd + ["-q", str(unit_path)])


def _run_hifi_real_data_test(pytest_cmd: list[str], args: argparse.Namespace) -> None:
    sample_path = _sample_path_from_args(args)
    if not sample_path:
        if args.require_hifi_real_data:
            raise RuntimeError(
                "HiFi real-data validation requested but no sample path was provided. "
                "Use --hifi-sample or VHSDECODE_HIFI_RF_SAMPLE."
            )
        print(
            "\n[local-validate] skipping HiFi real-data test "
            "(set --hifi-sample or VHSDECODE_HIFI_RF_SAMPLE to enable).",
            flush=True,
        )
        return

    env = os.environ.copy()
    env["VHSDECODE_HIFI_RF_SAMPLE"] = sample_path
    env["VHSDECODE_HIFI_TIMEOUT_SECONDS"] = str(args.hifi_timeout_seconds)
    env["VHSDECODE_HIFI_THREADS"] = args.hifi_threads
    env["VHSDECODE_HIFI_EXTRA_ARGS"] = args.hifi_extra_args

    integration_test = (
        _repo_root() / "tests" / "integration" / "test_hifi_threading_real_data.py"
    )
    _run(pytest_cmd + ["-q", str(integration_test), "-m", "integration"], env=env)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Local pre-GitHub validation runner for unit tests plus optional "
            "real-data HiFi threading integration checks."
        )
    )
    parser.add_argument(
        "--skip-unit",
        action="store_true",
        help="Skip tests/unit.",
    )
    parser.add_argument(
        "--skip-hifi-real-data",
        action="store_true",
        help="Skip tests/integration/test_hifi_threading_real_data.py.",
    )
    parser.add_argument(
        "--require-hifi-real-data",
        action="store_true",
        help=(
            "Fail if no HiFi sample is provided instead of skipping the real-data test."
        ),
    )
    parser.add_argument(
        "--hifi-sample",
        default="",
        help=(
            "Path to RF sample for HiFi real-data test. "
            "Falls back to VHSDECODE_HIFI_RF_SAMPLE."
        ),
    )
    parser.add_argument(
        "--hifi-timeout-seconds",
        type=int,
        default=45,
        help="Timeout for each real-data threaded decode probe (default: 45).",
    )
    parser.add_argument(
        "--hifi-threads",
        default="1,4",
        help="Comma-separated thread counts to test (default: 1,4).",
    )
    parser.add_argument(
        "--hifi-extra-args",
        default="--pal --8mm",
        help="Extra args forwarded to hifi-decode in the real-data test.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.hifi_timeout_seconds < 5:
        parser.error("--hifi-timeout-seconds must be >= 5")

    pytest_cmd = _resolve_pytest_command()

    if not args.skip_unit:
        _run_unit_tests(pytest_cmd)

    if not args.skip_hifi_real_data:
        _run_hifi_real_data_test(pytest_cmd, args)

    print("\n[local-validate] completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
