#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
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
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class ToolSpec:
    label: str
    terminal_cmd: str
    native_gui_cmd: Optional[list[str]] = None
    notes: str = ""

    @property
    def has_native_gui(self) -> bool:
        return self.native_gui_cmd is not None


def _entrypoint_or_module_cmd(entrypoint: str, module: str) -> str:
    executable = shutil.which(entrypoint)
    if executable:
        return shlex.quote(executable)
    return f"{shlex.quote(sys.executable)} -m {module}"


def _terminal_command_for(tool_key: str) -> str:
    commands = {
        "vhs": f"{_entrypoint_or_module_cmd('vhs-decode', 'vhsdecode.main')} --help",
        "cvbs": (
            f"{_entrypoint_or_module_cmd('cvbs-decode', 'cvbsdecode.main')} --help"
        ),
        "ld": f"{_entrypoint_or_module_cmd('ld-decode', 'lddecode.main')} --help",
        "hifi": (
            f"{_entrypoint_or_module_cmd('hifi-decode', 'vhsdecode.hifi.main')} --gui"
        ),
        "filter_tune": (
            f"{_entrypoint_or_module_cmd('filter-tune', 'filter_tune.filter_tune')}"
        ),
    }
    return commands[tool_key]


TOOLS = [
    ToolSpec(
        label="hifi-decode (native GUI)",
        terminal_cmd=_terminal_command_for("hifi"),
        native_gui_cmd=[sys.executable, "-m", "vhsdecode.hifi.main", "--gui"],
        notes="Launches hifi-decode with --gui.",
    ),
    ToolSpec(
        label="filter-tune (native GUI)",
        terminal_cmd=_terminal_command_for("filter_tune"),
        native_gui_cmd=[sys.executable, "-m", "filter_tune.filter_tune"],
        notes="Launches filter-tune Qt frontend.",
    ),
    ToolSpec(
        label="vhs-decode (terminal)",
        terminal_cmd=_terminal_command_for("vhs"),
        notes="Opens a terminal command for vhs-decode.",
    ),
    ToolSpec(
        label="cvbs-decode (terminal)",
        terminal_cmd=_terminal_command_for("cvbs"),
        notes="Opens a terminal command for cvbs-decode.",
    ),
    ToolSpec(
        label="ld-decode (terminal)",
        terminal_cmd=_terminal_command_for("ld"),
        notes="Opens a terminal command for ld-decode.",
    ),
]


def _open_terminal(command: str, working_directory: Path) -> None:
    shell_command = (
        f"cd {shlex.quote(str(working_directory))} && {command}; "
        "echo; "
        'echo "[decode-launcher] process finished with exit code $?"; '
        "exec $SHELL -l"
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

    if os.name == "nt":
        subprocess.Popen(["cmd.exe", "/k", shell_command])
        return

    raise RuntimeError(
        "Terminal launching is implemented for macOS and Windows in this launcher."
    )


class DecodeLauncherWindow(QWidget):
    def __init__(self, default_working_directory: Path):
        super().__init__()
        self._tools = TOOLS
        self.setWindowTitle("Decode Launcher (Qt6)")
        self.resize(720, 280)

        self.tool_combo = QComboBox()
        for tool in self._tools:
            self.tool_combo.addItem(tool.label)

        self.note_label = QLabel("")
        self.note_label.setWordWrap(True)

        self.cwd_edit = QLineEdit(str(default_working_directory))
        self.cwd_browse_button = QPushButton("Browse…")

        self.extra_args_edit = QLineEdit("")
        self.force_terminal_check = QCheckBox("Force terminal launch")
        self.command_preview = QLineEdit("")
        self.command_preview.setReadOnly(True)

        self.launch_button = QPushButton("Launch selected tool")
        self.close_button = QPushButton("Close")

        self._build_layout()
        self._wire_events()
        self._refresh_tool_state()

    def _build_layout(self) -> None:
        root = QVBoxLayout()
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        launch_group = QGroupBox("Decode Launcher")
        launch_layout = QGridLayout()
        launch_group.setLayout(launch_layout)

        launch_layout.addWidget(QLabel("Tool"), 0, 0)
        launch_layout.addWidget(self.tool_combo, 0, 1, 1, 3)

        launch_layout.addWidget(QLabel("Working directory"), 1, 0)
        launch_layout.addWidget(self.cwd_edit, 1, 1, 1, 2)
        launch_layout.addWidget(self.cwd_browse_button, 1, 3)

        launch_layout.addWidget(QLabel("Extra arguments"), 2, 0)
        launch_layout.addWidget(self.extra_args_edit, 2, 1, 1, 3)

        launch_layout.addWidget(self.force_terminal_check, 3, 0, 1, 4)

        launch_layout.addWidget(QLabel("Terminal preview"), 4, 0)
        launch_layout.addWidget(self.command_preview, 4, 1, 1, 3)

        launch_layout.addWidget(self.note_label, 5, 0, 1, 4)

        action_row = QHBoxLayout()
        action_row.addWidget(self.launch_button)
        action_row.addWidget(self.close_button)

        root.addWidget(launch_group)
        root.addLayout(action_row)
        self.setLayout(root)

    def _wire_events(self) -> None:
        self.tool_combo.currentIndexChanged.connect(self._refresh_tool_state)
        self.extra_args_edit.textChanged.connect(self._refresh_tool_state)
        self.force_terminal_check.toggled.connect(self._refresh_tool_state)
        self.cwd_browse_button.clicked.connect(self._browse_working_directory)
        self.launch_button.clicked.connect(self._launch_selected_tool)
        self.close_button.clicked.connect(self.close)

    def _selected_tool(self) -> ToolSpec:
        return self._tools[self.tool_combo.currentIndex()]

    def _terminal_preview_command(self, tool: ToolSpec) -> str:
        extra = self.extra_args_edit.text().strip()
        if extra:
            return f"{tool.terminal_cmd} {extra}"
        return tool.terminal_cmd

    def _refresh_tool_state(self) -> None:
        tool = self._selected_tool()
        self.command_preview.setText(self._terminal_preview_command(tool))
        self.note_label.setText(tool.notes)

    def _browse_working_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select working directory",
            self.cwd_edit.text().strip() or os.getcwd(),
        )
        if selected:
            self.cwd_edit.setText(selected)

    def _launch_selected_tool(self) -> None:
        tool = self._selected_tool()
        working_directory = Path(self.cwd_edit.text().strip() or os.getcwd()).expanduser()
        working_directory = working_directory.resolve()

        if not working_directory.is_dir():
            QMessageBox.critical(
                self,
                "Invalid working directory",
                f"Directory does not exist:\n{working_directory}",
            )
            return

        extra = self.extra_args_edit.text().strip()

        try:
            if tool.has_native_gui and not self.force_terminal_check.isChecked():
                command = list(tool.native_gui_cmd or [])
                if extra:
                    command += shlex.split(extra)
                subprocess.Popen(command, cwd=str(working_directory))
            else:
                _open_terminal(self._terminal_preview_command(tool), working_directory)
        except Exception as exc:
            QMessageBox.critical(self, "Launch failed", str(exc))
            return

        QMessageBox.information(self, "Launch started", f"Started: {tool.label}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decode Launcher (Qt6) for starting decode/tools commands"
    )
    parser.add_argument(
        "--cwd",
        dest="working_directory",
        default=os.getcwd(),
        help="Initial working directory shown in the launcher",
    )
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    window = DecodeLauncherWindow(Path(args.working_directory))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
