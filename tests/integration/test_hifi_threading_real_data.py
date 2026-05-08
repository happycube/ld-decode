"""Integration checks for HiFi threading behavior on real RF samples.

These tests are opt-in and require a local sample path:
  VHSDECODE_HIFI_RF_SAMPLE=/path/to/sample.flac

Optional controls:
  VHSDECODE_HIFI_THREADS=1,4
  VHSDECODE_HIFI_TIMEOUT_SECONDS=45
  VHSDECODE_HIFI_EXTRA_ARGS="--pal --8mm"
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


def _read_required_sample_path() -> Path:
    sample_raw = os.environ.get("VHSDECODE_HIFI_RF_SAMPLE", "").strip()
    if not sample_raw:
        pytest.skip("Set VHSDECODE_HIFI_RF_SAMPLE to run real-data HiFi integration tests.")

    sample_path = Path(sample_raw).expanduser()
    if not sample_path.is_file():
        pytest.skip(f"Real RF sample not found: {sample_path}")
    return sample_path


def _read_thread_values() -> list[int]:
    raw_threads = os.environ.get("VHSDECODE_HIFI_THREADS", "1,4")
    thread_values: list[int] = []
    for item in raw_threads.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value <= 0:
            raise ValueError(f"Thread count must be > 0, got: {value}")
        thread_values.append(value)

    if not thread_values:
        raise ValueError("No thread values provided in VHSDECODE_HIFI_THREADS")

    return thread_values


def _read_timeout_seconds() -> int:
    timeout_raw = os.environ.get("VHSDECODE_HIFI_TIMEOUT_SECONDS", "45").strip()
    timeout = int(timeout_raw)
    if timeout < 5:
        raise ValueError(
            f"VHSDECODE_HIFI_TIMEOUT_SECONDS must be >= 5, got: {timeout}"
        )
    return timeout


def _read_extra_args() -> list[str]:
    raw_args = os.environ.get("VHSDECODE_HIFI_EXTRA_ARGS", "--pal --8mm").strip()
    return shlex.split(raw_args) if raw_args else []


def _run_with_timeout(command: list[str], timeout_seconds: int) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return completed.returncode, f"{completed.stdout}\n{completed.stderr}"
    except subprocess.TimeoutExpired as exc:
        output_chunks: list[str] = []
        for stream in (exc.stdout, exc.stderr):
            if stream is None:
                continue
            if isinstance(stream, bytes):
                output_chunks.append(stream.decode(errors="replace"))
            else:
                output_chunks.append(stream)
        # Use 124 to mirror GNU timeout semantics.
        return 124, "\n".join(output_chunks)


@pytest.mark.integration
def test_hifi_decode_real_data_thread_sanity(tmp_path: Path):
    hifi_decode_bin = shutil.which("hifi-decode")
    if not hifi_decode_bin:
        pytest.skip("hifi-decode executable not found on PATH.")

    sample_path = _read_required_sample_path()
    thread_values = _read_thread_values()
    timeout_seconds = _read_timeout_seconds()
    extra_args = _read_extra_args()

    for threads in thread_values:
        output_file = tmp_path / f"hifi-thread-{threads}.wav"
        command = [
            hifi_decode_bin,
            str(sample_path),
            str(output_file),
            "-t",
            str(threads),
            "--overwrite",
            *extra_args,
        ]

        exit_code, combined_output = _run_with_timeout(command, timeout_seconds)
        lowered = combined_output.lower()
        output_exists = output_file.is_file()
        output_size = output_file.stat().st_size if output_exists else 0

        # Captured stdout may be buffered under pytest/subprocess timeout, so use
        # artifact creation as the primary signal that decode actually ran.
        assert output_exists and output_size > 0, (
            f"Expected non-empty decode output for -t {threads}, got size={output_size} "
            f"(exit={exit_code}). Output:\n{combined_output}"
        )
        assert "initializing ..." in lowered, combined_output
        assert "unrecognized arguments" not in lowered, combined_output
        assert "traceback (most recent call last):" not in lowered, combined_output
        assert exit_code in (0, 124), combined_output


class _DummySignal:
    def connect(self, _callback):
        return None


class _DummyWindow:
    def __init__(self):
        self.destroyed = _DummySignal()

    def setWindowIcon(self, _icon):
        return None

    def setAttribute(self, _attribute, _enabled):
        return None


class _DummyController:
    def __init__(self):
        self.window = _DummyWindow()


@pytest.mark.integration
def test_decode_launcher_passes_hifi_threads_to_hosted_ui(monkeypatch, tmp_path: Path):
    # decode_launcher supports either Qt6 or Qt5; skip if neither is available.
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:
            pytest.skip("PyQt5/PyQt6 not available for decode-launcher integration check.")

    sample_path = _read_required_sample_path()
    output_file = tmp_path / "launcher-hifi-thread-check.wav"
    thread_value = 4

    import vhsdecode.hifi.main as hifi_main
    from vhsdecode.decode_launcher import DecodeLauncherWindow

    captured_argv: dict[str, list[str]] = {}

    def _fake_launch_hosted_ui(argv=None, app=None):
        captured_argv["argv"] = list(argv or [])
        return _DummyController()

    monkeypatch.setattr(hifi_main, "launch_hosted_ui", _fake_launch_hosted_ui)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = DecodeLauncherWindow()
    extra_args = (
        f"--pal --8mm --overwrite {shlex.quote(str(sample_path))} "
        f"{shlex.quote(str(output_file))}"
    )
    window._launch_hifi_in_process(extra_args, thread_value)
    window.close()
    app.processEvents()

    argv = captured_argv.get("argv", [])
    assert argv, "launch_hosted_ui was not called by _launch_hifi_in_process"
    assert argv[0:2] == ["-t", str(thread_value)], argv
    assert str(sample_path) in argv, argv
    assert str(output_file) in argv, argv
