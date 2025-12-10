import os.path
import sys
import math

import numpy as np

import matplotlib
matplotlib.use("Qt5Agg")  # Must come before importing pyplot
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt

try:
    from PyQt6.QtGui import QIcon, QPalette
    from PyQt6.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QDial,
        QCheckBox,
        QComboBox,
        QPushButton,
        QLineEdit,
        QFileDialog,
        QDialog,
        QMessageBox,
        QSpinBox,
        QFrame,
        QSizePolicy,
        QGridLayout,
    )
    from PyQt6 import QtGui, QtCore
except ImportError:
    from PyQt5.QtGui import QIcon, QPalette
    from PyQt5.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QDial,
        QCheckBox,
        QComboBox,
        QPushButton,
        QLineEdit,
        QFileDialog,
        QDialog,
        QMessageBox,
        QSpinBox,
        QFrame,
        QSizePolicy,
        QGridLayout,
    )
    from PyQt5 import QtGui, QtCore

from vhsdecode.hifi.HiFiDecode import (
    DEFAULT_EXPANDER_GAIN,
    DEFAULT_EXPANDER_RATIO,
    DEFAULT_EXPANDER_ATTACK_TAU,
    DEFAULT_EXPANDER_RELEASE_TAU,
    DEFAULT_VHS_DEEMPHASIS_TAU_1,
    DEFAULT_VHS_DEEMPHASIS_TAU_2,
    DEFAULT_VHS_DEEMPHASIS_DB_PER_OCTAVE,
    DEFAULT_VHS_DEEMPHASIS_BANDWIDTH,
    DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1,
    DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2,
    DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE,
    DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH,

    DEFAULT_8MM_DEEMPHASIS_TAU_1,
    DEFAULT_8MM_DEEMPHASIS_TAU_2,
    DEFAULT_8MM_DEEMPHASIS_DB_PER_OCTAVE,
    DEFAULT_8MM_DEEMPHASIS_BANDWIDTH,
    DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_1,
    DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_2,
    DEFAULT_8MM_EXPANDER_WEIGHTING_DB_PER_OCTAVE,
    DEFAULT_8MM_EXPANDER_WEIGHTING_BANDWIDTH,

    DEFAULT_SPECTRAL_NR_AMOUNT,
    DEFAULT_RESAMPLER_QUALITY,
    DEMOD_QUADRATURE,
    DEMOD_HILBERT,
    DEFAULT_DEMOD,
    tau_as_freq,
    HiFiDecode,
    Deemphasis,
    Expander
)

STOP_STATE = 0
PLAY_STATE = 1
PAUSE_STATE = 2
PREVIEW_STATE = 3


class MainUIParameters:
    def __init__(self):
        self.volume: float = 1.0
        self.normalize = False
        self.expander_gain: float = DEFAULT_EXPANDER_GAIN
        self.expander_ratio: float = DEFAULT_EXPANDER_RATIO
        self.expander_attack_tau: float = DEFAULT_EXPANDER_ATTACK_TAU
        self.expander_release_tau: float = DEFAULT_EXPANDER_RELEASE_TAU
        self.expander_weighting_low_tau: float = DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1
        self.expander_weighting_high_tau: float = DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2
        self.expander_weighting_db_per_octave: float = DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE
        self.expander_weighting_bandwidth: float = DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH
        self.deemphasis_low_tau: float = DEFAULT_VHS_DEEMPHASIS_TAU_1
        self.deemphasis_high_tau: float = DEFAULT_VHS_DEEMPHASIS_TAU_2
        self.deemphasis_db_per_octave: float = DEFAULT_VHS_DEEMPHASIS_DB_PER_OCTAVE
        self.deemphasis_bandwidth: float = DEFAULT_VHS_DEEMPHASIS_BANDWIDTH
        self.afe_vco_deviation = 0
        self.afe_left_carrier = 0
        self.afe_right_carrier = 0
        self.spectral_nr_amount = DEFAULT_SPECTRAL_NR_AMOUNT
        self.enable_expander: bool = True
        self.enable_deemphasis: bool = True
        self.automatic_fine_tuning: bool = True
        self.bias_guess: bool = False
        self.grc = False
        self.audio_sample_rate: int = 48000
        self.standard: str = "NTSC"
        self.format: str = "VHS"
        self.audio_mode: str = "Stereo"
        self.resampler_quality = DEFAULT_RESAMPLER_QUALITY
        self.demod_type: str = DEFAULT_DEMOD.capitalize()
        self.input_sample_rate: float = 40.0
        self.input_file: str = ""
        self.output_file: str = ""
        self.head_switching_interpolation = "on"
        self.muting = "on"


def decode_options_to_ui_parameters(decode_options):
    values = MainUIParameters()
    values.volume = decode_options["gain"]
    values.normalize = decode_options["normalize"]
    values.enable_expander = decode_options["enable_expander"]
    values.enable_deemphasis = decode_options["enable_deemphasis"]
    values.expander_gain = decode_options["expander_gain"]
    values.expander_ratio = decode_options["expander_ratio"]
    values.expander_attack_tau = decode_options["expander_attack_tau"]
    values.expander_release_tau = decode_options["expander_release_tau"]
    values.expander_weighting_low_tau = decode_options["expander_weighting_low_tau"]
    values.expander_weighting_high_tau = decode_options["expander_weighting_high_tau"]
    values.expander_weighting_db_per_octave = decode_options["expander_weighting_db_per_octave"]
    values.expander_weighting_bandwidth = decode_options["expander_weighting_bandwidth"]
    values.deemphasis_low_tau = decode_options["deemphasis_low_tau"]
    values.deemphasis_high_tau = decode_options["deemphasis_high_tau"]
    values.deemphasis_db_per_octave = decode_options["deemphasis_db_per_octave"]
    values.deemphasis_bandwidth = decode_options["deemphasis_bandwidth"]
    values.afe_vco_deviation = decode_options["afe_vco_deviation"]
    values.afe_left_carrier = decode_options["afe_left_carrier"]
    values.afe_right_carrier = decode_options["afe_right_carrier"]
    values.spectral_nr_amount = decode_options["spectral_nr_amount"]
    values.automatic_fine_tuning = decode_options["auto_fine_tune"]
    values.bias_guess = decode_options["bias_guess"]
    values.audio_sample_rate = decode_options["audio_rate"]
    values.standard = "PAL" if decode_options["standard"] == "p" else "NTSC"
    values.format = "VHS" if decode_options["format"] == "vhs" else "Video8/Hi8"
    values.audio_mode = "Stereo"
    values.resampler_quality = decode_options["resampler_quality"]
    values.demod_type = decode_options["demod_type"].capitalize()
    values.input_sample_rate = decode_options["input_rate"]
    values.input_file = decode_options["input_file"]
    values.output_file = decode_options["output_file"]
    values.head_switching_interpolation = decode_options["head_switching_interpolation"]
    values.muting = decode_options["muting"]
    return values


def ui_parameters_to_decode_options(values: MainUIParameters):
    decode_options = {
        "input_rate": float(values.input_sample_rate) * 1e6,
        "standard": "p" if values.standard == "PAL" else "n",
        "format": "vhs" if values.format == "VHS" else "8mm",
        "demod_type": values.demod_type.lower(),
        "auto_fine_tune": values.automatic_fine_tuning,
        "bias_guess": values.bias_guess,
        "enable_expander": values.enable_expander,
        "enable_deemphasis": values.enable_deemphasis,
        "expander_gain": values.expander_gain,
        "expander_ratio": values.expander_ratio,
        "expander_attack_tau": values.expander_attack_tau,
        "expander_release_tau": values.expander_release_tau,
        "expander_weighting_low_tau": values.expander_weighting_low_tau,
        "expander_weighting_high_tau": values.expander_weighting_high_tau,
        "expander_weighting_db_per_octave": values.expander_weighting_db_per_octave,
        "expander_weighting_bandwidth": values.expander_weighting_bandwidth,
        "deemphasis_low_tau": values.deemphasis_low_tau,
        "deemphasis_high_tau": values.deemphasis_high_tau,
        "deemphasis_db_per_octave": values.deemphasis_db_per_octave,
        "deemphasis_bandwidth": values.deemphasis_bandwidth,
        "afe_vco_deviation": values.afe_vco_deviation,
        "afe_left_carrier": values.afe_left_carrier,
        "afe_right_carrier": values.afe_right_carrier,
        "spectral_nr_amount": values.spectral_nr_amount,
        "grc": values.grc,
        "audio_rate": values.audio_sample_rate,
        "gain": values.volume,
        "normalize": values.normalize,
        "input_file": values.input_file,
        "output_file": values.output_file,
        "resampler_quality": values.resampler_quality,
        "head_switching_interpolation": values.head_switching_interpolation,
        "muting": values.muting,
        "mode": (
            "s"
            if values.audio_mode == "Stereo"
            else (
                "l"
                if values.audio_mode == "L"
                else (
                    "r"
                    if values.audio_mode == "R"
                    else "mpx" if values.audio_mode == "Stereo MPX" else "sum"
                )
            )
        ),
    }
    return decode_options


class InputDialog(QDialog):
    def __init__(self, label: str, title: str, value=None, validator=None):
        super().__init__()
        self.validator = validator
        self.label = label
        self.value = value
        self.title = title
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(self.title)

        layout = QHBoxLayout()

        self.input_line = QLineEdit(self)
        self.input_line.setText(str(self.value))

        if self.validator is not None:
            self.input_line.setValidator(self.validator)
        layout.addWidget(self.input_line)

        label = QLabel(self.label, self)
        layout.addWidget(label)

        ok_button = QPushButton("Accept", self)
        ok_button.clicked.connect(self.accept_user_input)
        layout.addWidget(ok_button)

        self.setLayout(layout)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #333;
                color: #eee;
            }
            QLineEdit {
                background-color: #555;
                color: #eee;
                border: 1px solid #777;
            }
            QPushButton {
                background-color: #555;
                color: #eee;
                border: 1px solid #777;
            }
            QLabel {
                color: #eee;
            }
        """
        )

        # Set dialog size
        self.setFixedWidth(int(self.sizeHint().width()))
        self.setFixedHeight(self.sizeHint().height())

    def accept_user_input(self):
        self.value = self.input_line.text()
        self.accept()

    def get_input_value(self):
        self.exec()
        return self.value


class HifiUi(QMainWindow):
    def __init__(
        self,
        params: MainUIParameters,
        title: str = "HiFi Main Controls",
        main_layout_callback=None,
    ):
        super(HifiUi, self).__init__()

        self._transport_state = STOP_STATE

        # Set up the main window
        self.setWindowTitle(title)

        self.collapsableSections = []

        # Create central widget and layout
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        self.central_widget.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )

        self.main_layout: QHBoxLayout = QVBoxLayout(self.central_widget)
        main_layout_callback(self.main_layout)

        # Inner controls layout
        controls_layout = QVBoxLayout()
        self.main_layout.addLayout(controls_layout)

        # Input sample rate selection
        input_options_section = self.build_input_options_section()
        controls_layout.addLayout(input_options_section)

        # Format options Analog Front End adjustments
        format_system_options = self.build_format_options_section()
        controls_layout.addLayout(format_system_options)

        # Demodulation options section
        demodulation_options = self.build_demodulation_options_section()
        controls_layout.addLayout(demodulation_options)

        # Deemphasis options
        expander_deemphasis_options = self.build_expander_deemphasis_section()
        controls_layout.addLayout(expander_deemphasis_options)

        # Noise Reduction Options section
        noise_reduction_options = self.build_noise_reduction_section()
        controls_layout.addLayout(noise_reduction_options)

        # Audio Processing Options section
        audio_processing_options = self.build_audio_processing_options_section()
        controls_layout.addLayout(audio_processing_options)

        # Transport controls
        transport_controls_layout = self.build_transport_controls()
        self.main_layout.addLayout(transport_controls_layout)

        # Weighting / Deemphasis plot
        self.build_plot_window()

        # Apply dark theme with improved text visibility
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #333;
                color: #eee;
            }
            QDial, QLineEdit, QCheckBox, QComboBox, QPushButton {
                background-color: #555;
                color: #eee;
                border: 1px solid #777;
            }
            QDial {
                min-width: 50px;
                max-width: 50px;
                min-height: 50px;
                max-height: 50px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::item {
                background-color: #555;
                color: #eee;
            }
            QLabel {
                color: #eee;
            }
        """
        )
        self.change_button_color(self.stop_button, "#eee")
        # disables maximize button
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowType.WindowMaximizeButtonHint
        )
        self.resize_window()
        # sets default window icon
        self.setWindowIcon(QIcon.fromTheme("document-open"))
        self.setValues(params)

        # update this at the end so the window width is calculated with everything expanded
        for collapsableSection in self.collapsableSections:
            collapsableSection.setDefaultCollapseState()

    def resize_window(self, axis="hv"):
        self.central_widget.adjustSize()
        # disables resize
        if "h" in axis:
            self.setFixedWidth(int(self.minimumSizeHint().width()))
        # sets fixed height
        if "v" in axis:
            self.setFixedHeight(self.minimumSizeHint().height())

    def build_transport_controls(self):
        transport_controls_layout = QHBoxLayout()

        # Playback controls
        self.preview_button = QPushButton("Preview", self)
        self.play_button = QPushButton("▶", self)  # Play symbol
        self.pause_button = QPushButton("||", self)  # Pause symbol
        self.stop_button = QPushButton("■", self)  # Stop symbol
        max_button_height = max(
            self.preview_button.sizeHint().height(),
            self.play_button.sizeHint().height(),
            self.pause_button.sizeHint().height(),
            self.stop_button.sizeHint().height(),
        )
        self.preview_button.setFixedHeight(max_button_height)
        self.play_button.setFixedHeight(max_button_height)
        self.pause_button.setFixedHeight(max_button_height)
        self.stop_button.setFixedHeight(max_button_height)
        transport_controls_layout.addWidget(self.preview_button)
        transport_controls_layout.addWidget(self.play_button)
        transport_controls_layout.addWidget(self.pause_button)
        transport_controls_layout.addWidget(self.stop_button)

        self.preview_button.clicked.connect(self.on_preview_clicked)
        self.play_button.clicked.connect(self.on_play_clicked)
        self.pause_button.clicked.connect(self.on_pause_clicked)
        self.stop_button.clicked.connect(self.on_stop_clicked)

        return transport_controls_layout

    def build_input_options_section(self):
        layout = QVBoxLayout()

        input_options_frame = CollapsableSection(self, "Input Options")
        layout.addLayout(input_options_frame)

        # input sample rate
        input_samplerate_layout = QHBoxLayout()
        input_samplerate_label = QLabel("Input Sample Rate (MHz)")
        self.input_samplerate_combo = QComboBox(self)
        self.input_samplerate_combo.addItems(
            [
                "DdD (40)",
                "Clockgen (10)",
                "RTLSDR (8)",
                "cxadc (28.64)",
                "cxadc3 (35.8)",
                "10cxadc (14.32)",
                "10cxadc3 (17.9)",
                "Other",
            ]
        )
        self._input_combo_rates = [
            40.0,
            10.0,
            8.0,
            28.64,
            35.8,
            14.32,
            17.9,
        ]
        input_samplerate_layout.addWidget(input_samplerate_label)
        input_samplerate_layout.addWidget(self.input_samplerate_combo)
        self.input_samplerate_combo.setCurrentIndex(-1)
        self.input_samplerate_combo.currentIndexChanged.connect(
            self.on_input_samplerate_changed
        )
        input_options_frame.inner_layout.addLayout(input_samplerate_layout)

        return layout

    def build_format_options_section(self):
        layout = QVBoxLayout()

        format_options_frame = CollapsableSection(self, "Format Options")
        layout.addLayout(format_options_frame)

        # standard option
        standard_layout = QHBoxLayout()
        standard_label = QLabel("Standard")
        self.standard_combo = QComboBox(self)
        self.standard_combo.addItems(["PAL", "NTSC"])
        standard_layout.addWidget(standard_label)
        standard_layout.addWidget(self.standard_combo)
        self.standard_combo.currentIndexChanged.connect(self.on_standard_change)
        format_options_frame.inner_layout.addLayout(standard_layout)

        # format option
        format_layout = QHBoxLayout()
        format_label = QLabel("Format")
        self.format_combo = QComboBox(self)
        self.format_combo.addItems(["VHS", "Video8/Hi8"])
        format_layout.addWidget(format_label)
        format_layout.addWidget(self.format_combo)
        self.format_combo.currentIndexChanged.connect(self.on_format_change)
        format_options_frame.inner_layout.addLayout(format_layout)

        advanced_format_options_frame = CollapsableSection(
            self, "Advanced Format Options", default_collapsed=True
        )
        layout.addLayout(advanced_format_options_frame)

        # auto fine tune
        self.automatic_fine_tuning_checkbox = QCheckBox("Automatic fine tuning")
        self.automatic_fine_tuning_checkbox.setToolTip(
            "Automatically adjust bias during decode. Not applicable to Quadrature demodulation."
        )
        advanced_format_options_frame.inner_layout.addWidget(
            self.automatic_fine_tuning_checkbox
        )

        # bias guess
        self.bias_guess_checkbox = QCheckBox("Bias Guess")
        self.bias_guess_checkbox.setToolTip("Attempt to guess the carrier frequencies")
        advanced_format_options_frame.inner_layout.addWidget(self.bias_guess_checkbox)

        # left carrier adjustment
        afe_left_carrier_layout = QHBoxLayout()
        afe_left_carrier_spinbox_label = QLabel("Left Carrier (Hz)")
        self.afe_left_carrier_spinbox = QSpinBox(self)
        self.afe_left_carrier_spinbox.setGroupSeparatorShown(True)
        self.afe_left_carrier_spinbox.setMinimum(int(10e5))
        self.afe_left_carrier_spinbox.setMaximum(int(10e6))
        self.afe_left_carrier_spinbox.setSingleStep(100)
        self.afe_left_carrier_spinbox.setToolTip("Left carrier center frequency")
        afe_left_carrier_layout.addWidget(afe_left_carrier_spinbox_label)
        afe_left_carrier_layout.addWidget(self.afe_left_carrier_spinbox)
        advanced_format_options_frame.inner_layout.addLayout(afe_left_carrier_layout)

        # right carrier adjustment
        afe_right_carrier_layout = QHBoxLayout()
        afe_right_carrier_spinbox_label = QLabel("Right Carrier (Hz)")
        self.afe_right_carrier_spinbox = QSpinBox(self)
        self.afe_right_carrier_spinbox.setGroupSeparatorShown(True)
        self.afe_right_carrier_spinbox.setMinimum(int(10e5))
        self.afe_right_carrier_spinbox.setMaximum(int(10e6))
        self.afe_right_carrier_spinbox.setSingleStep(100)
        self.afe_right_carrier_spinbox.setToolTip("Right carrier center frequency")
        afe_right_carrier_layout.addWidget(afe_right_carrier_spinbox_label)
        afe_right_carrier_layout.addWidget(self.afe_right_carrier_spinbox)
        advanced_format_options_frame.inner_layout.addLayout(afe_right_carrier_layout)

        # vco deviation adjustment
        afe_vco_deviation_layout = QHBoxLayout()
        afe_vco_deviation_spinbox_label = QLabel("VCO Deviation")
        self.afe_vco_deviation_spinbox = QSpinBox(self)
        self.afe_vco_deviation_spinbox.setGroupSeparatorShown(True)
        self.afe_vco_deviation_spinbox.setMinimum(int(10e3))
        self.afe_vco_deviation_spinbox.setMaximum(int(10e5))
        self.afe_vco_deviation_spinbox.setSingleStep(10)
        self.afe_vco_deviation_spinbox.setToolTip(
            "Maximum frequency offset + or - from the center frequency"
        )
        afe_vco_deviation_layout.addWidget(afe_vco_deviation_spinbox_label)
        afe_vco_deviation_layout.addWidget(self.afe_vco_deviation_spinbox)
        advanced_format_options_frame.inner_layout.addLayout(afe_vco_deviation_layout)
        return layout

    def build_demodulation_options_section(self):
        layout = QVBoxLayout()

        demodulation_options_frame = CollapsableSection(
            self, "Demodulation Options", default_collapsed=True
        )
        layout.addLayout(demodulation_options_frame)

        # demodulation type option
        demod_type_layout = QHBoxLayout()
        demod_type_label = QLabel("FM Demodulation Type")
        self.demod_type_combo = QComboBox(self)
        self.demod_type_combo.addItems(
            [DEMOD_QUADRATURE.capitalize(), DEMOD_HILBERT.capitalize()]
        )
        demod_type_layout.addWidget(demod_type_label)
        demod_type_layout.addWidget(self.demod_type_combo)
        demodulation_options_frame.inner_layout.addLayout(demod_type_layout)

        return layout

    def build_noise_reduction_section(self):
        layout = QVBoxLayout()

        noise_reduction_options_frame = CollapsableSection(
            self, "Noise Reduction Options", default_collapsed=True
        )
        layout.addLayout(noise_reduction_options_frame)

        noise_reduction_options_layout = QHBoxLayout()

        # Volume dial and numeric textbox
        self.spectral_nr_amount_dial_control = DialControl(
            self, "Spectral NR", QtGui.QDoubleValidator(), 100, 0, 1
        )
        self.spectral_nr_amount_dial_control.dial.setToolTip('Uses "0" in Preview Mode')
        self.spectral_nr_amount_dial_control.textbox.setToolTip(
            'Uses "0" in Preview Mode'
        )

        noise_reduction_checkboxes_layout = QVBoxLayout()
        # Head Switching Interpolation checkbox
        self.head_switching_interpolation_checkbox = QCheckBox(
            "Head Switching Interpolation"
        )
        noise_reduction_checkboxes_layout.addWidget(
            self.head_switching_interpolation_checkbox
        )
        # Muting checkbox
        self.muting_checkbox = QCheckBox("Muting")
        noise_reduction_checkboxes_layout.addWidget(self.muting_checkbox)

        noise_reduction_options_layout.addWidget(
            self.spectral_nr_amount_dial_control, 1
        )
        noise_reduction_options_layout.addLayout(noise_reduction_checkboxes_layout, 1)
        noise_reduction_options_frame.inner_layout.addLayout(
            noise_reduction_options_layout
        )

        return layout

    def build_audio_processing_options_section(self):
        layout = QVBoxLayout()

        advanced_format_options_frame = CollapsableSection(self, "Audio Options")
        layout.addLayout(advanced_format_options_frame)

        # gain section
        gain_section_layout = QHBoxLayout()
        advanced_format_options_frame.inner_layout.addLayout(gain_section_layout)

        # Volume dial and numeric textbox
        self.volume_dial_control = DialControl(
            self, "Output Gain", QtGui.QDoubleValidator(), 100, 0, 2
        )
        gain_section_layout.addWidget(self.volume_dial_control, 1)

        # Normalize Checkbox
        normalize_layout = QHBoxLayout()
        self.normalize_checkbox = QCheckBox("Normalize")
        normalize_layout.addWidget(self.normalize_checkbox)
        gain_section_layout.addLayout(normalize_layout, 1)

        # Audio mode (mono L/mono R/stereo/stereo mpx)
        audio_mode_layout = QHBoxLayout()
        audio_mode_label = QLabel("Output Channel Mode")
        self.audio_mode_combo = QComboBox(self)
        self.audio_mode_combo.addItems(["Stereo", "L", "R", "Stereo MPX", "Sum"])
        audio_mode_layout.addWidget(audio_mode_label)
        audio_mode_layout.addWidget(self.audio_mode_combo)
        advanced_format_options_frame.inner_layout.addLayout(audio_mode_layout)

        # Sample rate options dropdown
        samplerate_layout = QHBoxLayout()
        sample_rate_label = QLabel("Output Sample Rate (Hz)")
        self.sample_rate_combo = QComboBox(self)
        self.sample_rate_combo.addItems(["44100", "48000", "96000", "192000"])
        self.sample_rate_combo.setToolTip('Uses "44100" in Preview Mode')
        samplerate_layout.addWidget(sample_rate_label)
        samplerate_layout.addWidget(self.sample_rate_combo)
        advanced_format_options_frame.inner_layout.addLayout(samplerate_layout)

        # Resampler quality
        resampler_quality_layout = QHBoxLayout()
        resampler_quality_label = QLabel("Output Resampler Quality")
        self.resampler_quality_combo = QComboBox(self)
        self.resampler_quality_combo.addItems(["High", "Medium", "Low"])
        self.resampler_quality_combo.setToolTip('Uses "Low" in Preview Mode')
        resampler_quality_layout.addWidget(resampler_quality_label)
        resampler_quality_layout.addWidget(self.resampler_quality_combo)
        advanced_format_options_frame.inner_layout.addLayout(resampler_quality_layout)

        return layout

    def build_expander_deemphasis_section(self):
        layout = QVBoxLayout()

        # Enable Expander/Deemphasis checkbox
        expander_controls_frame = CollapsableSection(
            self, "Expander Controls", default_collapsed=True
        )
        layout.addLayout(expander_controls_frame)

        self.enable_expander_checkbox = QCheckBox("Enabled")
        expander_controls_frame.inner_layout.addWidget(self.enable_expander_checkbox)
        expander_controls_layout = QHBoxLayout()
        self.expander_gain_dial_control = DialControl(
            self, "Gain (db)", QtGui.QDoubleValidator(), 1, 0, 30
        )
        expander_controls_layout.addWidget(self.expander_gain_dial_control)
        self.expander_ratio_dial_control = DialControl(
            self, "Ratio", QtGui.QDoubleValidator(), 100, 1, 10
        )
        expander_controls_layout.addWidget(self.expander_ratio_dial_control)
        self.expander_attack_tau_dial_control = DialControl(
            self, "Attack (𝜏)", QtGui.QDoubleValidator(), 10e3, 10e-4, 10e-3
        )
        expander_controls_layout.addWidget(self.expander_attack_tau_dial_control)
        self.expander_release_tau_dial_control = DialControl(
            self, "Release (𝜏)", QtGui.QDoubleValidator(), 10e2, 10e-3, 10e-2
        )
        expander_controls_layout.addWidget(self.expander_release_tau_dial_control)
        expander_controls_frame.inner_layout.addLayout(expander_controls_layout)

        expander_sideband_frame = CollapsableSection(
            self,
            "Expander Sideband Input (High-Pass Shelf Filter)",
            default_collapsed=True,
        )
        layout.addLayout(expander_sideband_frame)
        weighting_layout = QHBoxLayout()
        self.expander_weighting_low_tau_dial_control = DialControl(
            self,
            "Low Shelf (𝜏)",
            QtGui.QDoubleValidator(),
            10e5,
            DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2,
            10e-4,
        )
        weighting_layout.addWidget(self.expander_weighting_low_tau_dial_control)
        self.expander_weighting_high_tau_dial_control = DialControl(
            self,
            "High Shelf (𝜏)",
            QtGui.QDoubleValidator(),
            10e5,
            10e-7,
            DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1,
        )
        weighting_layout.addWidget(self.expander_weighting_high_tau_dial_control)
        self.expander_weighting_db_per_octave_dial_control = DialControl(
            self, "Slope (db/oct)", QtGui.QDoubleValidator(), 10, 0, 12
        )
        weighting_layout.addWidget(self.expander_weighting_db_per_octave_dial_control)
        self.expander_weighting_bandwidth_dial_control = DialControl(
            self, "Bandwidth", QtGui.QDoubleValidator(), 50, 0, 12
        )
        weighting_layout.addWidget(self.expander_weighting_bandwidth_dial_control)
        expander_sideband_frame.inner_layout.addLayout(weighting_layout)

        show_plot_btn_weighting = QPushButton("Plot")
        show_plot_btn_weighting.clicked.connect(self.show_plot)
        weighting_layout.addWidget(show_plot_btn_weighting)

        deemphasis_frame = CollapsableSection(
            self, "Deemphasis (Low-Pass Shelf Filter)", default_collapsed=True
        )
        layout.addLayout(deemphasis_frame)
        deemphasis_layout = QHBoxLayout()

        self.enable_deemphasis_checkbox = QCheckBox("Enabled")
        deemphasis_frame.inner_layout.addWidget(self.enable_deemphasis_checkbox)
        self.deemphasis_low_tau_dial_control = DialControl(
            self,
            "Low Shelf (𝜏)",
            QtGui.QDoubleValidator(),
            10e5,
            DEFAULT_VHS_DEEMPHASIS_TAU_2,
            10e-4,
        )
        deemphasis_layout.addWidget(self.deemphasis_low_tau_dial_control)
        self.deemphasis_high_tau_dial_control = DialControl(
            self,
            "High Shelf (𝜏)",
            QtGui.QDoubleValidator(),
            10e5,
            10e-7,
            DEFAULT_VHS_DEEMPHASIS_TAU_1,
        )
        deemphasis_layout.addWidget(self.deemphasis_high_tau_dial_control)
        self.deemphasis_db_per_octave_dial_control = DialControl(
            self, "Slope (db/oct)", QtGui.QDoubleValidator(), 10, 0, 12
        )
        deemphasis_layout.addWidget(self.deemphasis_db_per_octave_dial_control)
        self.deemphasis_bandwidth_dial_control = DialControl(
            self, "Bandwidth", QtGui.QDoubleValidator(), 50, 0, 12
        )
        deemphasis_layout.addWidget(self.deemphasis_bandwidth_dial_control)

        show_plot_btn_deemphasis = QPushButton("Plot")
        show_plot_btn_deemphasis.clicked.connect(self.show_plot)
        deemphasis_layout.addWidget(show_plot_btn_deemphasis)

        deemphasis_frame.inner_layout.addLayout(deemphasis_layout)

        return layout
    
    def schedule_plot_update(self):
        self._plot_update_timer.start(50)
    
    def build_plot_window(self):
        # Sideband / Deemphasis plot window
        self.weighting_deemphasis_plot = PlotWindow("Weighting / Deemphasis", self.getValues)
        self._plot_update_timer = QtCore.QTimer()
        self._plot_update_timer.setSingleShot(True)
        self._plot_update_timer.timeout.connect(self.weighting_deemphasis_plot.update_plot)

        self.expander_weighting_low_tau_dial_control.valueChanged.connect(self.schedule_plot_update)
        self.expander_weighting_high_tau_dial_control.valueChanged.connect(self.schedule_plot_update)
        self.expander_weighting_db_per_octave_dial_control.valueChanged.connect(self.schedule_plot_update)
        self.expander_weighting_bandwidth_dial_control.valueChanged.connect(self.schedule_plot_update)

        self.deemphasis_low_tau_dial_control.valueChanged.connect(self.schedule_plot_update)
        self.deemphasis_high_tau_dial_control.valueChanged.connect(self.schedule_plot_update)
        self.deemphasis_db_per_octave_dial_control.valueChanged.connect(self.schedule_plot_update)
        self.deemphasis_bandwidth_dial_control.valueChanged.connect(self.schedule_plot_update)

        self.audio_mode_combo.currentIndexChanged.connect(self.schedule_plot_update)
    
    def show_plot(self):
        geo = self.geometry()
        self.weighting_deemphasis_plot.move(geo.x() + geo.width() + 20, geo.y())
        self.weighting_deemphasis_plot.update_plot()
        self.weighting_deemphasis_plot.show()

    @property
    def transport_state(self):
        return self._transport_state if self.isVisible() else 0

    @transport_state.setter
    def transport_state(self, value):
        if value == STOP_STATE:
            self.on_stop_clicked()
        elif value == PLAY_STATE:
            self.on_play_clicked()
        elif value == PAUSE_STATE:
            self.on_pause_clicked()
        elif value == PREVIEW_STATE:
            self.on_preview_clicked()
        else:
            raise ValueError("Invalid transport state value")
        self._transport_state = value

    def setValues(self, values: MainUIParameters):
        self.volume_dial_control.setValue(values.volume)
        self.expander_gain_dial_control.setValue(values.expander_gain)
        self.expander_ratio_dial_control.setValue(values.expander_ratio)
        self.expander_attack_tau_dial_control.setValue(values.expander_attack_tau)
        self.expander_release_tau_dial_control.setValue(values.expander_release_tau)
        self.expander_weighting_low_tau_dial_control.setValue(
            values.expander_weighting_low_tau
        )
        self.expander_weighting_high_tau_dial_control.setValue(
            values.expander_weighting_high_tau
        )
        self.expander_weighting_db_per_octave_dial_control.setValue(
            values.expander_weighting_db_per_octave
        )
        self.expander_weighting_bandwidth_dial_control.setValue(
            values.expander_weighting_bandwidth
        )
        self.deemphasis_low_tau_dial_control.setValue(values.deemphasis_low_tau)
        self.deemphasis_high_tau_dial_control.setValue(values.deemphasis_high_tau)
        self.deemphasis_db_per_octave_dial_control.setValue(
            values.deemphasis_db_per_octave
        )
        self.deemphasis_bandwidth_dial_control.setValue(
            values.deemphasis_bandwidth
        )
        self.spectral_nr_amount_dial_control.setValue(values.spectral_nr_amount)
        self.normalize_checkbox.setChecked(values.normalize)
        self.muting_checkbox.setChecked(values.muting)
        self.enable_expander_checkbox.setChecked(values.enable_expander)
        self.enable_deemphasis_checkbox.setChecked(values.enable_deemphasis)
        self.head_switching_interpolation_checkbox.setChecked(
            values.head_switching_interpolation
        )
        self.automatic_fine_tuning_checkbox.setChecked(values.automatic_fine_tuning)
        self.bias_guess_checkbox.setChecked(values.bias_guess)
        self.sample_rate_combo.setCurrentText(str(values.audio_sample_rate))
        self.sample_rate_combo.setCurrentIndex(
            self.sample_rate_combo.findText(str(values.audio_sample_rate))
        )
        self.standard_combo.setCurrentText(values.standard)
        self.standard_combo.setCurrentIndex(
            self.standard_combo.findText(values.standard)
        )
        self.format_combo.setCurrentText(values.format)
        self.format_combo.setCurrentIndex(self.format_combo.findText(values.format))
        self.audio_mode_combo.setCurrentText(values.audio_mode)
        self.audio_mode_combo.setCurrentIndex(
            self.audio_mode_combo.findText(values.audio_mode)
        )
        self.resampler_quality_combo.setCurrentText(values.resampler_quality.title())
        self.resampler_quality_combo.setCurrentIndex(
            self.resampler_quality_combo.findText(values.resampler_quality.title())
        )

        self.demod_type_combo.setCurrentText(values.demod_type)
        self.demod_type_combo.setCurrentIndex(
            self.demod_type_combo.findText(values.demod_type)
        )

        self.input_sample_rate = values.input_sample_rate / 1e6
        found_rate = False
        for i, rate in enumerate(self._input_combo_rates):
            if abs((rate * 1e6) - values.input_sample_rate) < 5000:
                self.input_samplerate_combo.setCurrentIndex(i)
                found_rate = True
                break
        if not found_rate:
            new_other_text = f"Other ({(values.input_sample_rate / 1e6):g})"
            self.input_samplerate_combo.setPlaceholderText(new_other_text)

        self.update_afe_values(
            values.format,
            values.standard,
            values.afe_vco_deviation,
            values.afe_left_carrier,
            values.afe_right_carrier,
        )

        self.update_deemphasis_expander_values(values.format)

        self.input_file = values.input_file
        self.output_file = values.output_file

    def getValues(self) -> MainUIParameters:
        values = MainUIParameters()
        values.volume = self.volume_dial_control.value()
        values.expander_gain = self.expander_gain_dial_control.value()
        values.expander_ratio = self.expander_ratio_dial_control.value()
        values.expander_attack_tau = self.expander_attack_tau_dial_control.value()
        values.expander_release_tau = self.expander_release_tau_dial_control.value()
        values.expander_weighting_low_tau = (
            self.expander_weighting_low_tau_dial_control.value()
        )
        values.expander_weighting_high_tau = (
            self.expander_weighting_high_tau_dial_control.value()
        )
        values.expander_weighting_db_per_octave = (
            self.expander_weighting_db_per_octave_dial_control.value()
        )
        values.expander_weighting_bandwidth = (
            self.expander_weighting_bandwidth_dial_control.value()
        )
        values.deemphasis_low_tau = self.deemphasis_low_tau_dial_control.value()
        values.deemphasis_high_tau = self.deemphasis_high_tau_dial_control.value()
        values.deemphasis_db_per_octave = (
            self.deemphasis_db_per_octave_dial_control.value()
        )
        values.deemphasis_bandwidth = (
            self.deemphasis_bandwidth_dial_control.value()
        )
        values.afe_vco_deviation = self.afe_vco_deviation_spinbox.value()
        values.afe_left_carrier = self.afe_left_carrier_spinbox.value()
        values.afe_right_carrier = self.afe_right_carrier_spinbox.value()
        values.spectral_nr_amount = float(
            self.spectral_nr_amount_dial_control.textbox.text()
        )
        values.normalize = self.normalize_checkbox.isChecked()
        values.muting = self.muting_checkbox.isChecked()
        values.enable_expander = self.enable_expander_checkbox.isChecked()
        values.enable_deemphasis = self.enable_deemphasis_checkbox.isChecked()
        values.head_switching_interpolation = (
            self.head_switching_interpolation_checkbox.isChecked()
        )
        values.automatic_fine_tuning = self.automatic_fine_tuning_checkbox.isChecked()
        values.bias_guess = self.bias_guess_checkbox.isChecked()
        values.audio_sample_rate = int(self.sample_rate_combo.currentText())
        values.standard = self.standard_combo.currentText()
        values.format = self.format_combo.currentText()
        values.audio_mode = self.audio_mode_combo.currentText()
        values.resampler_quality = self.resampler_quality_combo.currentText().lower()
        values.demod_type = self.demod_type_combo.currentText()
        values.input_sample_rate = self.input_sample_rate
        values.input_file = self.input_file
        values.output_file = self.output_file
        return values

    def update_afe_values(
        self,
        format,
        standard,
        afe_vco_deviation=0,
        afe_left_carrier=0,
        afe_right_carrier=0,
    ):
        standard, _ = HiFiDecode.get_standard(
            "vhs" if format == "VHS" else "8mm",
            "p" if standard == "PAL" else "n",
            afe_vco_deviation,
            afe_left_carrier,
            afe_right_carrier,
        )
        self.afe_vco_deviation_spinbox.setValue(int(standard.VCODeviation))
        self.afe_left_carrier_spinbox.setValue(int(standard.LCarrierRef))
        self.afe_right_carrier_spinbox.setValue(int(standard.RCarrierRef))

    def update_deemphasis_expander_values(self, format):
        if format == "VHS":
            self.deemphasis_low_tau_dial_control.setValue(DEFAULT_VHS_DEEMPHASIS_TAU_1)
            self.deemphasis_high_tau_dial_control.setValue(DEFAULT_VHS_DEEMPHASIS_TAU_2)
            self.deemphasis_db_per_octave_dial_control.setValue(DEFAULT_VHS_DEEMPHASIS_DB_PER_OCTAVE)
            self.deemphasis_bandwidth_dial_control.setValue(DEFAULT_VHS_DEEMPHASIS_BANDWIDTH)
            self.expander_weighting_low_tau_dial_control.setValue(DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1)
            self.expander_weighting_high_tau_dial_control.setValue(DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2)
            self.expander_weighting_db_per_octave_dial_control.setValue(DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE)
            self.expander_weighting_bandwidth_dial_control.setValue(DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH)
        else:
            self.deemphasis_low_tau_dial_control.setValue(DEFAULT_8MM_DEEMPHASIS_TAU_1)
            self.deemphasis_high_tau_dial_control.setValue(DEFAULT_8MM_DEEMPHASIS_TAU_2)
            self.deemphasis_db_per_octave_dial_control.setValue(DEFAULT_8MM_DEEMPHASIS_DB_PER_OCTAVE)
            self.deemphasis_bandwidth_dial_control.setValue(DEFAULT_8MM_DEEMPHASIS_BANDWIDTH)
            self.expander_weighting_low_tau_dial_control.setValue(DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_1)
            self.expander_weighting_high_tau_dial_control.setValue(DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_2)
            self.expander_weighting_db_per_octave_dial_control.setValue(DEFAULT_8MM_EXPANDER_WEIGHTING_DB_PER_OCTAVE)
            self.expander_weighting_bandwidth_dial_control.setValue(DEFAULT_8MM_EXPANDER_WEIGHTING_BANDWIDTH)

    def on_standard_change(self):
        self.update_afe_values(
            format=self.format_combo.currentText(),
            standard=self.standard_combo.currentText(),
        )

    def on_format_change(self):
        self.update_afe_values(
            format=self.format_combo.currentText(),
            standard=self.standard_combo.currentText(),
        )
        self.update_deemphasis_expander_values(self.format_combo.currentText())

    def change_button_color(self, button, color):
        button.setStyleSheet(
            """
            QPushButton {
                background-color: %s;
                color: #000;
            }
        """
            % color
        )

    def default_button_color(self, button):
        button.setStyleSheet(
            """
            QPushButton {
                background-color: #555;
                color: #eee;
            }
        """
        )

    def confirm_overwrite(self):
        # checks if destination file exists and prompts user to overwrite
        if os.path.exists(self.output_file) and self.transport_state == 0:
            message_box = QMessageBox(
                QMessageBox.Icon.Question,
                "File Exists",
                "Overwrite existing file?",
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                parent=self,
            )
            message_box.setIcon(QMessageBox.Icon.Warning)
            message_box.setDefaultButton(QMessageBox.StandardButton.No)
            # dark mode
            message_box.setStyleSheet(
                """
                QMessageBox {
                    background-color: #333;
                    color: #eee;
                }
                QPushButton {
                    background-color: #555;
                    color: #eee;
                }
            """
            )
            message_box.exec()
            overwrite = message_box.standardButton(message_box.clickedButton())

            if overwrite == QMessageBox.StandardButton.No:
                print("Overwrite cancelled.")
                return True

        return False

    def on_play_clicked(self):
        print("▶ Play command issued.")
        if self.confirm_overwrite():
            return

        self._transport_state = PLAY_STATE
        self.change_button_color(self.play_button, "#0f0")
        self.default_button_color(self.preview_button)
        self.default_button_color(self.pause_button)
        self.default_button_color(self.stop_button)
        self.setWindowIcon(QIcon.fromTheme("document-save"))

    def on_preview_clicked(self):
        print("▶ Preview command issued.")
        if self.confirm_overwrite():
            return

        self._transport_state = PREVIEW_STATE
        self.change_button_color(self.preview_button, "#0f0")
        self.default_button_color(self.play_button)
        self.default_button_color(self.pause_button)
        self.default_button_color(self.stop_button)
        self.setWindowIcon(QIcon.fromTheme("document-save"))

    def on_pause_clicked(self):
        self.change_button_color(self.pause_button, "#eee")
        self.default_button_color(self.preview_button)
        self.default_button_color(self.play_button)
        self.default_button_color(self.stop_button)
        self.setWindowIcon(QIcon.fromTheme("document-open"))
        print("|| Pause command issued.")
        self._transport_state = PAUSE_STATE

    def on_stop_clicked(self):
        self.change_button_color(self.stop_button, "#eee")
        self.default_button_color(self.preview_button)
        self.default_button_color(self.play_button)
        self.default_button_color(self.pause_button)
        print("■ Stop command issued.")
        self._transport_state = STOP_STATE

    def on_input_samplerate_changed(self):
        print("Input sample rate changed.")
        if "Other" in self.input_samplerate_combo.currentText():
            input_dialog = InputDialog(
                title="Input Sample Rate",
                label="MHz",
                value=self.input_sample_rate,
                validator=QtGui.QDoubleValidator(),
            )
            value: float = input_dialog.get_input_value()
            if value is not None:
                new_other_text = f"Other ({float(value):g})"
                self.input_samplerate_combo.setPlaceholderText(new_other_text)
                self.input_samplerate_combo.setCurrentIndex(-1)
                self.input_sample_rate = value
        else:
            self.input_sample_rate = self._input_combo_rates[
                self.input_samplerate_combo.currentIndex()
            ]

    def generic_message_box(
        self,
        title: str,
        message: str,
        type: QMessageBox.Icon = QMessageBox.Icon.Information,
    ):
        message_box = QMessageBox(type, title, message, parent=self)
        message_box.setIcon(type)
        message_box.setDefaultButton(QMessageBox.StandardButton.Ok)
        # dark mode
        message_box.setStyleSheet(
            """
            QMessageBox {
                background-color: #333;
                color: #eee;
            }
            QPushButton {
                background-color: #555;
                color: #eee;
            }
        """
        )
        message_box.exec()

    def on_decode_finished(self, decoded_filename: str = "input stream"):
        self.setWindowIcon(QIcon.fromTheme("document-open"))
        # alerts user that decode is finished
        self.generic_message_box(
            "Decode Finished", f"Decode of {decoded_filename} finished."
        )


class FileOutputDialogUI(HifiUi):
    def __init__(
        self,
        params: MainUIParameters,
        title: str = "HiFi Decode",
        main_layout_callback=None,
    ):
        super(FileOutputDialogUI, self).__init__(params, title, self._layout_callback)

    def _layout_callback(self, main_layout):
        # Add file output widgets
        self.file_output_label = QLabel("Output file")
        self.file_output_textbox = QLineEdit(self)
        self.file_output_button = QPushButton("Browse", self)
        self.file_output_button.clicked.connect(self.on_file_output_button_clicked)
        self.file_output_layout = QHBoxLayout()
        self.file_output_layout.addWidget(self.file_output_label)
        self.file_output_layout.addWidget(self.file_output_textbox)
        self.file_output_layout.addWidget(self.file_output_button)
        self.main_layout.addLayout(self.file_output_layout)
        # sets browse button height to match text box height
        self.file_output_button.setFixedHeight(
            self.file_output_textbox.sizeHint().height()
        )
        self.file_output_textbox.setFixedHeight(
            self.file_output_textbox.sizeHint().height()
        )

    def on_file_output_button_clicked(self):
        qdialog = QFileDialog(self)
        qdialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if os.path.isdir(os.path.dirname(self.file_output_textbox.text())):
            qdialog.setDirectory(os.path.dirname(self.file_output_textbox.text()))

        file_name, _ = qdialog.getOpenFileName(
            self, "Open File", "", "All Files (*);;FLAC (*.flac)"
        )
        if file_name:
            self.file_output_textbox.setText(file_name)
        print("Output file browse button clicked.")

    def getValues(self) -> MainUIParameters:
        values = super(FileOutputDialogUI, self).getValues()
        values.output_file = self.file_output_textbox.text()
        return values

    def setValues(self, values: MainUIParameters):
        super(FileOutputDialogUI, self).setValues(values)
        self.file_output_textbox.setText(values.output_file)

    def on_decode_finished(self, decoded_filename: str = "input stream"):
        decoded_filename = os.path.basename(self.file_output_textbox.text())
        super(FileOutputDialogUI, self).on_decode_finished(decoded_filename)


class DialControl(QWidget):
    valueChanged = QtCore.pyqtSignal(float)

    def __init__(
        self,
        main_window,
        label_text,
        validator,
        scale=1,
        min_value=0,
        max_value=1,
        scroll_step_size=1,
    ):
        super(QWidget, self).__init__()
        layout = QHBoxLayout(self)

        # Volume dial and numeric textbox
        label_and_textbox = QVBoxLayout()

        label = QLabel(label_text)
        self.scale = scale

        textbox_character_width = max(int(math.log10(self.scale)) + 1, 3)
        self.textbox = QLineEdit(main_window)
        self.textbox.setValidator(validator)
        metrics = QtGui.QFontMetrics(self.textbox.font())
        width = metrics.horizontalAdvance("M") * textbox_character_width
        self.textbox.setFixedWidth(width)
        self.textbox.show()

        self.dial = QDial(main_window)
        self.dial.setRange(int(min_value * scale), int(max_value * scale))
        self.dial.setPageStep(1)
        self.dial.setSingleStep(scroll_step_size)

        label_and_textbox.addWidget(label)
        label_and_textbox.addWidget(self.textbox)
        layout.addWidget(self.dial)
        layout.addLayout(label_and_textbox)

        self.dial.valueChanged.connect(self.on_dial_change)
        self.textbox.editingFinished.connect(self.on_textbox_change)

    def setValue(self, value):
        self.dial.setValue(int(value * self.scale))
        self.textbox.setText(f"{value:g}")

    def value(self):
        return float(self.textbox.text())

    def on_dial_change(self, value):
        scaled_value = value / self.scale
        self.textbox.setText(f"{scaled_value:g}")
        self.valueChanged.emit(self.value())

    def on_textbox_change(self):
        text = self.textbox.text()
        try:
            value = float(text)
            self.dial.setValue(int(value * self.scale))
            self.valueChanged.emit(value)
        except ValueError:
            pass


class CollapsableSection(QVBoxLayout):
    def __init__(self, main_window, label_text, default_collapsed=False, bg_color = "#333"):
        super(CollapsableSection, self).__init__()

        self.main_window = main_window
        self.main_window.collapsableSections.append(self)
        self.default_collapsed = default_collapsed

        # Create toggle button
        self.collapsed_arrow = QLabel()
        self.collapsed_arrow.setStyleSheet("border: none;")
        self.collapsed_arrow.setFixedSize(
            self.collapsed_arrow.sizeHint().width(),
            self.collapsed_arrow.sizeHint().width(),
        )
        collapsed_arrow_font = self.collapsed_arrow.font()
        collapsed_arrow_font.setBold(True)
        collapsed_arrow_font.setPointSize(10)
        collapsed_arrow_font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self.collapsed_arrow.setFont(collapsed_arrow_font)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        line.setStyleSheet("color: #666;")
        line.setFixedHeight(2)

        label = QLabel(label_text)
        label.setStyleSheet(
            f"background-color: {bg_color}; padding: 1 0px; font-size: 0.8rem;"
        )
        label_font = label.font()
        label_font.setItalic(True)
        label.setFont(label_font)

        # Wrapper widget to hold label + padding
        label_layout = QHBoxLayout()
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.addWidget(label)
        label_widget = QWidget()
        label_widget.setLayout(label_layout)

        # Add both label and line to the same grid cell
        self.header = QWidget()

        horizontal_spacer = QGridLayout(self.header)
        horizontal_spacer.setContentsMargins(0, 0, 0, 0)
        horizontal_spacer.setSpacing(0)
        horizontal_spacer.addWidget(
            self.collapsed_arrow, 0, 0, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        horizontal_spacer.addWidget(
            label_widget, 0, 1, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        horizontal_spacer.addWidget(
            line, 0, 2, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        self.body = QFrame()
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body.setObjectName("LabeledFrame")
        self.body.setStyleSheet(
            "QFrame#LabeledFrame { border: 1px solid #aaa; border-radius: 15px; }"
        )
        self.addWidget(self.header)
        self.addWidget(self.body)

        self.header.mousePressEvent = self._toggle
        self.inner_layout = QVBoxLayout(self.body)

    def setDefaultCollapseState(self):
        self._setCollapsed(self.default_collapsed)

    def _setCollapsed(self, value):
        self._collapsed = value
        self.body.setVisible(not self._collapsed)
        self.collapsed_arrow.setText(
            "▶" if self._collapsed else "▼"
        )  # Right arrow if collapsed
        self.update()
        self.main_window.resize_window(axis="v")

    def _toggle(self, _):
        self._setCollapsed(not self._collapsed)


class FileIODialogUI(HifiUi):
    def __init__(
        self,
        params: MainUIParameters,
        title: str = "HiFi Decode",
        main_layout_callback=None,
    ):
        super(FileIODialogUI, self).__init__(params, title, self._layout_callback)

    def _layout_callback(self, main_layout):
        # Add file input widgets
        self.file_input_label = QLabel("Input file")
        self.file_input_textbox = QLineEdit(self)
        self.file_input_button = QPushButton("Browse", self)
        self.file_input_button.clicked.connect(self.on_file_input_button_clicked)
        self.file_input_layout = QHBoxLayout()
        self.file_input_layout.addWidget(self.file_input_label)
        self.file_input_layout.addWidget(self.file_input_textbox)
        self.file_input_layout.addWidget(self.file_input_button)
        self.main_layout.addLayout(self.file_input_layout)
        # sets browse button height to match text box height
        self.file_input_button.setFixedHeight(
            self.file_input_textbox.sizeHint().height()
        )
        self.file_input_textbox.setFixedHeight(
            self.file_input_textbox.sizeHint().height()
        )

        # Add file output widgets
        self.file_output_label = QLabel("Output file")
        self.file_output_textbox = QLineEdit(self)
        self.file_output_button = QPushButton("Browse", self)
        self.file_output_button.clicked.connect(self.on_file_output_button_clicked)
        self.file_output_layout = QHBoxLayout()
        self.file_output_layout.addWidget(self.file_output_label)
        self.file_output_layout.addWidget(self.file_output_textbox)
        self.file_output_layout.addWidget(self.file_output_button)
        self.main_layout.addLayout(self.file_output_layout)
        # sets browse button height to match text box height
        self.file_output_button.setFixedHeight(
            self.file_output_textbox.sizeHint().height()
        )
        self.file_output_textbox.setFixedHeight(
            self.file_output_textbox.sizeHint().height()
        )
        # sets file input and output text boxes to same width
        max_label_width = max(
            self.file_input_label.sizeHint().width(),
            self.file_output_label.sizeHint().width(),
        )
        self.file_input_label.setMinimumWidth(max_label_width)
        self.file_output_label.setMinimumWidth(max_label_width)

    def on_file_input_button_clicked(self):
        qdialog = QFileDialog(self)
        qdialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if os.path.isdir(os.path.dirname(self.file_input_textbox.text())):
            qdialog.setDirectory(os.path.dirname(self.file_input_textbox.text()))
        file_name, _ = qdialog.getOpenFileName(
            self, "Open File", "", "All Files (*);;FLAC (*.flac)"
        )

        if os.path.exists(file_name):
            self.file_input_textbox.setText(file_name)
        print("Input browse button clicked.")

    def on_file_output_button_clicked(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save File",
            "",
            "All Files (*);;FLAC (*.flac);; WAV (*.wav)",
        )

        if os.path.isdir(os.path.dirname(file_name)):
            self.file_output_textbox.setText(file_name)
        print("Output browse button clicked.")

    def getValues(self) -> MainUIParameters:
        values = super(FileIODialogUI, self).getValues()
        values.input_file = self.file_input_textbox.text()
        values.output_file = self.file_output_textbox.text()
        return values

    def setValues(self, values: MainUIParameters):
        super(FileIODialogUI, self).setValues(values)
        self.file_input_textbox.setText(values.input_file)
        self.file_output_textbox.setText(values.output_file)

    def on_decode_finished(self, decoded_filename: str = "input stream"):
        decoded_filename = os.path.basename(self.file_input_textbox.text())
        super(FileIODialogUI, self).on_decode_finished(decoded_filename)

class PlotWindow(QWidget):
    def __init__(self, title, getValues):
        super(QWidget, self).__init__()

        self.setWindowTitle(title)

        # Matplotlib figure
        fig, self.ax = plt.subplots(figsize=(12, 8))
        self.canvas = FigureCanvas(fig)

        self.toolbar = NavigationToolbar(self.canvas, self)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.toolbar)
        self.setLayout(layout)
        self.getValues = getValues

    def plot_response(self, label, color, freq, mag_db, t1, t2):
        # Compute the frequency response
        # Convert taus to frequencies
        t1_f = round(tau_as_freq(t1))
        t2_f = round(tau_as_freq(t2))
        center_f = round(np.sqrt(tau_as_freq(t1) * tau_as_freq(t2)))
    
        # Plot the full frequency response
        self.ax.semilogx(freq, mag_db, label=label, color=color)
    
        # Helper: get magnitude at closest frequency index
        def point_at(freq_target):
            idx = np.argmin(np.abs(freq - freq_target))
            return freq[idx], mag_db[idx]
    
        # Compute (x, y) for points
        t1_x, t1_y = point_at(t1_f)
        t2_x, t2_y = point_at(t2_f)
        cf_x, cf_y = point_at(center_f)
    
        # Plot dot markers instead of axvlines
        self.ax.plot(t1_x, t1_y, marker='|', color=color, markersize=15, 
                 label=f"({t1_f} Hz)")
        self.ax.plot(cf_x,  cf_y, marker='o', color=color, markersize=5,
                 label=f"({center_f} Hz)")
        self.ax.plot(t2_x, t2_y, marker='|', color=color, markersize=15,
                 label=f"({t2_f} Hz)")

    def update_plot(self):
        self.ax.clear()
        ui_values = self.getValues()

        deemphasis = Deemphasis(
            ui_values.audio_sample_rate,
            ui_values.deemphasis_low_tau,
            ui_values.deemphasis_high_tau,
            ui_values.deemphasis_db_per_octave,
            ui_values.deemphasis_bandwidth,
        )
        deemphasis_freqs, deemphasis_mag_db = deemphasis.get_response()

        expander = Expander(
            ui_values.audio_sample_rate,
            weighting_low_tau = ui_values.expander_weighting_low_tau,
            weighting_high_tau = ui_values.expander_weighting_high_tau,
            weighting_db_per_octave = ui_values.expander_weighting_db_per_octave,
            weighting_bandwidth = ui_values.expander_weighting_bandwidth
        )
        expander_freqs, expander_mag_db = expander.get_response()

        self.plot_response(
            "Sideband",
            "green",
            expander_freqs,
            expander_mag_db,
            ui_values.expander_weighting_low_tau,
            ui_values.expander_weighting_high_tau,
        )
        self.plot_response(
            "Deemphasis",
            "blue",
            deemphasis_freqs,
            deemphasis_mag_db,
            ui_values.deemphasis_low_tau,
            ui_values.deemphasis_high_tau,
        )

        self.ax.grid(True, which="both")
        self.ax.set_xlabel("Frequency [Hz]")
        self.ax.set_ylabel("Amplitude [dB]")
        self.ax.set_xlim([1, ui_values.audio_sample_rate/2])
        self.ax.set_ylim([-20, 3])
        
        self.ax.legend()
        self.canvas.draw()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    params = MainUIParameters()
    window = FileIODialogUI(params)
    window.show()
    sys.exit(app.exec())
