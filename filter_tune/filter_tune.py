#!/usr/bin/env python3

# released under GNU GPL v3 or later

import math
import numpy as np
import numpy.fft as npfft
import scipy.signal as signal
import os
import sys
import logging

from PyQt5.QtCore import Qt, QByteArray, QCryptographicHash, QMetaType, QSize
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyleFactory,
    QSizePolicy,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)
from PyQt5.QtGui import (
    QBrush,
    QGuiApplication,
    QImage,
    QKeySequence,
    QKeyEvent,
    QPalette,
    QPixmap,
)

from vhsdecode.utils import filtfft
from vhsdecode.addons.FMdeemph import gen_high_shelf
from vhsdecode.formats import get_format_params
from vhsdecode import compute_video_filters
from vhsdecode.main import supported_tape_formats

BLOCK_LEN = 32768
SAMPLE_RATE = (((1 / 64) * 283.75) + (25 / 1000000)) * 4e6
# fs = 40000000
# 2560
FRAME_WIDTH = 1135
OUT_SCALE_DIVIDEND = np.double(0xC800 - 0x0400)


def multicall(l=[]):
    for c in l:
        c()


### copied from vhs-decode


def _hz_to_output(inp, sys_params, phase=0):
    reduced = (
        inp - sys_params["ire0"] - sys_params["track_ire0_offset"][phase]
    ) / sys_params["hz_ire"]
    reduced -= sys_params["vsync_ire"]
    out_scale = OUT_SCALE_DIVIDEND / (100 - sys_params["vsync_ire"])
    return np.uint16(
        np.clip((reduced * out_scale) + sys_params["outputZero"], 0, 65535) + 0.5
    )


# def genDeemphFilter(mid_point, dBgain, Q, fs):
#    da, db = gen_high_shelf(mid_point, dBgain, Q, fs)
#    return filtfft((db, da), BLOCK_LEN, whole=False)


def genHighpass(freq, fs_hz):
    nyq = fs_hz / 2.0
    return filtfft(
        signal.butter(1, [freq / nyq], btype="highpass"), BLOCK_LEN, whole=False
    )


def genLowpass(freq, fs_hz):
    nyq = fs_hz / 2.0
    return filtfft(
        signal.butter(1, [freq / nyq], btype="lowpass"), BLOCK_LEN, whole=False
    )


#####


def readVHSFrame(f, nr, w, h):
    out = None
    offset = (nr * (2 * w * h) - 1024) * 4
    # offset=0
    try:
        # 1638400
        out = np.fromfile(f, dtype=np.single, count=1638400, offset=offset)
    except:
        print("Failed to load VHS frame from tbc file")
    return out


def readRefFrame(f, nr, w, h, offset=0):
    outa = None
    outb = None
    try:
        out_video = np.fromfile(
            f,
            dtype=np.uint16,
            count=(2 * w * h),
            offset=(nr - offset) * (2 * w * h) * 2,
        )
        outa = out_video[0 : (w * h)]
        outb = out_video[(w * h) : (2 * w * h)]
    except:
        print("Failed to load reference frame from tbc file")
    return outa, outb


class FormatParams:
    def __init__(self, system, tape_format, fs, logger):
        self.change_format(system, tape_format, fs, logger)

    def change_format(self, system, tape_format, fs, logger):
        self.fs = fs
        self.sys_params, self.rf_params = get_format_params(system, tape_format, logger)
        # TODO: THis default should be set elsewhere
        self.sys_params["track_ire0_offset"] = self.sys_params.get(
            "track_ire0_offset", [0, 0]
        )
        self.rf_params["deemph_q"] = self.rf_params.get("deemph_q", 0.5)
        self.sub_emphasis_params = compute_video_filters.create_sub_emphasis_params(
            self.rf_params,
            self.sys_params,
            self.sys_params["hz_ire"],
            self.sys_params["vsync_ire"],
        )


class VHStune(QDialog):
    refTBCFilename = ""
    proTBCFilename = ""
    title = "VHStune"

    curFrameNr = 1
    totalFrames = 2

    def __init__(self, logger, parent=None):
        super(VHStune, self).__init__(
            parent,
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint,
        )
        self._logger = logger

        self._format_params = FormatParams("PAL", "VHS", SAMPLE_RATE, logger)

        self.originalPalette = QApplication.palette()

        self.makeFilterParams()
        self.createControlsGroupBox()
        self.createFilterGroupBox()
        self.createStyleGroupBox()
        self.createRightArea()

        mainLayout = QGridLayout()
        leftLayout = QVBoxLayout()
        leftLayout.addWidget(self.controlsGroupBox)
        leftLayout.addWidget(self.filterGroupBox)
        leftLayout.addWidget(self.styleGroupBox)
        mainLayout.addLayout(leftLayout, 0, 0)
        mainLayout.addLayout(self.rightLayout, 0, 1)
        mainLayout.setRowStretch(0, 1)
        # mainLayout.setRowStretch(1, 1)
        mainLayout.setColumnStretch(1, 1)
        # mainLayout.setColumnStretch(1, 1)
        self.setLayout(mainLayout)

        self.setWindowTitle(self.title)

        self.initFilters()

    def makeFilterParams(self):
        rf_params = self._format_params.rf_params
        self.filter_params = {
            #          "deemph_enable": { "value": True, "step": None, "desc": "Enable deemphasis", "onchange": [ self.applyFilter, self.drawImage ] },
            "deemph_mid": {
                "value": rf_params["deemph_mid"],
                "step": 5000,
                "min": 10000,
                "max": 4000000,
                "desc": "Deemphasis mid freq ({:.0f} Hz):",
                "onchange": [
                    self.calcDeemphFilter,
                    self.applyDeemphFilter,
                    self.applyNLSVHSFilter,
                    self.drawImage,
                ],
            },
            "deemph_gain": {
                "value": rf_params["deemph_gain"],
                "step": 0.5,
                "min": -30,
                "max": 30,
                "desc": "Deemphasis gain ({:.1f} dB):",
                "onchange": [
                    self.calcDeemphFilter,
                    self.applyDeemphFilter,
                    self.applyNLSVHSFilter,
                    self.drawImage,
                ],
            },
            "deemph_q": {
                "value": rf_params["deemph_q"],
                "step": 0.05,
                "min": 0.05,
                "max": 5,
                "desc": "Deemphasis Q ({:.2f}):",
                "onchange": [
                    self.calcDeemphFilter,
                    self.applyDeemphFilter,
                    self.applyNLSVHSFilter,
                    self.drawImage,
                ],
            },
            "nonlinear_deemph_enable": {
                "value": False,
                "step": None,
                "desc": "Enable non-linear deemphasis",
                "onchange": [self.drawImage],
            },
            "nonlinear_deemph_showonly": {
                "value": False,
                "step": None,
                "desc": "Show only subtracted non-linear deemphasis part",
                "onchange": [self.drawImage],
            },
            "nonlinear_highpass_freq": {
                "value": rf_params["nonlinear_highpass_freq"],
                "step": 5000,
                "min": 10000,
                "max": 4000000,
                "desc": "Non-linear high-pass freq ({} Hz):",
                "onchange": [
                    self.calcNLHPFilter,
                    self.applyNLDeemphFilterA,
                    self.applyNLDeemphFilterB,
                    self.drawImage,
                ],
            },
            "nonlinear_bandpass_upper": {
                "value": rf_params.get("nonlinear_bandpass_upper", None),
                "step": 5000,
                "min": 300000,
                "max": 6000000,
                "desc": "Non-linear bandpass upper freq ({} Hz):",
                "onchange": [
                    self.calcNLHPFilter,
                    self.applyNLDeemphFilterA,
                    self.applyNLDeemphFilterB,
                    self.drawImage,
                ],
            },
            "nonlinear_linear_scale": {
                "value": rf_params.get("nonlinear_scaling_1", 1.0),
                "step": 0.05,
                "min": 0.05,
                "max": 2.0,
                "desc": "Non-linear linear scale ({:.2f}):",
                "onchange": [self.applyNLDeemphFilterB, self.drawImage],
            },
            "nonlinear_linear_scale_b": {
                "value": rf_params.get("nonlinear_scaling_2", 1.0),
                "step": 0.01,
                "min": 0.01,
                "max": 2.0,
                "desc": "Non-linear linear scale B ({:.2f}):",
                "onchange": [self.applyNLDeemphFilterB, self.drawImage],
            },
            "nonlinear_exponential_scale": {
                "value": rf_params.get("nonlinear_exp_scaling", 0.25),
                "step": 0.01,
                "min": 0.05,
                "max": 2,
                "desc": "Non-linear exponential scale ({:.2f}):",
                "onchange": [self.applyNLDeemphFilterB, self.drawImage],
            },
            "svhs_deemph_enable": {
                "value": False,
                "step": None,
                "desc": "Enable S-VHS non-linear deemphasis",
                "onchange": [self.drawImage],
            },
            "svhs_crossover_freq": {
                "value": 400000,
                "step": 5000,
                "min": 10000,
                "max": 4000000,
                "desc": "Crossover freq ({} Hz):",
                "onchange": [
                    self.calcNLSVHSFilter,
                    self.applyNLSVHSFilter,
                    self.drawImage,
                ],
            },
            "svhs_lowpass_freq": {
                "value": 7000000,
                "step": 10000,
                "min": 1000000,
                "max": 8000000,
                "desc": "Lowpass freq ({} Hz):",
                "onchange": [
                    self.calcNLSVHSFilter,
                    self.applyNLSVHSFilter,
                    self.drawImage,
                ],
            },
            "svhs_lf_in_level": {
                "value": 1.0,
                "step": 0.01,
                "min": 0.5,
                "max": 2.0,
                "desc": "LF input level ({:.2f}):",
                "onchange": [self.applyNLSVHSFilter, self.drawImage],
            },
            "svhs_hf_in_level": {
                "value": 1.0,
                "step": 0.01,
                "min": 0.5,
                "max": 2.0,
                "desc": "HF input level ({:.2f}):",
                "onchange": [self.applyNLSVHSFilter, self.drawImage],
            },
            "svhs_lf_out_level": {
                "value": 0.815,
                "step": 0.001,
                "min": 0.7,
                "max": 1.0,
                "desc": "LF output level ({:.3f}):",
                "onchange": [self.applyNLSVHSFilter, self.drawImage],
            },
            "svhs_hf_out_level": {
                "value": 0.66,
                "step": 0.01,
                "min": 0.25,
                "max": 2.0,
                "desc": "HF output level ({:.2f}):",
                "onchange": [self.applyNLSVHSFilter, self.drawImage],
            },
        }

    def initFilters(self):
        self.calcDeemphFilter()
        self.calcNLHPFilter()
        self.calcNLSVHSFilter()

    def updateFrameNr(self, s):
        if s == 1:
            self.curFrameNr = self.frameSlider.value()
            self.frameSpin.blockSignals(True)
            self.frameSpin.setValue(self.curFrameNr)
            self.frameSpin.blockSignals(False)
        if s == 2:
            self.curFrameNr = self.frameSpin.value()
            self.frameSlider.blockSignals(True)
            self.frameSlider.setValue(self.curFrameNr)
            self.frameSlider.blockSignals(False)
        else:
            if s == 3:
                self.curFrameNr -= 25
            elif s == 4:
                self.curFrameNr -= 1
            elif s == 5:
                self.curFrameNr += 1
            elif s == 6:
                self.curFrameNr += 25
            if self.curFrameNr <= 0:
                self.curFrameNr = 1
            elif self.curFrameNr >= self.totalFrames - 1:
                self.curFrameNr = self.totalFrames - 2
            self.frameSpin.blockSignals(True)
            self.frameSpin.setValue(self.curFrameNr)
            self.frameSpin.blockSignals(False)
            self.frameSlider.blockSignals(True)
            self.frameSlider.setValue(self.curFrameNr)
            self.frameSlider.blockSignals(False)
        self.updateImage()

    def updateImage(self, f=False, k=None):
        if f is True:
            if self.filter_params[k]["step"] is None:
                self.filter_params[k]["value"] = self.filter_params[k][
                    "ctrl"
                ].isChecked()
            else:
                self.filter_params[k]["value"] = (
                    self.filter_params[k]["step"]
                    * self.filter_params[k]["ctrl"].value()
                )
                self.filter_params[k]["label"].setText(
                    self.filter_params[k]["desc"].format(self.filter_params[k]["value"])
                )
            print(k)
            for p in self.filter_params[k]["onchange"]:
                p()
        else:
            self.loadImage()
            self.applyNLDeemphFilterA()
            self.applyNLDeemphFilterB()
            self.applyDeemphFilter()
            self.applyNLSVHSFilter()
            self.drawImage()

    def openRefTBCFile(self):
        fileName = QFileDialog.getOpenFileName(
            self, "Open reference tbc file", self.refTBCFilename, "tbc files (*.tbc)"
        )
        if fileName is not None and fileName[0] != "":
            self.refTBCFilename = fileName[0]
            self.updateImage()

    def openProTBCFile(self):
        fileName = QFileDialog.getOpenFileName(
            self, "Open to processed tbc file", self.proTBCFilename, "tbc files (*.tbc)"
        )
        if fileName is not None and fileName[0] != "":
            self.proTBCFilename = fileName[0]
            fSize = os.path.getsize(self.proTBCFilename)
            self.totalFrames = math.floor(fSize / (4 * 2 * FRAME_WIDTH * 313))
            self.frameSlider.setRange(1, self.totalFrames - 2)
            self.frameSpin.setRange(1, self.totalFrames - 2)
            self.updateImage()

    def loadImage(self):
        self.refFieldA, self.refFieldB = readRefFrame(
            self.refTBCFilename,
            self.curFrameNr,
            FRAME_WIDTH,
            313,
            self.refOffset.value(),
        )
        self.vhsFrameData = readVHSFrame(
            self.proTBCFilename, self.curFrameNr, FRAME_WIDTH, 313
        )
        pos = 0
        self.fftData = []
        while pos < (len(self.vhsFrameData) - BLOCK_LEN):
            self.fftData.append(npfft.rfft(self.vhsFrameData[pos : pos + BLOCK_LEN]))
            pos += BLOCK_LEN - 2048

    def calcDeemphFilter(self):
        self.deemphFilter = compute_video_filters.gen_video_main_deemp_fft(
            self.filter_params["deemph_gain"]["value"],
            self.filter_params["deemph_mid"]["value"],
            self.filter_params["deemph_q"]["value"],
            self._format_params.fs,
            BLOCK_LEN,
        )

    def calcNLHPFilter(self):
        self.NLHPFilter = compute_video_filters.gen_nonlinear_bandpass(
            None,
            self.filter_params["nonlinear_highpass_freq"]["value"],
            self._format_params.fs / 2.0,
            BLOCK_LEN,
        )

    def calcNLSVHSFilter(self):
        self.NLSVHSLPFilter = genLowpass(
            self.filter_params["svhs_crossover_freq"]["value"], self._format_params.fs
        )
        self.NLSVHSHPFilter = genHighpass(
            self.filter_params["svhs_crossover_freq"]["value"], self._format_params.fs
        )
        self.NLSVHSLPBFilter = genLowpass(
            self.filter_params["svhs_lowpass_freq"]["value"], self._format_params.fs
        )
        # self.NLSVHSACFilter = genHighpass(200000)

    def applyNLSVHSFilter(self):
        self.ProcessedSVHSFrame = []
        deviation = self._format_params.sub_emphasis_params.deviation / 2.0

        for b in self.fftData:
            hf_part = npfft.irfft(
                b * self.deemphFilter * self.NLSVHSHPFilter * self.NLSVHSLPBFilter
            )
            lf_part = npfft.irfft(b * self.deemphFilter * self.NLSVHSLPFilter)
            # dc_part = npfft.irfft(b * self.deemphFilter * self.NLSVHSACFilter)
            hf_amp = (
                abs(signal.hilbert(hf_part))
                / (deviation)
                * self.filter_params["svhs_hf_in_level"]["value"]
            )
            lf_amp = (
                abs(signal.hilbert(lf_part))
                / (deviation)
                * self.filter_params["svhs_lf_in_level"]["value"]
            )
            hf_amp_scaled = 1.0 / (
                0.26007715 * np.exp(-0.4152129 * (np.log(hf_amp) - 1.27878766))
                + 0.55291881
            )
            lf_amp_scaled = 1.0 / (
                0.15124517 * np.exp(-3.41855724 * lf_amp) + 0.81349599
            )
            #  * lf_amp_scaled *
            self.ProcessedSVHSFrame.append(
                hf_part
                * hf_amp_scaled
                * self.filter_params["svhs_hf_out_level"]["value"]
                + lf_part
                * lf_amp_scaled
                * self.filter_params["svhs_lf_out_level"]["value"]
            )

    def applyNLDeemphFilterA(self):
        self.NLDeemphAmplitude = []
        self.NLDeemphPart = []
        for b in self.fftData:
            hf_part = npfft.irfft(b * self.deemphFilter * self.NLHPFilter)
            self.NLDeemphPart.append(hf_part)
            deviation = self._format_params.sub_emphasis_params.deviation / 2.0
            self.NLDeemphAmplitude.append(abs(signal.hilbert(hf_part)) / deviation)

    def applyNLDeemphFilterB(self):
        self.NLProcessed = []
        for i in range(len(self.NLDeemphAmplitude)):
            amplitude_scaled = (
                self.NLDeemphAmplitude[i]
                * self.filter_params["nonlinear_linear_scale"]["value"]
            )
            amplitude_scaled = np.power(
                amplitude_scaled,
                self.filter_params["nonlinear_exponential_scale"]["value"],
            )
            amplitude_scaled *= self.filter_params["nonlinear_linear_scale_b"]["value"]
            self.NLProcessed.append(self.NLDeemphPart[i] * (1 - amplitude_scaled))

    def applyDeemphFilter(self):
        self.ProcessedFrame = []
        for b in self.fftData:
            self.ProcessedFrame.append(npfft.irfft(b * self.deemphFilter).real)

    def drawImage(self):
        outImage = None
        for i in range(len(self.ProcessedFrame)):
            if self.filter_params["svhs_deemph_enable"]["value"] is True:
                img = self.ProcessedSVHSFrame[i].copy()
            else:
                img = self.ProcessedFrame[i].copy()
            if self.filter_params["nonlinear_deemph_enable"]["value"] is True:
                if self.filter_params["nonlinear_deemph_showonly"]["value"] is True:
                    img.fill(self._format_params.sys_params["ire0"])
                    img += self.NLProcessed[i]
                else:
                    img -= self.NLProcessed[i]
            if outImage is None:
                outImage = img[1024:31744]
            else:
                outImage = np.append(outImage, img[1024:31744])
        height = 313
        width = FRAME_WIDTH
        field_samples = height * width

        vhsFieldA = _hz_to_output(
            outImage[0:field_samples],
            self._format_params.sys_params,
            0 ^ int(self.swapTrackFieldChkBox.isChecked()),
            # self.systemComboBox.currentText(),
        )
        vhsFieldB = _hz_to_output(
            outImage[field_samples : field_samples * 2],
            self._format_params.sys_params,
            1 ^ int(self.swapTrackFieldChkBox.isChecked()),
        )
        outFieldA = None
        outFieldB = None
        if self.refFieldA is not None and self.refFieldB is not None:
            height *= 2
            outFieldA = np.append(self.refFieldA, vhsFieldA)
            outFieldB = np.append(self.refFieldB, vhsFieldB)
        else:
            outFieldA = vhsFieldA
            outFieldB = vhsFieldB

        if self.showFieldsChkBox.isChecked() is True:
            outFrame = np.append(outFieldA, outFieldB)
        else:
            outFrame = np.empty((height * 2, width), dtype=np.uint16)
            outFrame[::2, :] = outFieldA.reshape(height, width)
            outFrame[1::2, :] = outFieldB.reshape(height, width)
        pixmap = QPixmap(
            QImage(
                outFrame.data,
                FRAME_WIDTH,
                height * 2,
                FRAME_WIDTH * 2,
                QImage.Format_Grayscale16,
            )
        )
        if self.displayWidthSlider.value() != 100:
            pixmap = pixmap.scaled(
                QSize(
                    int(FRAME_WIDTH * (self.displayWidthSlider.value() / 100.0)),
                    height * 2,
                ),
                transformMode=Qt.SmoothTransformation,
            )
        if self.displayHeightSlider.value() != 1:
            pixmap = pixmap.scaled(
                QSize(pixmap.width(), height * 2 * self.displayHeightSlider.value()),
                transformMode=Qt.FastTransformation,
            )
        self.dispLabel.setPixmap(pixmap)

    def createRightArea(self):
        self.rightLayout = QGridLayout()
        # scroll = QScrollArea()
        # scroll.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.dispLabel = QLabel()
        self.dispLabel.setSizePolicy(
            QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding
        )
        # scroll.setWidget(self.dispLabel)
        self.frameSlider = QSlider(Qt.Horizontal, self)

        self.frameSlider.setRange(1, 1)
        self.frameSlider.setValue(1)
        self.frameSpin = QSpinBox()

        self.frameSpin.setRange(1, 1)
        self.frameSpin.setValue(1)
        self.frameSlider.valueChanged.connect(lambda: self.updateFrameNr(1))
        self.frameSpin.valueChanged.connect(lambda: self.updateFrameNr(2))
        frameSpinLabel = QLabel("Frame #:")
        frameSpinLabel.setBuddy(self.frameSpin)
        skipBackBtn = QPushButton("<<")
        skipBackBtn.clicked.connect(lambda: self.updateFrameNr(3))
        stepBackBtn = QPushButton("<")
        stepBackBtn.clicked.connect(lambda: self.updateFrameNr(4))
        stepFwdBtn = QPushButton(">")
        stepFwdBtn.clicked.connect(lambda: self.updateFrameNr(5))
        skipFwdBtn = QPushButton(">>")
        skipFwdBtn.clicked.connect(lambda: self.updateFrameNr(6))
        btnLayout = QHBoxLayout()
        btnLayout.addWidget(frameSpinLabel)
        btnLayout.addWidget(self.frameSpin)
        btnLayout.addWidget(skipBackBtn)
        btnLayout.addWidget(stepBackBtn)
        btnLayout.addWidget(stepFwdBtn)
        btnLayout.addWidget(skipFwdBtn)
        # self.rightLayout.addWidget(scroll, 0, 0)
        self.rightLayout.addWidget(self.dispLabel, 0, 0)
        self.rightLayout.addWidget(self.frameSlider, 1, 0)
        self.rightLayout.addLayout(btnLayout, 2, 0)
        self.rightLayout.setRowStretch(0, 1)
        self.rightLayout.setColumnStretch(0, 1)

    def _change_format(self):
        self._format_params.change_format(
            "PAL", self.systemComboBox.currentText(), self._logger
        )
        self.drawImage()

    def createControlsGroupBox(self):
        self.controlsGroupBox = QGroupBox("Controls")
        layout = QVBoxLayout()
        openRefTBCFileButton = QPushButton("Open reference TBC")
        openRefTBCFileButton.clicked.connect(self.openRefTBCFile)
        openProTBCFileButton = QPushButton("Open TBC to process")
        openProTBCFileButton.clicked.connect(self.openProTBCFile)

        layout.addWidget(openRefTBCFileButton)
        layout.addWidget(openProTBCFileButton)

        self.systemComboBox = QComboBox()
        supported_tape_formats_list = list(supported_tape_formats)
        index_of_vhs = supported_tape_formats_list.index("VHS")
        self.systemComboBox.addItems(supported_tape_formats_list)
        self.systemComboBox.setCurrentIndex(index_of_vhs)
        self.systemComboBox.currentIndexChanged.connect(self._change_format)
        layout.addWidget(self.systemComboBox)

        self.refOffset = QSpinBox()
        self.refOffset.setRange(-10000, 10000)
        self.refOffset.setValue(0)
        refOffsetLabel = QLabel("Offset of reference TBC:")
        refOffsetLabel.setBuddy(self.refOffset)
        self.refOffset.valueChanged.connect(self.updateImage)

        layout.addWidget(refOffsetLabel)
        layout.addWidget(self.refOffset)

        #        self.tbcWidth = QSpinBox()
        #        self.tbcWidth.setRange(1,10000)
        #        self.tbcWidth.setValue(FRAME_WIDTH)
        #        tbcWidthLabel = QLabel("TBC width:")
        #        tbcWidthLabel.setBuddy(self.tbcWidth)

        #        layout.addWidget(tbcWidthLabel)
        #        layout.addWidget(self.tbcWidth)

        #        self.tbcHeight = QSpinBox()
        #        self.tbcHeight.setRange(1,10000)
        #        self.tbcHeight.setValue(313)
        #        tbcHeightLabel = QLabel("TBC height (field lines):")
        #        tbcHeightLabel.setBuddy(self.tbcHeight)

        #        layout.addWidget(tbcHeightLabel)
        #        layout.addWidget(self.tbcHeight)

        self.swapTrackFieldChkBox = QCheckBox("Swap track / field (invert track phase)")
        self.swapTrackFieldChkBox.setCheckState(0)
        self.swapTrackFieldChkBox.stateChanged.connect(self.drawImage)

        layout.addWidget(self.swapTrackFieldChkBox)

        self.showFieldsChkBox = QCheckBox("Show fields separated")
        self.showFieldsChkBox.setCheckState(0)
        self.showFieldsChkBox.stateChanged.connect(self.updateImage)

        layout.addWidget(self.showFieldsChkBox)

        self.displayWidthSlider = QSlider(Qt.Horizontal, self.controlsGroupBox)
        self.displayWidthSlider.setRange(1, 200)
        self.displayWidthSlider.setValue(50)
        self.displayWidthSlider.setTickPosition(QSlider.TicksBelow)
        self.displayWidthSlider.valueChanged.connect(self.drawImage)

        displayWidthLabel = QLabel("Display width (in percent):")
        displayWidthLabel.setBuddy(self.displayWidthSlider)

        layout.addWidget(displayWidthLabel)
        layout.addWidget(self.displayWidthSlider)

        self.displayHeightSlider = QSlider(Qt.Horizontal, self.controlsGroupBox)
        self.displayHeightSlider.setRange(1, 5)
        self.displayHeightSlider.setValue(1)
        self.displayHeightSlider.setTickPosition(QSlider.TicksBelow)
        self.displayHeightSlider.valueChanged.connect(self.drawImage)

        displayHeightLabel = QLabel("Display height (factor):")
        displayHeightLabel.setBuddy(self.displayHeightSlider)

        layout.addWidget(displayHeightLabel)
        layout.addWidget(self.displayHeightSlider)

        self.controlsGroupBox.setLayout(layout)

    def createFilterGroupBox(self):
        self.filterGroupBox = QGroupBox("Filter settings")
        layout = QVBoxLayout()

        for k in self.filter_params.keys():
            if self.filter_params[k]["step"] is None:
                self.filter_params[k]["ctrl"] = QCheckBox(self.filter_params[k]["desc"])
                self.filter_params[k]["ctrl"].setChecked(self.filter_params[k]["value"])
                self.filter_params[k]["ctrl"].stateChanged.connect(
                    lambda state, x=k: self.updateImage(True, x)
                )
                layout.addWidget(self.filter_params[k]["ctrl"])
            elif self.filter_params[k]["value"] is not None:
                self.filter_params[k]["ctrl"] = QSlider(
                    Qt.Horizontal, self.filterGroupBox
                )
                self.filter_params[k]["ctrl"].setTracking(False)
                self.filter_params[k]["ctrl"].setRange(
                    int(self.filter_params[k]["min"] / self.filter_params[k]["step"]),
                    int(self.filter_params[k]["max"] / self.filter_params[k]["step"]),
                )
                self.filter_params[k]["ctrl"].setValue(
                    int(self.filter_params[k]["value"] / self.filter_params[k]["step"])
                )
                self.filter_params[k]["ctrl"].valueChanged.connect(
                    lambda state, x=k: self.updateImage(True, x)
                )
                self.filter_params[k]["label"] = QLabel(
                    self.filter_params[k]["desc"].format(self.filter_params[k]["value"])
                )
                self.filter_params[k]["label"].setBuddy(self.filter_params[k]["ctrl"])
                layout.addWidget(self.filter_params[k]["label"])
                layout.addWidget(self.filter_params[k]["ctrl"])

        layout.addStretch(1)
        self.filterGroupBox.setLayout(layout)

    def createStyleGroupBox(self):
        self.styleGroupBox = QGroupBox("Style")
        layout = QVBoxLayout()

        styleComboBox = QComboBox()
        styleComboBox.addItems(QStyleFactory.keys())

        styleLabel = QLabel("&Style:")
        styleLabel.setBuddy(styleComboBox)

        self.useStylePaletteCheckBox = QCheckBox("&Use style's standard palette")
        self.useStylePaletteCheckBox.setChecked(True)

        styleComboBox.activated[str].connect(self.changeStyle)
        self.useStylePaletteCheckBox.toggled.connect(self.changePalette)

        layout.addWidget(styleLabel)
        layout.addWidget(styleComboBox)
        layout.addWidget(self.useStylePaletteCheckBox)

        self.styleGroupBox.setLayout(layout)

    def changeStyle(self, styleName):
        QApplication.setStyle(QStyleFactory.create(styleName))
        self.changePalette()

    def changePalette(self):
        if self.useStylePaletteCheckBox.isChecked():
            QApplication.setPalette(QApplication.style().standardPalette())
        else:
            QApplication.setPalette(self.originalPalette)


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    logger = logging.getLogger("vhstune")
    vhsTune = VHStune(logger)
    vhsTune.show()
    pos = vhsTune.pos()
    if pos.x() < 0 or pos.y() < 0:
        vhsTune.move(0, 0)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
