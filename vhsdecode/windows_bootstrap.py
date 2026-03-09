from __future__ import annotations

import os
import sys


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


