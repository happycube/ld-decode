/******************************************************************************
 * chromadecoderconfigdialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2019-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef CHROMADECODERCONFIGDIALOG_H
#define CHROMADECODERCONFIGDIALOG_H

#include <QAbstractButton>
#include <QDialog>

#include "comb.h"
#include "outputwriter.h"
#include "palcolour.h"
#include "monodecoder.h"
#include "tbcsource.h"

namespace Ui {
class ChromaDecoderConfigDialog;
}

class ChromaDecoderConfigDialog : public QDialog
{
    Q_OBJECT

public:
    explicit ChromaDecoderConfigDialog(QWidget *parent = nullptr);
    ~ChromaDecoderConfigDialog();

    void setConfiguration(VideoSystem system, const PalColour::Configuration &palConfiguration,
                          const Comb::Configuration &ntscConfiguration,
                          const MonoDecoder::MonoConfiguration &monoConfiguration,
                          const TbcSource::SourceMode &_mode,
						  const bool _isInit,
                          const OutputWriter::Configuration &outputConfiguration);
    const PalColour::Configuration &getPalConfiguration();
    const Comb::Configuration &getNtscConfiguration();
    const OutputWriter::Configuration &getOutputConfiguration();

signals:
    void chromaDecoderConfigChanged();

public slots:
	void updateSourceMode(TbcSource::SourceMode mode);

private slots:
    void on_chromaGainHorizontalSlider_valueChanged(int value);
    void on_chromaPhaseHorizontalSlider_valueChanged(int value);
	void on_enableYNRCheckBox_clicked();
	void on_enableYCCombineCheckBox_clicked();

    void on_palFilterButtonGroup_buttonClicked(QAbstractButton *button);
    void on_thresholdHorizontalSlider_valueChanged(int value);
    void on_showFFTsCheckBox_clicked();
    void on_simplePALCheckBox_clicked();

    void on_ntscFilterButtonGroup_buttonClicked(QAbstractButton *button);
    void on_phaseCompCheckBox_clicked();
    void on_adaptiveCheckBox_clicked();
    void on_showMapCheckBox_clicked();
    void on_cNRHorizontalSlider_valueChanged(int value);
    void on_yNRHorizontalSlider_valueChanged(int value);

private:
    Ui::ChromaDecoderConfigDialog *ui;
    VideoSystem system;
    PalColour::Configuration palConfiguration;
    Comb::Configuration ntscConfiguration;
    MonoDecoder::MonoConfiguration monoConfiguration;
    OutputWriter::Configuration outputConfiguration;
	TbcSource* tbcSource = nullptr;
	TbcSource::SourceMode sourceMode;
	double ynrLevel = 0;
	bool isInit = true;
	bool combine = false;
	bool yNREnabled = true;

    void updateDialog();
};

#endif // CHROMADECODERCONFIGDIALOG_H
