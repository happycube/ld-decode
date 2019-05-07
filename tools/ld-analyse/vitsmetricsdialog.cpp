/************************************************************************

    vitsmetricsdialog.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
    modify it under the terms of the GNU General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

************************************************************************/

#include "vitsmetricsdialog.h"
#include "ui_vitsmetricsdialog.h"

VitsMetricsDialog::VitsMetricsDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::VitsMetricsDialog)
{
    ui->setupUi(this);
}

VitsMetricsDialog::~VitsMetricsDialog()
{
    delete ui;
}

void VitsMetricsDialog::updateVitsMetrics(LdDecodeMetaData::Field firstField, LdDecodeMetaData::Field secondField)
{
    qDebug() << "VitsMetricsDialog::updateVitsMetrics(): Called";

    if (firstField.vitsMetrics.inUse || secondField.vitsMetrics.inUse) {
        if (firstField.vitsMetrics.whiteSNR > 0) ui->whiteSNRLabel->setText(QString::number(firstField.vitsMetrics.whiteSNR));
        else ui->whiteSNRLabel->setText(QString::number(secondField.vitsMetrics.whiteSNR));

        if (firstField.vitsMetrics.whiteIRE > 0) ui->whiteIRELabel->setText(QString::number(firstField.vitsMetrics.whiteIRE));
        else ui->whiteIRELabel->setText(QString::number(secondField.vitsMetrics.whiteIRE));

        if (firstField.vitsMetrics.whiteRFLevel > 0) ui->whiteRFLevelLabel->setText(QString::number(firstField.vitsMetrics.whiteRFLevel));
        else ui->whiteRFLevelLabel->setText(QString::number(secondField.vitsMetrics.whiteRFLevel));

        if (firstField.vitsMetrics.greyPSNR > 0) ui->greyPSNRLabel->setText(QString::number(firstField.vitsMetrics.greyPSNR));
        else ui->greyPSNRLabel->setText(QString::number(secondField.vitsMetrics.greyPSNR));

        if (firstField.vitsMetrics.greyIRE > 0) ui->greyIRELabel->setText(QString::number(firstField.vitsMetrics.greyIRE));
        else ui->greyIRELabel->setText(QString::number(secondField.vitsMetrics.greyIRE));

        if (firstField.vitsMetrics.greyRFLevel > 0) ui->greyRFLevelLabel->setText(QString::number(firstField.vitsMetrics.greyRFLevel));
        else ui->greyRFLevelLabel->setText(QString::number(secondField.vitsMetrics.greyRFLevel));

        if (firstField.vitsMetrics.blackLinePreTBCIRE > 0) ui->blackLinePreTBCIRELabel->setText(QString::number(firstField.vitsMetrics.blackLinePreTBCIRE));
        else ui->blackLinePreTBCIRELabel->setText(QString::number(secondField.vitsMetrics.blackLinePreTBCIRE));

        if (firstField.vitsMetrics.blackLinePostTBCIRE > 0) ui->blackLinePostTBCIRELabel->setText(QString::number(firstField.vitsMetrics.blackLinePostTBCIRE));
        else ui->blackLinePostTBCIRELabel->setText(QString::number(secondField.vitsMetrics.blackLinePostTBCIRE));

        if (firstField.vitsMetrics.blackLinePSNR > 0) ui->blackLinePSNRLabel->setText(QString::number(firstField.vitsMetrics.blackLinePSNR));
        else ui->blackLinePSNRLabel->setText(QString::number(secondField.vitsMetrics.blackLinePSNR));

        if (firstField.vitsMetrics.blackLineRFLevel > 0) ui->blackLineRFLevelLabel->setText(QString::number(firstField.vitsMetrics.blackLineRFLevel));
        else ui->blackLineRFLevelLabel->setText(QString::number(secondField.vitsMetrics.blackLineRFLevel));

        if (firstField.vitsMetrics.syncLevelPSNR > 0) ui->syncLevelPSNRLabel->setText(QString::number(firstField.vitsMetrics.syncLevelPSNR));
        else ui->syncLevelPSNRLabel->setText(QString::number(secondField.vitsMetrics.syncLevelPSNR));

        if (firstField.vitsMetrics.syncRFLevel > 0) ui->syncRFLevelLabel->setText(QString::number(firstField.vitsMetrics.syncRFLevel));
        else ui->syncRFLevelLabel->setText(QString::number(secondField.vitsMetrics.syncRFLevel));

        if (firstField.vitsMetrics.syncToBlackRFRatio > 0) ui->syncToBlackRFRatioLabel->setText(QString::number(firstField.vitsMetrics.syncToBlackRFRatio));
        else ui->syncToBlackRFRatioLabel->setText(QString::number(secondField.vitsMetrics.syncToBlackRFRatio));

        if (firstField.vitsMetrics.syncToWhiteRFRatio > 0) ui->syncToWhiteRFRatioLabel->setText(QString::number(firstField.vitsMetrics.syncToWhiteRFRatio));
        else ui->syncToWhiteRFRatioLabel->setText(QString::number(secondField.vitsMetrics.syncToWhiteRFRatio));

        if (firstField.vitsMetrics.blackToWhiteRFRatio > 0) ui->blackToWhiteRFRatioLabel->setText(QString::number(firstField.vitsMetrics.blackToWhiteRFRatio));
        else ui->blackToWhiteRFRatioLabel->setText(QString::number(secondField.vitsMetrics.blackToWhiteRFRatio));

        if (firstField.vitsMetrics.ntscWhiteFlagSNR > 0) ui->ntscWhiteFlagSNRLabel->setText(QString::number(firstField.vitsMetrics.ntscWhiteFlagSNR));
        else ui->ntscWhiteFlagSNRLabel->setText(QString::number(secondField.vitsMetrics.ntscWhiteFlagSNR));

        if (firstField.vitsMetrics.ntscWhiteFlagRFLevel > 0) ui->ntscWhiteFlagRFLevelLabel->setText(QString::number(firstField.vitsMetrics.ntscWhiteFlagRFLevel));
        else ui->ntscWhiteFlagRFLevelLabel->setText(QString::number(secondField.vitsMetrics.ntscWhiteFlagRFLevel));

        if (firstField.vitsMetrics.ntscLine19Burst0IRE > 0) ui->ntscLine19Burst0IRELabel->setText(QString::number(firstField.vitsMetrics.ntscLine19Burst0IRE));
        else ui->ntscLine19Burst0IRELabel->setText(QString::number(secondField.vitsMetrics.ntscLine19Burst0IRE));

        if (firstField.vitsMetrics.ntscLine19Burst70IRE > 0) ui->ntscLine19Burst70IRELabel->setText(QString::number(firstField.vitsMetrics.ntscLine19Burst70IRE));
        else ui->ntscLine19Burst70IRELabel->setText(QString::number(secondField.vitsMetrics.ntscLine19Burst70IRE));

        if (firstField.vitsMetrics.ntscLine19ColorPhase > 0) ui->ntscLine19ColorPhaseLabel->setText(QString::number(firstField.vitsMetrics.ntscLine19ColorPhase));
        else ui->ntscLine19ColorPhaseLabel->setText(QString::number(secondField.vitsMetrics.ntscLine19ColorPhase));

        if (firstField.vitsMetrics.ntscLine19ColorRawSNR > 0) ui->ntscLine19ColorRawSNRLabel->setText(QString::number(firstField.vitsMetrics.ntscLine19ColorRawSNR));
        else ui->ntscLine19ColorRawSNRLabel->setText(QString::number(secondField.vitsMetrics.ntscLine19ColorRawSNR));

        if (firstField.vitsMetrics.ntscLine19Color3DPhase > 0) ui->ntscLine19Color3DPhaseLabel->setText(QString::number(firstField.vitsMetrics.ntscLine19Color3DPhase));
        else ui->ntscLine19Color3DPhaseLabel->setText(QString::number(secondField.vitsMetrics.ntscLine19Color3DPhase));

        if (firstField.vitsMetrics.ntscLine19Color3DRawSNR > 0) ui->ntscLine19Color3DRawSNRLabel->setText(QString::number(firstField.vitsMetrics.ntscLine19Color3DRawSNR));
        else ui->ntscLine19Color3DRawSNRLabel->setText(QString::number(secondField.vitsMetrics.ntscLine19Color3DRawSNR));

        if (firstField.vitsMetrics.palVITSBurst50Level > 0) ui->palVITSBurst50LevelLabel->setText(QString::number(firstField.vitsMetrics.palVITSBurst50Level));
        else ui->palVITSBurst50LevelLabel->setText(QString::number(secondField.vitsMetrics.palVITSBurst50Level));
    }
}
