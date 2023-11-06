#!/usr/bin/env python3

# released under GNU GPL v3 or later

import math
import numpy as np
import numpy.fft as npfft
import scipy.signal as signal
import os
import sys

from PyQt5.QtCore import (Qt, QByteArray, QCryptographicHash, QMetaType, QSize)
from PyQt5.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QApplication, QCheckBox, QComboBox,
                             QDialog, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QMessageBox, QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox,
                             QStyleFactory, QSizePolicy, QTableWidgetItem, QTextEdit, QVBoxLayout)
from PyQt5.QtGui import (QBrush, QGuiApplication, QImage, QKeySequence, QKeyEvent, QPalette, QPixmap)

## System params

params = {}
params["VHS"] = {}
params["VHS"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["VHS"]["hz_ire"] = 1e6 / (100 + (-params["VHS"]["vsync_ire"]))
params["VHS"]["ire0"] = 4.8e6 - (params["VHS"]["hz_ire"] * 100)
params["VHS"]["ire0_track_offset"] = [0, 0]
params["VHS"]["outputZero"] = 256
params["VHS"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["VHS"]["vsync_ire"])
params["VHS"]["nl_deviation"] = 0.4 * (100 / 0.7)
params["VHS HQ"] = {}
params["VHS HQ"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["VHS HQ"]["hz_ire"] = 1e6 / (100 + (-params["VHS HQ"]["vsync_ire"]))
params["VHS HQ"]["ire0"] = 4.8e6 - (params["VHS HQ"]["hz_ire"] * 100)
params["VHS HQ"]["ire0_track_offset"] = [7812.5, 0]
params["VHS HQ"]["outputZero"] = 256
params["VHS HQ"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["VHS HQ"]["vsync_ire"])
params["VHS HQ"]["nl_deviation"] = 0.4 * (100 / 0.7)
params["S-VHS"] = {}
params["S-VHS"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["S-VHS"]["hz_ire"] = 1.6e6 / (100 + (-params["S-VHS"]["vsync_ire"]))
params["S-VHS"]["ire0"] = 7e6 - (params["S-VHS"]["hz_ire"] * 100)
params["S-VHS"]["ire0_track_offset"] = [7812.5, 0]
params["S-VHS"]["outputZero"] = 256
params["S-VHS"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["S-VHS"]["vsync_ire"])
params["S-VHS"]["nl_deviation"] = 0.4 * (100 / 0.7) 
params["Betamax"] = {}
params["Betamax"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["Betamax"]["hz_ire"] = 1.4e6 / (100 + (-params["Betamax"]["vsync_ire"]))
params["Betamax"]["ire0"] = 5.2e6 - (params["Betamax"]["hz_ire"] * 100)
params["Betamax"]["ire0_track_offset"] = [0, 0]
params["Betamax"]["outputZero"] = 256
params["Betamax"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["Betamax"]["vsync_ire"])
params["Video8"] = {}
params["Video8"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["Video8"]["hz_ire"] = 1.2e6 / (100 + (-params["Video8"]["vsync_ire"]))
params["Video8"]["ire0"] = 5.4e6 - (params["Video8"]["hz_ire"] * 100)
params["Video8"]["ire0_track_offset"] = [0, 0]
params["Video8"]["outputZero"] = 256
params["Video8"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["Video8"]["vsync_ire"])
params["Hi8"] = {}
params["Hi8"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["Hi8"]["hz_ire"] = 2e6 / (100 + (-params["Hi8"]["vsync_ire"]))
params["Hi8"]["ire0"] = 7.7e6 - (params["Hi8"]["hz_ire"] * 100)
params["Hi8"]["ire0_track_offset"] = [0, 0]
params["Hi8"]["outputZero"] = 256
params["Hi8"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["Hi8"]["vsync_ire"])
params["Umatic"] = {}
params["Umatic"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["Umatic"]["hz_ire"] = 1600000 / 140.0
params["Umatic"]["ire0"] = 4257143
params["Umatic"]["ire0_track_offset"] = [0, 0]
params["Umatic"]["outputZero"] = 256
params["Umatic"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["Umatic"]["vsync_ire"])
params["VCR"] = {}
params["VCR"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["VCR"]["hz_ire"] = 1400000 / (100 + (-params["VCR"]["vsync_ire"]))
params["VCR"]["ire0"] = 3.0e6 + (params["VCR"]["hz_ire"] * -params["VCR"]["vsync_ire"])
params["VCR"]["ire0_track_offset"] = [0, 0]
params["VCR"]["outputZero"] = 256
params["VCR"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["VCR"]["vsync_ire"])
params["EIA-J"] = {}
params["EIA-J"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["EIA-J"]["hz_ire"] = 1800000 / (100 + (-params["EIA-J"]["vsync_ire"]))
params["EIA-J"]["ire0"] = 3.8e6 + (params["EIA-J"]["hz_ire"] * -params["EIA-J"]["vsync_ire"])
params["EIA-J"]["ire0_track_offset"] = [0, 0]
params["EIA-J"]["outputZero"] = 256
params["EIA-J"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["EIA-J"]["vsync_ire"])
params["Type B"] = {}
params["Type B"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["Type B"]["hz_ire"] = (8.9e6-7.4e6) / 143.0
params["Type B"]["ire0"] = 7.40e6
params["Type B"]["ire0_track_offset"] = [0, 0]
params["Type B"]["outputZero"] = 256
params["Type B"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["Type B"]["vsync_ire"])
params["Type C"] = {}
params["Type C"]["vsync_ire"] = -0.3 * (100 / 0.7)
params["Type C"]["hz_ire"] = 1740000 / 143.0
params["Type C"]["ire0"] = 7.68e6
params["Type C"]["ire0_track_offset"] = [0, 0]
params["Type C"]["outputZero"] = 256
params["Type C"]["out_scale"] = np.double(0xC800 - 0x0400) / (100 - params["Type C"]["vsync_ire"])
blocklen = 32768
fs = (((1 / 64) * 283.75) + (25 / 1000000)) * 8e6
#fs = 40000000
# 2560
frame_width = 1135
print("fs  = ", fs)

def multicall(l = []):
    for c in l:
        c()

### copied from vhs-decode

def hz_to_output(inp, phase=0, sys="VHS"):
    reduced = (inp - params[sys]["ire0"] - params[sys]["ire0_track_offset"][phase]) / params[sys]["hz_ire"]
    reduced -= params[sys]["vsync_ire"]
    return np.uint16(
    np.clip(
            (reduced * params[sys]["out_scale"]) + params[sys]["outputZero"], 0, 65535
        )
        + 0.5
    )

def gen_high_shelf(f0, dbgain, qfactor, fs):
    """Generate high shelving filter coeficcients (digital).
    f0: The center frequency where the gain in decibel is at half the maximum value.
       Normalized to sampling frequency, i.e output will be filter from 0 to 2pi.
    dbgain: gain at the top of the shelf in decibels
    qfactor: determines shape of filter TODO: Document better
    fs: sampling frequency

    TODO: Generate based on -3db
    Based on: https://www.w3.org/2011/audio/audio-eq-cookbook.html
    """
    a = 10 ** (dbgain / 40.0)
    w0 = 2 * math.pi * (f0 / fs)
    alpha = math.sin(w0) / (2 * qfactor)

    cosw0 = math.cos(w0)
    asquared = math.sqrt(a)

    b0 = a * ((a + 1) + (a - 1) * cosw0 + 2 * asquared * alpha)
    b1 = -2 * a * ((a - 1) + (a + 1) * cosw0)
    b2 = a * ((a + 1) + (a - 1) * cosw0 - 2 * asquared * alpha)
    a0 = (a + 1) - (a - 1) * cosw0 + 2 * asquared * alpha
    a1 = 2 * ((a - 1) - (a + 1) * cosw0)
    a2 = (a + 1) - (a - 1) * cosw0 - 2 * asquared * alpha
    return [b0, b1, b2], [a0, a1, a2]

# This converts a regular B, A filter to an FFT of our selected block length
# if Whole is false, output only up to and including the nyquist frequency (for use with rfft)
def filtfft(filt, blocklen, whole=True):
    # worN = blocklen if whole else (blocklen // 2) + 1
    worN = blocklen
    output_size = blocklen if whole else (blocklen // 2) + 1

    # When not calculating the whole spectrum,
    # we still need to include the nyquist value here to give the same result as with
    # the whole freq range output.
    # This requires scipy 1.5.0 or newer.
    # return signal.freqz(filt[0], filt[1], worN, whole=whole, include_nyquist=True)[1]

    # Using the old way for now.
    return signal.freqz(filt[0], filt[1], worN, whole=True)[1][:output_size]

def genDeemphFilter(mid_point, dBgain, Q):
    da, db = gen_high_shelf(mid_point, dBgain, Q, fs)
    return filtfft((db, da), blocklen, whole=False)

def genHighpass(freq, fs_hz):
    nyq = fs_hz / 2.0
    return filtfft(signal.butter(1,[freq / nyq], btype="highpass"), blocklen, whole=False)    

def genLowpass(freq, fs_hz):
    nyq = fs_hz / 2.0
    return filtfft(signal.butter(1,[freq / nyq], btype="lowpass"), blocklen, whole=False)   

#####

def readVHSFrame(f, nr, w, h):
    out = None
    offset=(nr*(2*w*h)-1024)*4
    #offset=0
    try:
        #1638400
        out = np.fromfile(f,dtype=np.single,count=1638400,offset=offset)
    except:
        print("Failed to load VHS frame from tbc file")
    return out

def readRefFrame(f, nr, w, h, offset=0):
    outa = None
    outb = None
    try:
        out_video = np.fromfile(f,dtype=np.uint16,count=(2*w*h),offset=(nr-offset)*(2*w*h)*2)
        outa = out_video[0:(w*h)]
        outb = out_video[(w*h):(2*w*h)]
    except:
        print("Failed to load reference frame from tbc file")
    return outa, outb

class VHStune(QDialog):

    refTBCFilename = ''
    proTBCFilename = ''
    title = "VHStune"

    curFrameNr = 1
    totalFrames = 2

    def makeFilterParams(self):
        self.filter_params = { 
#          "deemph_enable": { "value": True, "step": None, "desc": "Enable deemphasis", "onchange": [ self.applyFilter, self.drawImage ] },
          "deemph_mid": { "value": 370000, "step": 5000, "min": 10000, "max": 4000000, "desc": 'Deemphasis mid freq ({:.0f} Hz):', "onchange": [ self.calcDeemphFilter, self.applyDeemphFilter, self.applyNLSVHSFilter, self.drawImage ] },
          "deemph_gain": { "value": 14, "step": 0.5, "min": -30, "max": 30, "desc": 'Deemphasis gain ({:.1f} dB):', "onchange": [ self.calcDeemphFilter, self.applyDeemphFilter, self.applyNLSVHSFilter, self.drawImage ] },
          "deemph_q": { "value": 0.5, "step": 0.05, "min": 0.05, "max": 5, "desc": 'Deemphasis Q ({:.2f}):', "onchange": [ self.calcDeemphFilter, self.applyDeemphFilter, self.applyNLSVHSFilter, self.drawImage ] },
          "nonlinear_deemph_enable": { "value": False, "step": None, "desc": "Enable non-linear deemphasis", "onchange": [ self.drawImage ] },
          "nonlinear_deemph_showonly": { "value": False, "step": None, "desc": "Show only subtracted non-linear deemphasis part", "onchange": [ self.drawImage ] },
          "nonlinear_highpass_freq": { "value": 500000, "step": 5000, "min": 10000, "max": 4000000, "desc": 'Non-linear high-pass freq ({} Hz):', "onchange": [ self.calcNLHPFilter, self.applyNLDeemphFilterA, self.applyNLDeemphFilterB, self.drawImage ] },
          "nonlinear_linear_scale": { "value": 1.0, "step": 0.05, "min": 0.05, "max": 2.0, "desc": 'Non-linear linear scale ({:.2f}):', "onchange": [ self.applyNLDeemphFilterB, self.drawImage ] },
          "nonlinear_linear_scale_b": { "value": 1.0, "step": 0.01, "min": 0.01, "max": 2.0, "desc": 'Non-linear linear scale B ({:.2f}):', "onchange": [ self.applyNLDeemphFilterB, self.drawImage ] },
          "nonlinear_exponential_scale": { "value": 0.33, "step": 0.01, "min": 0.05, "max": 2, "desc": 'Non-linear exponential scale ({:.2f}):', "onchange": [ self.applyNLDeemphFilterB, self.drawImage ] },
          "svhs_deemph_enable": { "value": True, "step": None, "desc": "Enable S-VHS non-linear deemphasis", "onchange": [ self.drawImage ] },
          "svhs_crossover_freq": { "value": 400000, "step": 5000, "min": 10000, "max": 4000000, "desc": 'Crossover freq ({} Hz):', "onchange": [ self.calcNLSVHSFilter, self.applyNLSVHSFilter, self.drawImage ] },
          "svhs_lowpass_freq": { "value": 7000000, "step": 10000, "min": 1000000, "max": 8000000, "desc": 'Lowpass freq ({} Hz):', "onchange": [ self.calcNLSVHSFilter, self.applyNLSVHSFilter, self.drawImage ] },
          "svhs_lf_in_level": { "value": 1.0, "step": 0.01, "min": 0.5, "max": 2.0, "desc": 'LF input level ({:.2f}):', "onchange": [ self.applyNLSVHSFilter, self.drawImage ] },
          "svhs_hf_in_level": { "value": 1.0, "step": 0.01, "min": 0.5, "max": 2.0, "desc": 'HF input level ({:.2f}):', "onchange": [ self.applyNLSVHSFilter, self.drawImage ] },
          "svhs_lf_out_level": { "value": 0.815, "step": 0.001, "min": 0.7, "max": 1.0, "desc": 'LF output level ({:.3f}):', "onchange": [ self.applyNLSVHSFilter, self.drawImage ] },
          "svhs_hf_out_level": { "value": 0.66, "step": 0.01, "min": 0.25, "max": 2.0, "desc": 'HF output level ({:.2f}):', "onchange": [ self.applyNLSVHSFilter, self.drawImage ] }
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

    def updateImage(self, f = False, k = None):
        if f is True:
            if self.filter_params[k]["step"] is None:
                self.filter_params[k]["value"] = self.filter_params[k]["ctrl"].isChecked()
            else:
                self.filter_params[k]["value"] = self.filter_params[k]["step"] * self.filter_params[k]["ctrl"].value()
                self.filter_params[k]["label"].setText(self.filter_params[k]["desc"].format(self.filter_params[k]["value"]))
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
        fileName = QFileDialog.getOpenFileName(self, "Open reference tbc file", self.refTBCFilename, "tbc files (*.tbc)")
        if fileName is not None and fileName[0] != '':
            self.refTBCFilename = fileName[0]
            self.updateImage()

    def openProTBCFile(self):
        fileName = QFileDialog.getOpenFileName(self, "Open to processed tbc file", self.proTBCFilename, "tbc files (*.tbc)")
        if fileName is not None and fileName[0] != '':
            self.proTBCFilename = fileName[0]
            fSize = os.path.getsize(self.proTBCFilename)
            self.totalFrames = math.floor(fSize/(4*2*frame_width*313))
            self.frameSlider.setRange(1,self.totalFrames-2)
            self.frameSpin.setRange(1,self.totalFrames-2)
            self.updateImage()

    def loadImage(self):
        self.refFieldA, self.refFieldB = readRefFrame(self.refTBCFilename, self.curFrameNr, frame_width, 313, self.refOffset.value())
        self.vhsFrameData = readVHSFrame(self.proTBCFilename, self.curFrameNr, frame_width, 313)
        pos = 0
        self.fftData = []
        while pos < (len(self.vhsFrameData) - blocklen):
            self.fftData.append(npfft.rfft(self.vhsFrameData[pos:pos+blocklen]))
            pos += (blocklen - 2048)

    def calcDeemphFilter(self):
        self.deemphFilter = genDeemphFilter(self.filter_params["deemph_mid"]["value"],self.filter_params["deemph_gain"]["value"],self.filter_params["deemph_q"]["value"])

    def calcNLHPFilter(self):
        self.NLHPFilter = genHighpass(self.filter_params["nonlinear_highpass_freq"]["value"], fs)
    
    def calcNLSVHSFilter(self):
        self.NLSVHSLPFilter = genLowpass(self.filter_params["svhs_crossover_freq"]["value"], fs)
        self.NLSVHSHPFilter = genHighpass(self.filter_params["svhs_crossover_freq"]["value"], fs)
        self.NLSVHSLPBFilter = genLowpass(self.filter_params["svhs_lowpass_freq"]["value"], fs)
        #self.NLSVHSACFilter = genHighpass(200000)

    def applyNLSVHSFilter(self):
        self.ProcessedSVHSFrame = []
        for b in self.fftData:
            hf_part = npfft.irfft(b * self.deemphFilter * self.NLSVHSHPFilter * self.NLSVHSLPBFilter)
            lf_part = npfft.irfft(b * self.deemphFilter * self.NLSVHSLPFilter)
            #dc_part = npfft.irfft(b * self.deemphFilter * self.NLSVHSACFilter)
            hf_amp = abs(signal.hilbert(hf_part)) / (params[self.systemComboBox.currentText()]["nl_deviation"] * params[self.systemComboBox.currentText()]["hz_ire"]) * self.filter_params["svhs_hf_in_level"]["value"]
            lf_amp = abs(signal.hilbert(lf_part)) / (params[self.systemComboBox.currentText()]["nl_deviation"] * params[self.systemComboBox.currentText()]["hz_ire"]) * self.filter_params["svhs_lf_in_level"]["value"]
            hf_amp_scaled = 1.0 / (0.26007715*np.exp(-0.4152129*(np.log(hf_amp)-1.27878766))+0.55291881)
            lf_amp_scaled = 1.0 / (0.15124517*np.exp(-3.41855724*lf_amp)+0.81349599)
            #  * lf_amp_scaled * 
            self.ProcessedSVHSFrame.append(hf_part * hf_amp_scaled * self.filter_params["svhs_hf_out_level"]["value"] + lf_part * lf_amp_scaled * self.filter_params["svhs_lf_out_level"]["value"])

    def applyNLDeemphFilterA(self):
        self.NLDeemphAmplitude = []
        self.NLDeemphPart = []
        for b in self.fftData:
            hf_part = npfft.irfft(b * self.NLHPFilter)
            self.NLDeemphPart.append(hf_part)
            self.NLDeemphAmplitude.append(abs(signal.hilbert(hf_part)) / (params[self.systemComboBox.currentText()]["nl_deviation"] * params[self.systemComboBox.currentText()]["hz_ire"]))

    def applyNLDeemphFilterB(self):
        self.NLProcessed = []
        for i in range(len(self.NLDeemphAmplitude)):
            amplitude_scaled = self.NLDeemphAmplitude[i] * self.filter_params["nonlinear_linear_scale"]["value"]
            amplitude_scaled = np.power(amplitude_scaled, self.filter_params["nonlinear_exponential_scale"]["value"])
            amplitude_scaled *= self.filter_params["nonlinear_linear_scale_b"]["value"]
            self.NLProcessed.append(self.NLDeemphPart[i] * (1 - amplitude_scaled))

    def applyDeemphFilter(self):
        self.ProcessedFrame = []
        for b in self.fftData:
            self.ProcessedFrame.append(npfft.irfft(b*self.deemphFilter).real)
            
    def drawImage(self):
        outImage = None
        for i in range(len(self.ProcessedFrame)):
            if self.filter_params["svhs_deemph_enable"]["value"] is True:
                img = self.ProcessedSVHSFrame[i].copy()
            else:
                img = self.ProcessedFrame[i].copy()
            if self.filter_params["nonlinear_deemph_enable"]["value"] is True:
                if self.filter_params["nonlinear_deemph_showonly"]["value"] is True:
                    img.fill(6200000)
                    img += self.NLProcessed[i]
                else:
                    img -= self.NLProcessed[i]
            if outImage is None:
                outImage = img[1024:31744]
            else:
                outImage = np.append(outImage,img[1024:31744])
        height = 313
        width = frame_width
        field_samples = height * width

        vhsFieldA = hz_to_output(outImage[0:field_samples], 0^int(self.swapTrackFieldChkBox.isChecked()), self.systemComboBox.currentText())
        vhsFieldB = hz_to_output(outImage[field_samples:field_samples * 2], 1^int(self.swapTrackFieldChkBox.isChecked()), self.systemComboBox.currentText())
        outFieldA = None
        outFieldB = None
        if self.refFieldA is not None and self.refFieldB is not None:
            height *= 2
            outFieldA = np.append(self.refFieldA,vhsFieldA)
            outFieldB = np.append(self.refFieldB,vhsFieldB)
        else:
            outFieldA = vhsFieldA
            outFieldB = vhsFieldB

        if self.showFieldsChkBox.isChecked() is True:
            outFrame = np.append(outFieldA,outFieldB)
        else:
            outFrame = np.empty((height*2,width),dtype=np.uint16)
            outFrame[::2,:] = outFieldA.reshape(height, width)
            outFrame[1::2,:] = outFieldB.reshape(height, width)
        pixmap = QPixmap(QImage(outFrame.data, frame_width, height*2, frame_width*2, QImage.Format_Grayscale16))
        if self.displayWidthSlider.value() != 100:
            pixmap = pixmap.scaled(QSize(int(frame_width*(self.displayWidthSlider.value()/100.0)), height*2),transformMode=Qt.SmoothTransformation)
        if self.displayHeightSlider.value() != 1:
            pixmap = pixmap.scaled(QSize(pixmap.width(), height*2*self.displayHeightSlider.value()),transformMode=Qt.FastTransformation)
        self.dispLabel.setPixmap(pixmap)

    def __init__(self, parent=None):
        super(VHStune, self).__init__(parent, Qt.Window |
                                              Qt.WindowMinimizeButtonHint |
                                              Qt.WindowMaximizeButtonHint |
                                              Qt.WindowCloseButtonHint)

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
        #mainLayout.setRowStretch(1, 1)
        mainLayout.setColumnStretch(1, 1)
        #mainLayout.setColumnStretch(1, 1)
        self.setLayout(mainLayout)

        self.setWindowTitle(self.title)
        
        self.initFilters()

    def createRightArea(self):
        self.rightLayout = QGridLayout()
        #scroll = QScrollArea()
        #scroll.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.dispLabel = QLabel()
        self.dispLabel.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        #scroll.setWidget(self.dispLabel)
        self.frameSlider = QSlider(Qt.Horizontal, self)

        self.frameSlider.setRange(1,1)
        self.frameSlider.setValue(1)
        self.frameSpin = QSpinBox()
        
        self.frameSpin.setRange(1,1)
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
        #self.rightLayout.addWidget(scroll, 0, 0)
        self.rightLayout.addWidget(self.dispLabel, 0, 0)
        self.rightLayout.addWidget(self.frameSlider, 1, 0)
        self.rightLayout.addLayout(btnLayout, 2, 0)
        self.rightLayout.setRowStretch(0, 1)
        self.rightLayout.setColumnStretch(0, 1)

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
        self.systemComboBox.addItems(params.keys())
        self.systemComboBox.currentIndexChanged.connect(self.drawImage)
        layout.addWidget(self.systemComboBox)

        self.refOffset = QSpinBox()
        self.refOffset.setRange(-10000,10000)
        self.refOffset.setValue(0)
        refOffsetLabel = QLabel("Offset of reference TBC:")
        refOffsetLabel.setBuddy(self.refOffset)
        self.refOffset.valueChanged.connect(self.updateImage)
        
        layout.addWidget(refOffsetLabel)
        layout.addWidget(self.refOffset)

#        self.tbcWidth = QSpinBox()
#        self.tbcWidth.setRange(1,10000)
#        self.tbcWidth.setValue(frame_width)
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

        self.swapTrackFieldChkBox = QCheckBox('Swap track / field (invert track phase)')
        self.swapTrackFieldChkBox.setCheckState(0)
        self.swapTrackFieldChkBox.stateChanged.connect(self.drawImage)

        layout.addWidget(self.swapTrackFieldChkBox)

        self.showFieldsChkBox = QCheckBox('Show fields separated')
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
                self.filter_params[k]["ctrl"].stateChanged.connect(lambda state,x=k: self.updateImage(True,x))
                layout.addWidget(self.filter_params[k]["ctrl"]) 
            else:
                self.filter_params[k]["ctrl"] = QSlider(Qt.Horizontal, self.filterGroupBox)
                self.filter_params[k]["ctrl"].setRange(int(self.filter_params[k]["min"]/self.filter_params[k]["step"]),int(self.filter_params[k]["max"]/self.filter_params[k]["step"]))
                self.filter_params[k]["ctrl"].setValue(int(self.filter_params[k]["value"]/self.filter_params[k]["step"]))
                self.filter_params[k]["ctrl"].valueChanged.connect(lambda state,x=k: self.updateImage(True,x))
                self.filter_params[k]["label"] = QLabel(self.filter_params[k]["desc"].format(self.filter_params[k]["value"]))
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
        if (self.useStylePaletteCheckBox.isChecked()):
            QApplication.setPalette(QApplication.style().standardPalette())
        else:
            QApplication.setPalette(self.originalPalette)

if __name__ == '__main__':

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    vhsTune = VHStune()
    vhsTune.show()
    pos = vhsTune.pos()
    if pos.x() < 0 or pos.y() < 0:
        vhsTune.move(0,0)
    sys.exit(app.exec_())
