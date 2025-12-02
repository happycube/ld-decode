/******************************************************************************
 * chromadecoderconfigdialog.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2019-2025 Simon Inns
 * SPDX-FileCopyrightText: 2020-2022 Adam Sampson
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "chromadecoderconfigdialog.h"
#include "ui_chromadecoderconfigdialog.h"
#include "mainwindow.h"

#include <cmath>

/*
 * These two functions provide a non-linear mapping for sliders that control
 * phase adjustments in degrees. The maximum range is from -180 to +180
 * degrees, but phase errors are usually < 10 degrees so we need more precise
 * adjustment in the middle.
 */

static constexpr double DEGREE_SLIDER_POWER = 3.0;
static constexpr qint32 DEGREE_SLIDER_SCALE = 1000;

static double degreesToSliderPos(double degrees) {
    double sliderPos = pow(abs(degrees) / 180, 1 / DEGREE_SLIDER_POWER) * DEGREE_SLIDER_SCALE;
    if (degrees < 0) {
        return -sliderPos;
    } else {
        return sliderPos;
    }
}

static double sliderPosToDegrees(double sliderPos) {
    double degrees = pow(abs(sliderPos) / DEGREE_SLIDER_SCALE, DEGREE_SLIDER_POWER) * 180;
    if (sliderPos < 0) {
        return -degrees;
    } else {
        return degrees;
    }
}

ChromaDecoderConfigDialog::ChromaDecoderConfigDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::ChromaDecoderConfigDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    ui->chromaGainHorizontalSlider->setMinimum(0);
    ui->chromaGainHorizontalSlider->setMaximum(200);

    ui->chromaPhaseHorizontalSlider->setMinimum(-DEGREE_SLIDER_SCALE);
    ui->chromaPhaseHorizontalSlider->setMaximum(DEGREE_SLIDER_SCALE);

    ui->thresholdHorizontalSlider->setMinimum(0);
    ui->thresholdHorizontalSlider->setMaximum(100);

    ui->cNRHorizontalSlider->setMinimum(0);
    ui->cNRHorizontalSlider->setMaximum(100);

    ui->yNRHorizontalSlider->setMinimum(0);
    ui->yNRHorizontalSlider->setMaximum(100);
    
	//get tbcSource instance from mainWindow
	if (auto mw = qobject_cast<MainWindow*>(parent)) {
		tbcSource = &mw->getTbcSource();
	}
	
    // Update the dialogue
    updateDialog();
}

ChromaDecoderConfigDialog::~ChromaDecoderConfigDialog()
{
    delete ui;
}

void ChromaDecoderConfigDialog::setConfiguration(VideoSystem _system, const PalColour::Configuration &_palConfiguration,
                                                 const Comb::Configuration &_ntscConfiguration,
                                                 const MonoDecoder::MonoConfiguration &_monoConfiguration,
												 const TbcSource::SourceMode &_mode,
												 const bool _isInit,
                                                 const OutputWriter::Configuration &_outputConfiguration)
{
    double yNRLevel = _system == NTSC ? ntscConfiguration.yNRLevel : palConfiguration.yNRLevel;
    system = _system;
    palConfiguration = _palConfiguration;
    ntscConfiguration = _ntscConfiguration;
    monoConfiguration = _monoConfiguration;
    outputConfiguration = _outputConfiguration;
	sourceMode = _mode;

    palConfiguration.chromaGain = qBound(0.0, palConfiguration.chromaGain, 2.0);
    palConfiguration.chromaPhase = qBound(-180.0, palConfiguration.chromaPhase, 180.0);
    palConfiguration.transformThreshold = qBound(0.0, palConfiguration.transformThreshold, 1.0);
    palConfiguration.yNRLevel = qBound(0.0, yNRLevel, 10.0);
    ntscConfiguration.cNRLevel = qBound(0.0, ntscConfiguration.cNRLevel, 10.0);
    ntscConfiguration.yNRLevel = qBound(0.0, yNRLevel, 10.0);

    // For settings that both decoders share, the PAL default takes precedence
    ntscConfiguration.chromaGain = palConfiguration.chromaGain;
    ntscConfiguration.chromaPhase = palConfiguration.chromaPhase;

    // Select the tab corresponding to the current standard automatically
    if (system == NTSC) {
        ui->standardTabs->setCurrentWidget(ui->ntscTab);
    } else {
        ui->standardTabs->setCurrentWidget(ui->palTab);
    }
	
	isInit = _isInit;
    updateDialog();
    emit chromaDecoderConfigChanged();
}

const PalColour::Configuration &ChromaDecoderConfigDialog::getPalConfiguration()
{
    return palConfiguration;
}

const Comb::Configuration &ChromaDecoderConfigDialog::getNtscConfiguration()
{
    return ntscConfiguration;
}

const OutputWriter::Configuration &ChromaDecoderConfigDialog::getOutputConfiguration()
{
    return outputConfiguration;
}

void ChromaDecoderConfigDialog::updateDialog()
{
    const bool isSourcePal = system == PAL || system == PAL_M;
    const bool isSourceNtsc = system == NTSC;
	
	if(!isInit)
	{
		if(sourceMode == TbcSource::ONE_SOURCE)
		{
			palConfiguration.chromaFilter = PalColour::transform3DFilter;
			ntscConfiguration.dimensions = 3;
		}
		else
		{
			palConfiguration.chromaFilter = PalColour::transform2DFilter;
			ntscConfiguration.dimensions = 2;
		}
		ntscConfiguration.phaseCompensation = (tbcSource->getVideoParameters().tapeFormat != "");//enable phase compensation only for tape
		ui->enableYNRCheckBox->setChecked(yNREnabled);
		ui->enableYCCombineCheckBox->setChecked(combine);
		
		isInit = true;
	}

    // Shared settings

    ui->chromaGainHorizontalSlider->setValue(static_cast<qint32>(palConfiguration.chromaGain * 100));

    ui->chromaGainValueLabel->setEnabled(true);
    ui->chromaGainValueLabel->setText(QString::number(palConfiguration.chromaGain, 'f', 2));

    ui->chromaPhaseHorizontalSlider->setValue(static_cast<qint32>(degreesToSliderPos(palConfiguration.chromaPhase)));

    ui->chromaPhaseValueLabel->setEnabled(true);
    ui->chromaPhaseValueLabel->setText(QString::number(palConfiguration.chromaPhase, 'f', 1) + QChar(0xB0));
    
    ui->yNRHorizontalSlider->setValue(static_cast<qint32>(ynrLevel * 10));
    ui->yNRValueLabel->setText(QString::number(ynrLevel, 'f', 1) + tr(" IRE"));
	
	if(sourceMode == TbcSource::BOTH_SOURCES)
	{
		ui->enableYCCombineCheckBox->show();
	}
	else
	{
		ui->enableYCCombineCheckBox->hide();
	}

    // PAL settings
	
	ui->palMonoRadioButton->setEnabled(isSourcePal);
    ui->palFilterPalColourRadioButton->setEnabled(isSourcePal);
    ui->palFilterTransform2DRadioButton->setEnabled(isSourcePal);
    ui->palFilterTransform3DRadioButton->setEnabled(isSourcePal);
	
	if(isSourcePal)
	{
		switch (palConfiguration.chromaFilter) {
		case PalColour::mono:
			ui->palMonoRadioButton->setChecked(true);
			ui->chromaGainHorizontalSlider->setEnabled(false);
			ui->chromaPhaseHorizontalSlider->setEnabled(false);
			break;
		case PalColour::palColourFilter:
			ui->palFilterPalColourRadioButton->setChecked(true);
			ui->chromaGainHorizontalSlider->setEnabled(true);
			ui->chromaPhaseHorizontalSlider->setEnabled(true);
			break;
		case PalColour::transform2DFilter:
			ui->palFilterTransform2DRadioButton->setChecked(true);
			ui->chromaGainHorizontalSlider->setEnabled(true);
			ui->chromaPhaseHorizontalSlider->setEnabled(true);
			break;
		case PalColour::transform3DFilter:
			ui->palFilterTransform3DRadioButton->setChecked(true);
			ui->chromaGainHorizontalSlider->setEnabled(true);
			ui->chromaPhaseHorizontalSlider->setEnabled(true);
			break;
		}
	}

    const bool isTransform = ((palConfiguration.chromaFilter != PalColour::palColourFilter) && (palConfiguration.chromaFilter != PalColour::mono) );

    ui->thresholdLabel->setEnabled(isSourcePal && isTransform);

    ui->thresholdHorizontalSlider->setEnabled(isSourcePal && isTransform);
    ui->thresholdHorizontalSlider->setValue(static_cast<qint32>(palConfiguration.transformThreshold * 100));

    ui->thresholdValueLabel->setEnabled(isSourcePal && isTransform);
    ui->thresholdValueLabel->setText(QString::number(palConfiguration.transformThreshold, 'f', 2));

    ui->showFFTsCheckBox->setEnabled(isSourcePal && isTransform);
    ui->showFFTsCheckBox->setChecked(palConfiguration.showFFTs);

    ui->simplePALCheckBox->setEnabled(isSourcePal && isTransform);
    ui->simplePALCheckBox->setChecked(palConfiguration.simplePAL);

    // NTSC settings

    ui->phaseCompCheckBox->setEnabled(isSourceNtsc);
    ui->phaseCompCheckBox->setChecked(ntscConfiguration.phaseCompensation);
    ui->ntscMonoRadioButton->setEnabled(isSourceNtsc);
    ui->ntscFilter1DRadioButton->setEnabled(isSourceNtsc);
    ui->ntscFilter2DRadioButton->setEnabled(isSourceNtsc);
    ui->ntscFilter3DRadioButton->setEnabled(isSourceNtsc);
	
	if(isSourceNtsc)
	{
		switch (ntscConfiguration.dimensions) {
		case 0:
			ui->ntscMonoRadioButton->setChecked(true);
			ui->phaseCompCheckBox->setEnabled(false);
			ui->chromaGainHorizontalSlider->setEnabled(false);
			ui->chromaPhaseHorizontalSlider->setEnabled(false);
			break;
		case 1:
			ui->ntscFilter1DRadioButton->setChecked(true);
			ui->phaseCompCheckBox->setEnabled(true);
			ui->chromaGainHorizontalSlider->setEnabled(true);
			ui->chromaPhaseHorizontalSlider->setEnabled(true);
			break;
		case 2:
			ui->ntscFilter2DRadioButton->setChecked(true);
			ui->phaseCompCheckBox->setEnabled(true);
			ui->chromaGainHorizontalSlider->setEnabled(true);
			ui->chromaPhaseHorizontalSlider->setEnabled(true);
			break;
		case 3:
			ui->ntscFilter3DRadioButton->setChecked(true);
			ui->phaseCompCheckBox->setEnabled(true);
			ui->chromaGainHorizontalSlider->setEnabled(true);
			ui->chromaPhaseHorizontalSlider->setEnabled(true);
			break;
		}
    }

    ui->adaptiveCheckBox->setEnabled(isSourceNtsc && ntscConfiguration.dimensions == 3);
    ui->adaptiveCheckBox->setChecked(ntscConfiguration.adaptive);

    ui->showMapCheckBox->setEnabled(isSourceNtsc && ntscConfiguration.dimensions == 3);
    ui->showMapCheckBox->setChecked(ntscConfiguration.showMap);

    ui->cNRLabel->setEnabled(isSourceNtsc);

    ui->cNRHorizontalSlider->setEnabled(isSourceNtsc && ntscConfiguration.dimensions != 0);
    ui->cNRHorizontalSlider->setValue(static_cast<qint32>(ntscConfiguration.cNRLevel * 10));

    ui->cNRValueLabel->setEnabled(isSourceNtsc);
    ui->cNRValueLabel->setText(QString::number(ntscConfiguration.cNRLevel, 'f', 1) + tr(" IRE"));
}

// Methods to handle changes to the dialogue

void ChromaDecoderConfigDialog::on_chromaGainHorizontalSlider_valueChanged(int value)
{
    palConfiguration.chromaGain = static_cast<double>(value) / 100;
    ntscConfiguration.chromaGain = palConfiguration.chromaGain;
    ui->chromaGainValueLabel->setText(QString::number(palConfiguration.chromaGain, 'f', 2));
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_chromaPhaseHorizontalSlider_valueChanged(int value)
{
    palConfiguration.chromaPhase = sliderPosToDegrees(static_cast<double>(value));
    ntscConfiguration.chromaPhase = palConfiguration.chromaPhase;
    ui->chromaPhaseValueLabel->setText(QString::number(palConfiguration.chromaPhase, 'f', 1) + QChar(0xB0));
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_enableYNRCheckBox_clicked()
{
	yNREnabled = ui->enableYNRCheckBox->isChecked();
	ui->yNRHorizontalSlider->setEnabled(yNREnabled);
	
	if(ui->enableYNRCheckBox->isChecked())
	{
		palConfiguration.yNRLevel = ynrLevel;
		ntscConfiguration.yNRLevel = ynrLevel;
		monoConfiguration.yNRLevel = ynrLevel;
	}
	else
	{
		ynrLevel = monoConfiguration.yNRLevel;
		
		palConfiguration.yNRLevel = static_cast<double>(0);
		ntscConfiguration.yNRLevel = static_cast<double>(0);
		monoConfiguration.yNRLevel = static_cast<double>(0);
	}
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_palFilterButtonGroup_buttonClicked(QAbstractButton *button)
{
	if (button == ui->palMonoRadioButton){
		palConfiguration.chromaFilter = PalColour::mono;
    } else if (button == ui->palFilterPalColourRadioButton) {
        palConfiguration.chromaFilter = PalColour::palColourFilter;
    } else if (button == ui->palFilterTransform2DRadioButton) {
        palConfiguration.chromaFilter = PalColour::transform2DFilter;
    } else {
        palConfiguration.chromaFilter = PalColour::transform3DFilter;
    }
    updateDialog();
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_thresholdHorizontalSlider_valueChanged(int value)
{
    palConfiguration.transformThreshold = static_cast<double>(value) / 100;
    ui->thresholdValueLabel->setText(QString::number(palConfiguration.transformThreshold, 'f', 2));
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_showFFTsCheckBox_clicked()
{
    palConfiguration.showFFTs = ui->showFFTsCheckBox->isChecked();
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_simplePALCheckBox_clicked()
{
    palConfiguration.simplePAL = ui->simplePALCheckBox->isChecked();
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_ntscFilterButtonGroup_buttonClicked(QAbstractButton *button)
{
	if(button == ui->ntscMonoRadioButton){
		ntscConfiguration.dimensions = 0;
	} else if (button == ui->ntscFilter1DRadioButton) {
        ntscConfiguration.dimensions = 1;
    } else if (button == ui->ntscFilter2DRadioButton) {
        ntscConfiguration.dimensions = 2;
    } else {
        ntscConfiguration.dimensions = 3;
    }
    updateDialog();
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_phaseCompCheckBox_clicked()
{
    ntscConfiguration.phaseCompensation = ui->phaseCompCheckBox->isChecked();
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_adaptiveCheckBox_clicked()
{
    ntscConfiguration.adaptive = ui->adaptiveCheckBox->isChecked();
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_showMapCheckBox_clicked()
{
    ntscConfiguration.showMap = ui->showMapCheckBox->isChecked();
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_cNRHorizontalSlider_valueChanged(int value)
{
    ntscConfiguration.cNRLevel = static_cast<double>(value) / 10;
    ui->cNRValueLabel->setText(QString::number(ntscConfiguration.cNRLevel, 'f', 1) + tr(" IRE"));
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::on_yNRHorizontalSlider_valueChanged(int value)
{
    palConfiguration.yNRLevel = static_cast<double>(value) / 10;
    ntscConfiguration.yNRLevel = static_cast<double>(value) / 10;
	monoConfiguration.yNRLevel = static_cast<double>(value) / 10;
	ynrLevel = static_cast<double>(value) / 10;
    ui->yNRValueLabel->setText(QString::number(ntscConfiguration.yNRLevel, 'f', 1) + tr(" IRE"));
    emit chromaDecoderConfigChanged();
}

void ChromaDecoderConfigDialog::updateSourceMode(TbcSource::SourceMode mode)
{
	sourceMode = mode;
	if(sourceMode == TbcSource::BOTH_SOURCES)
	{
		ui->enableYCCombineCheckBox->show();
	}
	else
	{
		ui->enableYCCombineCheckBox->hide();
	}
}

void ChromaDecoderConfigDialog::on_enableYCCombineCheckBox_clicked()
{
	combine = ui->enableYCCombineCheckBox->isChecked();
	tbcSource->setCombine(combine);
	emit chromaDecoderConfigChanged();
}