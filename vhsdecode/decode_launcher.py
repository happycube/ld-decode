#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QStyleFactory,
        QVBoxLayout,
        QWidget,
    )
    ALIGN_TOP = Qt.AlignmentFlag.AlignTop
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QColor, QPalette
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QStyleFactory,
        QVBoxLayout,
        QWidget,
    )
    ALIGN_TOP = Qt.AlignTop


@dataclass(frozen=True)
class ToolSpec:
    label: str
    subcommand: str
    default_args: tuple[str, ...] = ()
    prefer_native_gui: bool = False
    notes: str = ""


TOOLS = [
    ToolSpec(
        label="hifi-decode (native GUI)",
        subcommand="hifi",
        default_args=("--gui",),
        prefer_native_gui=True,
        notes="Launches hifi-decode with --gui.",
    ),
    ToolSpec(
        label="filter-tune (native GUI)",
        subcommand="filter-tune",
        prefer_native_gui=True,
        notes="Launches filter-tune Qt frontend.",
    ),
    ToolSpec(
        label="vhs-decode (terminal)",
        subcommand="vhs",
        notes="Opens a terminal command for vhs-decode.",
    ),
    ToolSpec(
        label="cvbs-decode (terminal)",
        subcommand="cvbs",
        notes="Opens a terminal command for cvbs-decode.",
    ),
    ToolSpec(
        label="ld-decode (terminal)",
        subcommand="ld",
        notes="Opens a terminal command for ld-decode.",
    ),
]


DECODER_SUBCOMMANDS = {"vhs", "cvbs", "ld"}
SYSTEM_OPTIONS_DECODE = [
    "NTSC",
    "NTSCJ",
    "PAL",
    "PALM",
    "MPAL",
    "MESECAM",
    "405",
    "819",
    "NLINHA",
]
SYSTEM_OPTIONS_LD = ["NTSC", "NTSCJ", "PAL"]

def _decode_prefix_command() -> list[str]:
    if getattr(sys, "frozen", False):
        # In bundled binaries, the executable is the decode dispatcher itself.
        return [sys.executable]

    # Source/dev mode: run through decode.py so subcommands resolve consistently.
    decode_script = Path(__file__).resolve().parents[1] / "decode.py"
    return [sys.executable, str(decode_script)]


def _build_decode_command(tool: ToolSpec, extra_args: str) -> list[str]:
    command = _decode_prefix_command() + [tool.subcommand] + list(tool.default_args)
    if extra_args:
        command += shlex.split(extra_args)
    return command


def _build_basic_decoder_args(
    tool: ToolSpec,
    input_path: str,
    output_path: str,
    frequency: str,
    system: str,
    threads: int,
) -> list[str]:
    if tool.subcommand not in DECODER_SUBCOMMANDS:
        return []

    args = [input_path, output_path]

    if frequency.strip():
        args += ["-f", frequency.strip()]

    args += ["-t", str(threads)]

    if tool.subcommand in {"vhs", "cvbs"}:
        if system == "NTSCJ":
            args += ["--NTSCJ", "--system", "NTSC"]
        else:
            args += ["--system", system]
    elif tool.subcommand == "ld":
        if system == "PAL":
            args += ["--pal"]
        elif system == "NTSCJ":
            args += ["--NTSCJ"]

    return args


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)

def _shell_join_windows(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)

def _shell_join_platform(parts: list[str]) -> str:
    return _shell_join_windows(parts) if os.name == "nt" else _shell_join(parts)


def _open_linux_terminal(shell_command: str) -> None:
    shell = os.environ.get("SHELL", "/bin/bash")
    shell_args = [shell, "-lc", shell_command]
    terminal_candidates: list[tuple[str, list[str]]] = [
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", *shell_args]),
        ("gnome-terminal", ["gnome-terminal", "--", *shell_args]),
        ("kgx", ["kgx", "--", *shell_args]),
        ("konsole", ["konsole", "-e", *shell_args]),
        ("mate-terminal", ["mate-terminal", "--", *shell_args]),
        ("xfce4-terminal", ["xfce4-terminal", "--command", f"{shell} -lc {shlex.quote(shell_command)}"]),
        ("lxterminal", ["lxterminal", "-e", f"{shell} -lc {shlex.quote(shell_command)}"]),
        ("kitty", ["kitty", "--hold", *shell_args]),
        ("alacritty", ["alacritty", "-e", *shell_args]),
        ("xterm", ["xterm", "-hold", "-e", *shell_args]),
    ]

    for binary, command in terminal_candidates:
        if shutil.which(binary):
            subprocess.Popen(command)
            return

    raise RuntimeError(
        "Could not find a supported Linux terminal emulator (e.g. gnome-terminal, konsole, xterm)."
    )


def _open_terminal(command_parts: list[str], working_directory: Path) -> None:
    if os.name == "nt":
        command = _shell_join_windows(command_parts)
        cwd = str(working_directory).replace('"', '""')
        shell_command = (
            f'cd /d "{cwd}" && {command} '
            "& echo. "
            "& echo [decode-launcher] process finished with exit code %ERRORLEVEL%"
        )
        subprocess.Popen(["cmd.exe", "/k", shell_command])
        return

    command = _shell_join(command_parts)
    shell = os.environ.get("SHELL", "/bin/bash")
    shell_command = (
        f"cd {shlex.quote(str(working_directory))} && {command}; "
        "echo; "
        'echo "[decode-launcher] process finished with exit code $?"; '
        f"exec {shlex.quote(shell)} -l"
    )

    if sys.platform == "darwin":
        escaped = shell_command.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(
            [
                "osascript",
                "-e",
                'tell application "Terminal" to activate',
                "-e",
                f'tell application "Terminal" to do script "{escaped}"',
            ]
        )
        return

    _open_linux_terminal(shell_command)


class DecodeLauncherWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._tools = TOOLS
        self.setWindowTitle("Decode Launcher")
        self.resize(720, 280)

        self.tool_combo = QComboBox()
        for tool in self._tools:
            self.tool_combo.addItem(tool.label)
        # Default to basic VHS decode flow.
        self.tool_combo.setCurrentIndex(2)

        self.note_label = QLabel("")
        self.note_label.setWordWrap(True)

        self.extra_args_edit = QLineEdit("")
        self.force_terminal_check = QCheckBox("Force terminal launch")
        self.command_preview = QLineEdit("")
        self.command_preview.setReadOnly(True)
        self.input_edit = QLineEdit("")
        self.input_browse_button = QPushButton("Input…")
        self.output_edit = QLineEdit("")
        self.output_browse_button = QPushButton("Output…")
        self.frequency_edit = QLineEdit("40")
        self.system_combo = QComboBox()
        self.system_combo.addItems(SYSTEM_OPTIONS_DECODE)
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 64)
        self.threads_spin.setValue(4)
        self._output_manually_set = False
        self._last_decoder_tbc_path: Optional[Path] = None
        self._has_launched_decoder = False

        self.launch_button = QPushButton("Launch selected tool")
        self.launch_tbc_tools_button = QPushButton("Launch tbc-tools / ld-analyse")
        self.close_button = QPushButton("Close")

        self._build_layout()
        self._wire_events()
        self._refresh_tool_state()

    def _build_layout(self) -> None:
        root = QVBoxLayout()
        root.setAlignment(ALIGN_TOP)

        launch_group = QGroupBox("")
        launch_layout = QGridLayout()
        launch_group.setLayout(launch_layout)

        launch_layout.addWidget(QLabel("Tool"), 0, 0)
        launch_layout.addWidget(self.tool_combo, 0, 1, 1, 3)
        launch_layout.addWidget(QLabel("Input file"), 2, 0)
        launch_layout.addWidget(self.input_edit, 2, 1, 1, 2)
        launch_layout.addWidget(self.input_browse_button, 2, 3)

        launch_layout.addWidget(QLabel("Output base"), 3, 0)
        launch_layout.addWidget(self.output_edit, 3, 1, 1, 2)
        launch_layout.addWidget(self.output_browse_button, 3, 3)

        launch_layout.addWidget(QLabel("Frequency (MHz)"), 4, 0)
        launch_layout.addWidget(self.frequency_edit, 4, 1)
        launch_layout.addWidget(QLabel("TV system"), 4, 2)
        launch_layout.addWidget(self.system_combo, 4, 3)

        launch_layout.addWidget(QLabel("Threads"), 5, 0)
        launch_layout.addWidget(self.threads_spin, 5, 1)

        launch_layout.addWidget(QLabel("Extra arguments"), 6, 0)
        launch_layout.addWidget(self.extra_args_edit, 6, 1, 1, 3)

        launch_layout.addWidget(self.force_terminal_check, 7, 0, 1, 4)

        launch_layout.addWidget(QLabel("Terminal preview"), 8, 0)
        launch_layout.addWidget(self.command_preview, 8, 1, 1, 3)

        launch_layout.addWidget(self.note_label, 9, 0, 1, 4)

        action_row = QHBoxLayout()
        action_row.addWidget(self.launch_button)
        action_row.addWidget(self.launch_tbc_tools_button)
        action_row.addWidget(self.close_button)

        root.addWidget(launch_group)
        root.addLayout(action_row)
        self.setLayout(root)

    def _wire_events(self) -> None:
        self.tool_combo.currentIndexChanged.connect(self._refresh_tool_state)
        self.extra_args_edit.textChanged.connect(self._refresh_tool_state)
        self.input_edit.textChanged.connect(self._on_input_changed)
        self.output_edit.textChanged.connect(self._refresh_tool_state)
        self.output_edit.textEdited.connect(self._on_output_edited)
        self.frequency_edit.textChanged.connect(self._refresh_tool_state)
        self.system_combo.currentIndexChanged.connect(self._refresh_tool_state)
        self.threads_spin.valueChanged.connect(self._refresh_tool_state)
        self.force_terminal_check.toggled.connect(self._refresh_tool_state)
        self.input_browse_button.clicked.connect(self._browse_input_file)
        self.output_browse_button.clicked.connect(self._browse_output_file)
        self.launch_button.clicked.connect(self._launch_selected_tool)
        self.launch_tbc_tools_button.clicked.connect(self._launch_tbc_tools)
        self.close_button.clicked.connect(self.close)

    def _selected_tool(self) -> ToolSpec:
        return self._tools[self.tool_combo.currentIndex()]

    def _terminal_preview_command(self, tool: ToolSpec) -> str:
        base_cmd = _build_decode_command(tool, "")
        basic_args = _build_basic_decoder_args(
            tool=tool,
            input_path=self.input_edit.text().strip(),
            output_path=self.output_edit.text().strip(),
            frequency=self.frequency_edit.text().strip(),
            system=self.system_combo.currentText(),
            threads=self.threads_spin.value(),
        )
        extra = self.extra_args_edit.text().strip()
        if extra:
            basic_args += shlex.split(extra)
        return _shell_join_platform(base_cmd + basic_args)

    def _refresh_tool_state(self) -> None:
        tool = self._selected_tool()
        self._sync_system_options_for_tool(tool)
        self.command_preview.setText(self._terminal_preview_command(tool))
        self.note_label.setText(tool.notes)
        decoder_selected = tool.subcommand in DECODER_SUBCOMMANDS
        for widget in (
            self.input_edit,
            self.input_browse_button,
            self.output_edit,
            self.output_browse_button,
            self.frequency_edit,
            self.system_combo,
            self.threads_spin,
        ):
            widget.setEnabled(decoder_selected)

    def _sync_system_options_for_tool(self, tool: ToolSpec) -> None:
        current = self.system_combo.currentText()
        wanted = SYSTEM_OPTIONS_LD if tool.subcommand == "ld" else SYSTEM_OPTIONS_DECODE
        existing = [self.system_combo.itemText(i) for i in range(self.system_combo.count())]
        if existing == wanted:
            return
        self.system_combo.blockSignals(True)
        self.system_combo.clear()
        self.system_combo.addItems(wanted)
        self.system_combo.setCurrentText(current if current in wanted else "NTSC")
        self.system_combo.blockSignals(False)

    def _infer_default_output_base(self, input_path: str) -> str:
        if not input_path.strip():
            return ""
        path = Path(input_path.strip()).expanduser()
        parent = path.parent if path.parent.as_posix() != "." else Path.cwd()
        stem = path.stem or path.name
        return str(parent / stem)

    def _on_input_changed(self, value: str) -> None:
        if not self._output_manually_set:
            self.output_edit.setText(self._infer_default_output_base(value))
        self._refresh_tool_state()

    def _on_output_edited(self, value: str) -> None:
        self._output_manually_set = bool(value.strip())

    def _effective_working_directory(self) -> Path:
        input_path = self.input_edit.text().strip()
        if input_path:
            parent = Path(input_path).expanduser().parent
            if parent.is_dir():
                return parent.resolve()
        return Path(os.getcwd()).resolve()

    def _browse_input_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select input file",
            self.input_edit.text().strip() or str(self._effective_working_directory()),
        )
        if selected:
            self.input_edit.setText(selected)

    def _browse_output_file(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Select output base name",
            self.output_edit.text().strip() or str(self._effective_working_directory()),
        )
        if selected:
            self._output_manually_set = True
            self.output_edit.setText(selected)
    def _output_to_tbc_candidate(self, output_value: str) -> Optional[Path]:
        if not output_value.strip():
            return None

        output_path = Path(output_value.strip()).expanduser()
        if not output_path.is_absolute():
            output_path = self._effective_working_directory() / output_path
        output_path = output_path.resolve(strict=False)

        if output_path.suffix.lower() == ".tbc":
            return output_path
        return Path(str(output_path) + ".tbc")

    def _candidate_tbc_path(self) -> Optional[Path]:
        tbc_path = self._output_to_tbc_candidate(self.output_edit.text())
        decoder_selected = self._selected_tool().subcommand in DECODER_SUBCOMMANDS

        # Use explicit output path when available.
        if tbc_path is not None and (tbc_path.exists() or decoder_selected):
            return tbc_path

        # If no explicit output is currently set, fall back to the latest decoder
        # launch from this session to keep ld-analyse aligned with active decodes.
        if (
            tbc_path is None
            and self._has_launched_decoder
            and self._last_decoder_tbc_path is not None
        ):
            return self._last_decoder_tbc_path
        return None

    def _find_tbc_tools_executable(self) -> Optional[Path]:
        search_roots: list[Path] = []
        if sys.platform == "darwin":
            search_roots.extend([Path("/Applications"), Path.home() / "Applications"])
        elif os.name == "nt":
            search_roots.extend(
                [
                    Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
                    Path.home() / "AppData" / "Local" / "Programs",
                ]
            )

        if getattr(sys, "frozen", False):
            decode_exe = Path(sys.executable).resolve()
            search_roots.extend(
                [decode_exe.parent, decode_exe.parent.parent, decode_exe.parent.parent.parent]
            )
            # In app bundles, also search where the .app lives.
            for parent in decode_exe.parents:
                if parent.name == "MacOS" and parent.parent.name == "Contents":
                    app_dir = parent.parent.parent
                    search_roots.extend([app_dir.parent, app_dir.parent.parent])
                    break
        else:
            repo_root = Path(__file__).resolve().parents[1]
            search_roots.extend([repo_root, repo_root.parent, self._effective_working_directory()])

        # De-duplicate while preserving order.
        deduped_roots: list[Path] = []
        seen: set[str] = set()
        for root in search_roots:
            key = str(root.resolve()) if root.exists() else str(root)
            if key not in seen:
                seen.add(key)
                deduped_roots.append(root)
        def root_candidates(root: Path) -> list[Path]:
            if os.name == "nt":
                return [
                    root / "ld-analyse.exe",
                    root / "tbc-tools.exe",
                    root / "tbc-tools" / "ld-analyse.exe",
                ]
            if sys.platform == "darwin":
                return [
                    root / "tbc-tools.app" / "Contents" / "MacOS" / "ld-analyse",
                    root / "ld-analyse.app" / "Contents" / "MacOS" / "ld-analyse",
                    root / "ld-analyse",
                ]
            return [
                root / "ld-analyse",
                root / "tbc-tools.AppImage",
                root / "tbc-tools.appimage",
                root / "tbc-tools" / "ld-analyse",
            ]

        def child_candidates(child: Path) -> list[Path]:
            if os.name == "nt":
                return [
                    child / "ld-analyse.exe",
                    child / "tbc-tools.exe",
                    child / "tbc-tools" / "ld-analyse.exe",
                ]
            if sys.platform == "darwin":
                if child.suffix.lower() == ".app":
                    return [
                        child / "Contents" / "MacOS" / "ld-analyse",
                        child / "Contents" / "MacOS" / "tbc-tools",
                    ]
                return [
                    child / "tbc-tools.app" / "Contents" / "MacOS" / "ld-analyse",
                    child / "ld-analyse.app" / "Contents" / "MacOS" / "ld-analyse",
                    child / "ld-analyse",
                ]
            return [
                child / "ld-analyse",
                child / "tbc-tools.AppImage",
                child / "tbc-tools.appimage",
                child / "tbc-tools" / "ld-analyse",
            ]

        for root in deduped_roots:
            candidates = root_candidates(root)

            # Also check one level down from the root (common unpack layouts).
            try:
                children = list(root.iterdir()) if root.exists() else []
            except OSError:
                children = []

            for child in children:
                if child.is_dir():
                    candidates.extend(child_candidates(child))

            for candidate in candidates:
                if candidate.exists() and candidate.is_file():
                    return candidate
        return None

    def _launch_tbc_tools(self) -> None:
        executable = self._find_tbc_tools_executable()
        if executable is None:
            QMessageBox.critical(
                self,
                "tbc-tools not found",
                "Could not find tbc-tools / ld-analyse near the decode binary or working folder.",
            )
            return

        command = [str(executable)]
        tbc_candidate = self._candidate_tbc_path()
        if tbc_candidate is not None:
            command.append(str(tbc_candidate))

        try:
            subprocess.Popen(command, cwd=str(self._effective_working_directory()))
        except Exception as exc:
            QMessageBox.critical(self, "Launch failed", str(exc))
            return

    def _launch_selected_tool(self) -> None:
        tool = self._selected_tool()
        working_directory = self._effective_working_directory()

        if not working_directory.is_dir():
            QMessageBox.critical(
                self,
                "Invalid working directory",
                f"Directory does not exist:\n{working_directory}",
            )
            return

        extra = self.extra_args_edit.text().strip()

        try:
            command = _build_decode_command(tool, "")
            basic_args = _build_basic_decoder_args(
                tool=tool,
                input_path=self.input_edit.text().strip(),
                output_path=self.output_edit.text().strip(),
                frequency=self.frequency_edit.text().strip(),
                system=self.system_combo.currentText(),
                threads=self.threads_spin.value(),
            )

            if tool.subcommand in DECODER_SUBCOMMANDS:
                if not self.input_edit.text().strip():
                    QMessageBox.critical(self, "Missing input file", "Select an input file.")
                    return
                if not self.output_edit.text().strip():
                    QMessageBox.critical(self, "Missing output path", "Select an output base path.")
                    return
                self._last_decoder_tbc_path = self._output_to_tbc_candidate(
                    self.output_edit.text()
                )
                self._has_launched_decoder = self._last_decoder_tbc_path is not None

            command += basic_args
            if extra:
                command += shlex.split(extra)

            if tool.prefer_native_gui and not self.force_terminal_check.isChecked():
                if os.name == "nt":
                    start_command = f'start "" {_shell_join_windows(command)}'
                    subprocess.Popen(["cmd.exe", "/c", start_command], cwd=str(working_directory))
                else:
                    subprocess.Popen(command, cwd=str(working_directory))
            else:
                _open_terminal(command, working_directory)
        except Exception as exc:
            QMessageBox.critical(self, "Launch failed", str(exc))
            return

def _apply_fusion_dark_mode(app: QApplication) -> None:
    fusion_style = QStyleFactory.create("Fusion")
    if fusion_style is not None:
        app.setStyle(fusion_style)
    else:
        app.setStyle("Fusion")

    role = QPalette.ColorRole if hasattr(QPalette, "ColorRole") else QPalette
    group = QPalette.ColorGroup if hasattr(QPalette, "ColorGroup") else QPalette

    palette = QPalette()
    palette.setColor(role.Window, QColor(53, 53, 53))
    palette.setColor(role.WindowText, QColor(225, 225, 225))
    palette.setColor(role.Base, QColor(35, 35, 35))
    palette.setColor(role.AlternateBase, QColor(53, 53, 53))
    palette.setColor(role.ToolTipBase, QColor(30, 30, 30))
    palette.setColor(role.ToolTipText, QColor(225, 225, 225))
    palette.setColor(role.Text, QColor(225, 225, 225))
    palette.setColor(role.Button, QColor(53, 53, 53))
    palette.setColor(role.ButtonText, QColor(225, 225, 225))
    palette.setColor(role.BrightText, QColor(255, 80, 80))
    palette.setColor(role.Highlight, QColor(42, 130, 218))
    palette.setColor(role.HighlightedText, QColor(20, 20, 20))
    palette.setColor(group.Disabled, role.Text, QColor(120, 120, 120))
    palette.setColor(group.Disabled, role.ButtonText, QColor(120, 120, 120))
    palette.setColor(group.Disabled, role.WindowText, QColor(120, 120, 120))
    app.setPalette(palette)
    app.setStyleSheet(
        "QToolTip { color: #e1e1e1; background-color: #2b2b2b; border: 1px solid #4a4a4a; }"
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decode Launcher (Qt) for starting decode/tools commands"
    )
    parser.parse_args(argv)

    app = QApplication(sys.argv)
    _apply_fusion_dark_mode(app)
    window = DecodeLauncherWindow()
    window.show()
    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
