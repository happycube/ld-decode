from __future__ import annotations

import os
import sys
_DEVNULL_STDIO = None


def prepare_frozen_windows_gui_launch() -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return

    _detach_explorer_console()


def _detach_explorer_console() -> None:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    console_window = kernel32.GetConsoleWindow()
    if not console_window:
        return

    process_list = (wintypes.DWORD * 2)()
    process_count = kernel32.GetConsoleProcessList(process_list, len(process_list))

    # If the launcher was started from an existing terminal, leave that console
    # attached. When started directly from Explorer, hide and detach the
    # transient boot console before the Qt window appears.
    if process_count > 1:
        return

    user32.ShowWindow(console_window, 0)
    kernel32.FreeConsole()
    _redirect_detached_stdio_to_devnull()


def _redirect_detached_stdio_to_devnull() -> None:
    global _DEVNULL_STDIO

    if _DEVNULL_STDIO is not None:
        return

    stdin_stream = open(os.devnull, "r", encoding="utf-8", errors="ignore")
    stdout_stream = open(os.devnull, "w", encoding="utf-8", errors="ignore", buffering=1)
    stderr_stream = open(os.devnull, "w", encoding="utf-8", errors="ignore", buffering=1)

    _DEVNULL_STDIO = (stdin_stream, stdout_stream, stderr_stream)
    sys.stdin = stdin_stream
    sys.stdout = stdout_stream
    sys.stderr = stderr_stream
    sys.__stdin__ = stdin_stream
    sys.__stdout__ = stdout_stream
    sys.__stderr__ = stderr_stream


