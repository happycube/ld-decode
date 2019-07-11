/************************************************************************

    vbidialog.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-analyse is free software: you can redistribute it and/or
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

#include "vbidialog.h"
#include "ui_vbidialog.h"

VbiDialog::VbiDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::VbiDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);
}

VbiDialog::~VbiDialog()
{
    delete ui;
}

void VbiDialog::updateVbi(LdDecodeMetaData::Field firstField, LdDecodeMetaData::Field secondField)
{
    qDebug() << "VbiDialog::updateVbi(): Called";

    if (!firstField.vbi.inUse && !secondField.vbi.inUse) {
        // VBI data is not valid
        ui->discTypeLabel->setText("No metadata");
        ui->leadInLabel->setText("No metadata");
        ui->leadOutLabel->setText("No metadata");
        ui->userCodeLabel->setText("No metadata");
        ui->pictureNumberLabel->setText("No metadata");
        ui->pictureStopCodeLabel->setText("No metadata");
        ui->chapterNumberLabel->setText("No metadata");
        ui->clvTimeCodeLabel->setText("No metadata");

        ui->cxLabel->setText("No metadata");
        ui->discSizeLabel->setText("No metadata");
        ui->discSideLabel->setText("No metadata");
        ui->teletextLabel->setText("No metadata");
        ui->programmeDumpLabel->setText("No metadata");
        ui->fmFmMultiplexLabel->setText("No metadata");
        ui->digitalLabel->setText("No metadata");
        ui->parityCorrectLabel->setText("No metadata");
        ui->soundModeLabel->setText("No metadata");

        ui->cxLabelAm2->setText("No metadata");
        ui->discSizeLabelAm2->setText("No metadata");
        ui->discSideLabelAm2->setText("No metadata");
        ui->teletextLabelAm2->setText("No metadata");
        ui->copyAllowedLabelAm2->setText("No metadata");
        ui->standardVideoLabelAm2->setText("No metadata");
        ui->soundModeLabelAm2->setText("No metadata");

        return;
    }

    if (firstField.vbi.type != LdDecodeMetaData::VbiDiscTypes::unknownDiscType) {
        if (firstField.vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) ui->discTypeLabel->setText("CAV");
        if (firstField.vbi.type == LdDecodeMetaData::VbiDiscTypes::clv) ui->discTypeLabel->setText("CLV");
    } else {
        if (secondField.vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) ui->discTypeLabel->setText("CAV");
        if (secondField.vbi.type == LdDecodeMetaData::VbiDiscTypes::clv) ui->discTypeLabel->setText("CLV");
        if (secondField.vbi.type == LdDecodeMetaData::VbiDiscTypes::unknownDiscType) ui->discTypeLabel->setText("Unknown");
    }

    if (firstField.vbi.leadIn || secondField.vbi.leadIn) ui->leadInLabel->setText("Yes");
    else ui->leadInLabel->setText("No");

    if (firstField.vbi.leadOut || secondField.vbi.leadOut) ui->leadOutLabel->setText("Yes");
    else ui->leadOutLabel->setText("No");

    if (firstField.vbi.userCode.isEmpty() && secondField.vbi.userCode.isEmpty()) ui->userCodeLabel->setText("None");
    else {
        if (!firstField.vbi.userCode.isEmpty()) ui->userCodeLabel->setText(firstField.vbi.userCode);
        else ui->userCodeLabel->setText(secondField.vbi.userCode);
    }

    if (firstField.vbi.picNo != -1) ui->pictureNumberLabel->setText(QString::number(firstField.vbi.picNo));
    else if (secondField.vbi.picNo != -1) ui->pictureNumberLabel->setText(QString::number(secondField.vbi.picNo));
    else ui->pictureNumberLabel->setText("Unknown");

    if (firstField.vbi.picStop || secondField.vbi.picStop) ui->pictureStopCodeLabel->setText("Yes");
    else ui->pictureStopCodeLabel->setText("No");

    if (firstField.vbi.chNo != -1) ui->chapterNumberLabel->setText(QString::number(firstField.vbi.chNo));
    else if (secondField.vbi.chNo != -1) ui->chapterNumberLabel->setText(QString::number(secondField.vbi.chNo));
    else ui->chapterNumberLabel->setText("Unknown");

    QString clvTimecodeString;
    if (firstField.vbi.clvHr != -1 || firstField.vbi.clvMin != -1 || firstField.vbi.clvSec != -1 || firstField.vbi.clvPicNo != -1 ||
            secondField.vbi.clvHr != -1 || secondField.vbi.clvMin != -1 || secondField.vbi.clvSec != -1 || secondField.vbi.clvPicNo != -1 ) {
        if (firstField.vbi.clvHr != -1 && firstField.vbi.clvMin != -1) {
            clvTimecodeString = QString("%1").arg(firstField.vbi.clvHr, 2, 10, QChar('0')) + ":" + QString("%1").arg(firstField.vbi.clvMin, 2, 10, QChar('0')) + ":";
        } else if (secondField.vbi.clvHr != -1 && secondField.vbi.clvMin != -1) {
            clvTimecodeString = QString("%1").arg(secondField.vbi.clvHr, 2, 10, QChar('0')) + ":" + QString("%1").arg(secondField.vbi.clvMin, 2, 10, QChar('0')) + ":";
        } else clvTimecodeString = "xx:xx:";

        if (firstField.vbi.clvSec != -1 && firstField.vbi.clvPicNo != -1) {
            clvTimecodeString += QString("%1").arg(firstField.vbi.clvSec, 2, 10, QChar('0')) + "." + QString("%1").arg(firstField.vbi.clvPicNo, 2, 10, QChar('0'));
        } else if (secondField.vbi.clvSec != -1 && secondField.vbi.clvPicNo != -1) {
            clvTimecodeString += QString("%1").arg(secondField.vbi.clvSec, 2, 10, QChar('0')) + "." + QString("%1").arg(secondField.vbi.clvPicNo, 2, 10, QChar('0'));
        } else clvTimecodeString += "xx.xx";
    } else if (firstField.vbi.clvHr != -1 || firstField.vbi.clvMin != -1 || secondField.vbi.clvHr != -1 || secondField.vbi.clvMin != -1) {
        if (firstField.vbi.clvHr != -1 && firstField.vbi.clvMin != -1) {
            clvTimecodeString = QString("%1").arg(firstField.vbi.clvHr, 2, 10, QChar('0')) + ":" + QString("%1").arg(firstField.vbi.clvMin, 2, 10, QChar('0'));
        } else if (secondField.vbi.clvHr != -1 && secondField.vbi.clvMin != -1) {
            clvTimecodeString = QString("%1").arg(secondField.vbi.clvHr, 2, 10, QChar('0')) + ":" + QString("%1").arg(secondField.vbi.clvMin, 2, 10, QChar('0'));
        } else clvTimecodeString = "xx:xx";
    } else clvTimecodeString = "Unknown";
    ui->clvTimeCodeLabel->setText(clvTimecodeString);

    // Display original programme status
    if (firstField.vbi.cx || secondField.vbi.cx) ui->cxLabel->setText("On");
    else ui->cxLabel->setText("Off");

    if (firstField.vbi.size || secondField.vbi.size) ui->discSizeLabel->setText("12 inch disc");
    else ui->discSizeLabel->setText("8 inch disc");

    if (firstField.vbi.side || secondField.vbi.side) ui->discSideLabel->setText("Side 1");
    else ui->discSideLabel->setText("Side 2");

    if (firstField.vbi.teletext || secondField.vbi.teletext) ui->teletextLabel->setText("Present on disc");
    else ui->teletextLabel->setText("Not present on disc");

    if (firstField.vbi.dump || secondField.vbi.dump) ui->programmeDumpLabel->setText("Yes");
    else ui->programmeDumpLabel->setText("No");

    if (firstField.vbi.fm || secondField.vbi.fm) ui->fmFmMultiplexLabel->setText("Yes");
    else ui->fmFmMultiplexLabel->setText("No");

    if (firstField.vbi.digital || secondField.vbi.digital) ui->digitalLabel->setText("Yes");
    else ui->digitalLabel->setText("No");

    if (firstField.vbi.parity || secondField.vbi.parity) ui->parityCorrectLabel->setText("Yes");
    else ui->parityCorrectLabel->setText("No");

    if ((firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::futureUse) && (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::futureUse)) {
        ui->soundModeLabel->setText("Future use/unknown");
    } else if (firstField.vbi.soundMode != LdDecodeMetaData::VbiSoundModes::futureUse) {
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo) ui->soundModeLabel->setText("Stereo");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::mono) ui->soundModeLabel->setText("Mono");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff) ui->soundModeLabel->setText("Audio sub-carriers off");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::bilingual) ui->soundModeLabel->setText("Bilingual");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo_stereo) ui->soundModeLabel->setText("Stereo_Stereo");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo_bilingual) ui->soundModeLabel->setText("Stereo_Bilingual");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::crossChannelStereo) ui->soundModeLabel->setText("Cross Channel Stereo");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::bilingual_bilingual) ui->soundModeLabel->setText("Bilingual_Bilingual");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::mono_dump) ui->soundModeLabel->setText("Mono dump");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo_dump) ui->soundModeLabel->setText("Stereo dump");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::bilingual_dump) ui->soundModeLabel->setText("Bilingual dump");
        if (firstField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::futureUse) ui->soundModeLabel->setText("Future use/unknown");
    } else {
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo) ui->soundModeLabel->setText("Stereo");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::mono) ui->soundModeLabel->setText("Mono");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff) ui->soundModeLabel->setText("Audio sub-carriers off");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::bilingual) ui->soundModeLabel->setText("Bilingual");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo_stereo) ui->soundModeLabel->setText("Stereo_Stereo");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo_bilingual) ui->soundModeLabel->setText("Stereo_Bilingual");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::crossChannelStereo) ui->soundModeLabel->setText("Cross Channel Stereo");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::bilingual_bilingual) ui->soundModeLabel->setText("Bilingual_Bilingual");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::mono_dump) ui->soundModeLabel->setText("Mono dump");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::stereo_dump) ui->soundModeLabel->setText("Stereo dump");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::bilingual_dump) ui->soundModeLabel->setText("Bilingual dump");
        if (secondField.vbi.soundMode == LdDecodeMetaData::VbiSoundModes::futureUse) ui->soundModeLabel->setText("Future use/unknown");
    }

    // Display programme status amendment 2
    if (firstField.vbi.cx || secondField.vbi.cx) ui->cxLabelAm2->setText("On");
    else ui->cxLabelAm2->setText("Off");

    if (firstField.vbi.size || secondField.vbi.size) ui->discSizeLabelAm2->setText("12 inch disc");
    else ui->discSizeLabelAm2->setText("8 inch disc");

    if (firstField.vbi.side || secondField.vbi.side) ui->discSideLabelAm2->setText("Side 1");
    else ui->discSideLabelAm2->setText("Side 2");

    if (firstField.vbi.teletext || secondField.vbi.teletext) ui->teletextLabelAm2->setText("Present on disc");
    else ui->teletextLabelAm2->setText("Not present on disc");

    if ((firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::futureUse) && (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::futureUse)) {
        ui->soundModeLabelAm2->setText("Future use/unknown");
    } else if (firstField.vbi.soundModeAm2 != LdDecodeMetaData::VbiSoundModes::futureUse) {
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo) ui->soundModeLabelAm2->setText("Stereo");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::mono) ui->soundModeLabelAm2->setText("Mono");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff) ui->soundModeLabelAm2->setText("Audio sub-carriers off");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::bilingual) ui->soundModeLabelAm2->setText("Bilingual");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo_stereo) ui->soundModeLabelAm2->setText("Stereo_Stereo");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo_bilingual) ui->soundModeLabelAm2->setText("Stereo_Bilingual");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::crossChannelStereo) ui->soundModeLabelAm2->setText("Cross Channel Stereo");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::bilingual_bilingual) ui->soundModeLabelAm2->setText("Bilingual_Bilingual");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::mono_dump) ui->soundModeLabelAm2->setText("Mono dump");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo_dump) ui->soundModeLabelAm2->setText("Stereo dump");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::bilingual_dump) ui->soundModeLabelAm2->setText("Bilingual dump");
        if (firstField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::futureUse) ui->soundModeLabelAm2->setText("Future use/unknown");
    } else {
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo) ui->soundModeLabelAm2->setText("Stereo");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::mono) ui->soundModeLabelAm2->setText("Mono");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff) ui->soundModeLabelAm2->setText("Audio sub-carriers off");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::bilingual) ui->soundModeLabelAm2->setText("Bilingual");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo_stereo) ui->soundModeLabelAm2->setText("Stereo_Stereo");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo_bilingual) ui->soundModeLabelAm2->setText("Stereo_Bilingual");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::crossChannelStereo) ui->soundModeLabelAm2->setText("Cross Channel Stereo");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::bilingual_bilingual) ui->soundModeLabelAm2->setText("Bilingual_Bilingual");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::mono_dump) ui->soundModeLabelAm2->setText("Mono dump");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::stereo_dump) ui->soundModeLabelAm2->setText("Stereo dump");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::bilingual_dump) ui->soundModeLabelAm2->setText("Bilingual dump");
        if (secondField.vbi.soundModeAm2 == LdDecodeMetaData::VbiSoundModes::futureUse) ui->soundModeLabelAm2->setText("Future use/unknown");
    }

    if (firstField.vbi.copyAm2 || secondField.vbi.copyAm2) ui->copyAllowedLabelAm2->setText("Yes");
    else ui->copyAllowedLabelAm2->setText("No");

    if (firstField.vbi.standardAm2 || secondField.vbi.standardAm2) ui->standardVideoLabelAm2->setText("Yes");
    else ui->standardVideoLabelAm2->setText("No");

}
