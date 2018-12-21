/************************************************************************

    vbidialog.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018 Simon Inns

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

#include "vbidialog.h"
#include "ui_vbidialog.h"

VbiDialog::VbiDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::VbiDialog)
{
    ui->setupUi(this);
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
        ui->discTypeLabel->setText("Invalid");
        ui->leadInLabel->setText("Invalid");
        ui->leadOutLabel->setText("Invalid");
        ui->userCodeLabel->setText("Invalid");
        ui->pictureNumberLabel->setText("Invalid");
        ui->pictureStopCodeLabel->setText("Invalid");
        ui->chapterNumberLabel->setText("Invalid");
        ui->clvTimeCodeLabel->setText("Invalid");
        ui->clvPictureNumberLabel->setText("Invalid");

        ui->cxLabel->setText("Invalid");
        ui->discSizeLabel->setText("Invalid");
        ui->discSideLabel->setText("Invalid");
        ui->teletextLabel->setText("Invalid");
        ui->programmeDumpLabel->setText("Invalid");
        ui->fmFmMultiplexLabel->setText("Invalid");
        ui->digitalLabel->setText("Invalid");
        ui->parityCorrectLabel->setText("Invalid");
        ui->soundModeLabel->setText("Invalid");

        ui->cxLabelAm2->setText("Invalid");
        ui->discSizeLabelAm2->setText("Invalid");
        ui->discSideLabelAm2->setText("Invalid");
        ui->teletextLabelAm2->setText("Invalid");
        ui->copyAllowedLabelAm2->setText("Invalid");
        ui->standardVideoLabelAm2->setText("Invalid");
        ui->soundModeLabelAm2->setText("Invalid");

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

    if (firstField.vbi.userCode.isEmpty() && secondField.vbi.userCode.isEmpty()) ui->userCodeLabel->setText("Not present");
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
    if (secondField.vbi.chNo != -1) ui->chapterNumberLabel->setText(QString::number(secondField.vbi.chNo));
    else ui->chapterNumberLabel->setText("Unknown");

    if (firstField.vbi.timeCode.hr != -1 && firstField.vbi.timeCode.min != -1) {
        ui->clvTimeCodeLabel->setText(QString::number(firstField.vbi.timeCode.hr) + ":" + QString::number(firstField.vbi.timeCode.min));
    } else if (secondField.vbi.timeCode.hr != -1 && secondField.vbi.timeCode.min != -1) {
        ui->clvTimeCodeLabel->setText(QString::number(secondField.vbi.timeCode.hr) + ":" + QString::number(secondField.vbi.timeCode.min));
    } else ui->clvTimeCodeLabel->setText("Unknown");

    if (firstField.vbi.clvPicNo.sec != -1 && firstField.vbi.clvPicNo.picNo != -1) {
        ui->clvPictureNumberLabel->setText(QString::number(firstField.vbi.clvPicNo.sec) + "." + QString::number(firstField.vbi.clvPicNo.picNo));
    } else if (secondField.vbi.clvPicNo.sec != -1 && secondField.vbi.clvPicNo.picNo != -1) {
        ui->clvPictureNumberLabel->setText(QString::number(secondField.vbi.clvPicNo.sec) + "." + QString::number(secondField.vbi.clvPicNo.picNo));
    } else {
        ui->clvPictureNumberLabel->setText("Unknown");
    }

    // Display original programme status
    if (firstField.vbi.statusCode.valid) {
        if (firstField.vbi.statusCode.cx) ui->cxLabel->setText("On");
        else ui->cxLabel->setText("Off");

        if (firstField.vbi.statusCode.size) ui->discSizeLabel->setText("12 inch disc");
        else ui->discSizeLabel->setText("8 inch disc");

        if (firstField.vbi.statusCode.side) ui->discSideLabel->setText("Side 1");
        else ui->discSideLabel->setText("Side 2");

        if (firstField.vbi.statusCode.teletext) ui->teletextLabel->setText("Present on disc");
        else ui->teletextLabel->setText("Not present on disc");

        if (firstField.vbi.statusCode.dump) ui->programmeDumpLabel->setText("Yes");
        else ui->programmeDumpLabel->setText("No");

        if (firstField.vbi.statusCode.fm) ui->fmFmMultiplexLabel->setText("Yes");
        else ui->fmFmMultiplexLabel->setText("No");

        if (firstField.vbi.statusCode.digital) ui->digitalLabel->setText("Yes");
        else ui->digitalLabel->setText("No");

        if (firstField.vbi.statusCode.parity) ui->parityCorrectLabel->setText("Yes");
        else ui->parityCorrectLabel->setText("No");

        if (firstField.vbi.statusCode.soundMode ==  0) ui->soundModeLabel->setText("Stereo");
        if (firstField.vbi.statusCode.soundMode ==  1) ui->soundModeLabel->setText("Mono");
        if (firstField.vbi.statusCode.soundMode ==  2) ui->soundModeLabel->setText("Audio sub-carriers off");
        if (firstField.vbi.statusCode.soundMode ==  3) ui->soundModeLabel->setText("Bilingual");
        if (firstField.vbi.statusCode.soundMode ==  4) ui->soundModeLabel->setText("Stereo_Stereo");
        if (firstField.vbi.statusCode.soundMode ==  5) ui->soundModeLabel->setText("Stereo_Bilingual");
        if (firstField.vbi.statusCode.soundMode ==  6) ui->soundModeLabel->setText("Cross Channel Stereo");
        if (firstField.vbi.statusCode.soundMode ==  7) ui->soundModeLabel->setText("Bilingual_Bilingual");
        if (firstField.vbi.statusCode.soundMode ==  8) ui->soundModeLabel->setText("Mono dump");
        if (firstField.vbi.statusCode.soundMode ==  9) ui->soundModeLabel->setText("Stereo dump");
        if (firstField.vbi.statusCode.soundMode == 10) ui->soundModeLabel->setText("Bilingual dump");
        if (firstField.vbi.statusCode.soundMode == 11) ui->soundModeLabel->setText("Future use/unknown");
    } else if (secondField.vbi.statusCode.valid) {
        if (secondField.vbi.statusCode.cx) ui->cxLabel->setText("On");
        else ui->cxLabel->setText("Off");

        if (secondField.vbi.statusCode.size) ui->discSizeLabel->setText("12 inch disc");
        else ui->discSizeLabel->setText("8 inch disc");

        if (secondField.vbi.statusCode.side) ui->discSideLabel->setText("Side 1");
        else ui->discSideLabel->setText("Side 2");

        if (secondField.vbi.statusCode.teletext) ui->teletextLabel->setText("Present on disc");
        else ui->teletextLabel->setText("Not present on disc");

        if (secondField.vbi.statusCode.dump) ui->programmeDumpLabel->setText("Yes");
        else ui->programmeDumpLabel->setText("No");

        if (secondField.vbi.statusCode.fm) ui->fmFmMultiplexLabel->setText("Yes");
        else ui->fmFmMultiplexLabel->setText("No");

        if (secondField.vbi.statusCode.digital) ui->digitalLabel->setText("Yes");
        else ui->digitalLabel->setText("No");

        if (secondField.vbi.statusCode.parity) ui->parityCorrectLabel->setText("Yes");
        else ui->parityCorrectLabel->setText("No");

        if (secondField.vbi.statusCode.soundMode ==  0) ui->soundModeLabel->setText("Stereo");
        if (secondField.vbi.statusCode.soundMode ==  1) ui->soundModeLabel->setText("Mono");
        if (secondField.vbi.statusCode.soundMode ==  2) ui->soundModeLabel->setText("Audio sub-carriers off");
        if (secondField.vbi.statusCode.soundMode ==  3) ui->soundModeLabel->setText("Bilingual");
        if (secondField.vbi.statusCode.soundMode ==  4) ui->soundModeLabel->setText("Stereo_Stereo");
        if (secondField.vbi.statusCode.soundMode ==  5) ui->soundModeLabel->setText("Stereo_Bilingual");
        if (secondField.vbi.statusCode.soundMode ==  6) ui->soundModeLabel->setText("Cross Channel Stereo");
        if (secondField.vbi.statusCode.soundMode ==  7) ui->soundModeLabel->setText("Bilingual_Bilingual");
        if (secondField.vbi.statusCode.soundMode ==  8) ui->soundModeLabel->setText("Mono dump");
        if (secondField.vbi.statusCode.soundMode ==  9) ui->soundModeLabel->setText("Stereo dump");
        if (secondField.vbi.statusCode.soundMode == 10) ui->soundModeLabel->setText("Bilingual dump");
        if (secondField.vbi.statusCode.soundMode == 11) ui->soundModeLabel->setText("Future use/unknown");
    } else {
        ui->cxLabel->setText("Invalid");
        ui->discSizeLabel->setText("Invalid");
        ui->discSideLabel->setText("Invalid");
        ui->teletextLabel->setText("Invalid");
        ui->programmeDumpLabel->setText("Invalid");
        ui->fmFmMultiplexLabel->setText("Invalid");
        ui->digitalLabel->setText("Invalid");
        ui->parityCorrectLabel->setText("Invalid");
        ui->soundModeLabel->setText("Invalid");
    }

    // Display programme status amendment 2
    if (firstField.vbi.statusCodeAm2.valid) {
        if (firstField.vbi.statusCodeAm2.cx) ui->cxLabelAm2->setText("On");
        else ui->cxLabelAm2->setText("Off");

        if (firstField.vbi.statusCodeAm2.size) ui->discSizeLabelAm2->setText("12 inch disc");
        else ui->discSizeLabelAm2->setText("8 inch disc");

        if (firstField.vbi.statusCodeAm2.side) ui->discSideLabelAm2->setText("Side 1");
        else ui->discSideLabelAm2->setText("Side 2");

        if (firstField.vbi.statusCodeAm2.teletext) ui->teletextLabelAm2->setText("Present on disc");
        else ui->teletextLabelAm2->setText("Not present on disc");

        if (firstField.vbi.statusCodeAm2.copy) ui->copyAllowedLabelAm2->setText("Yes");
        else ui->copyAllowedLabelAm2->setText("No");

        if (firstField.vbi.statusCodeAm2.standard) ui->standardVideoLabelAm2->setText("Yes");
        else ui->standardVideoLabelAm2->setText("No");

        if (firstField.vbi.statusCodeAm2.soundMode ==  0) ui->soundModeLabelAm2->setText("Stereo");
        if (firstField.vbi.statusCodeAm2.soundMode ==  1) ui->soundModeLabelAm2->setText("Mono");
        if (firstField.vbi.statusCodeAm2.soundMode ==  2) ui->soundModeLabelAm2->setText("Audio sub-carriers off");
        if (firstField.vbi.statusCodeAm2.soundMode ==  3) ui->soundModeLabelAm2->setText("Bilingual");
        if (firstField.vbi.statusCodeAm2.soundMode ==  4) ui->soundModeLabelAm2->setText("Stereo_Stereo");
        if (firstField.vbi.statusCodeAm2.soundMode ==  5) ui->soundModeLabelAm2->setText("Stereo_Bilingual");
        if (firstField.vbi.statusCodeAm2.soundMode ==  6) ui->soundModeLabelAm2->setText("Cross Channel Stereo");
        if (firstField.vbi.statusCodeAm2.soundMode ==  7) ui->soundModeLabelAm2->setText("Bilingual_Bilingual");
        if (firstField.vbi.statusCodeAm2.soundMode ==  8) ui->soundModeLabelAm2->setText("Mono dump");
        if (firstField.vbi.statusCodeAm2.soundMode ==  9) ui->soundModeLabelAm2->setText("Stereo dump");
        if (firstField.vbi.statusCodeAm2.soundMode == 10) ui->soundModeLabelAm2->setText("Bilingual dump");
        if (firstField.vbi.statusCodeAm2.soundMode == 11) ui->soundModeLabelAm2->setText("Future use/unknown");
    } else if (secondField.vbi.statusCodeAm2.valid) {
        if (secondField.vbi.statusCodeAm2.cx) ui->cxLabelAm2->setText("On");
        else ui->cxLabelAm2->setText("Off");

        if (secondField.vbi.statusCodeAm2.size) ui->discSizeLabelAm2->setText("12 inch disc");
        else ui->discSizeLabelAm2->setText("8 inch disc");

        if (secondField.vbi.statusCodeAm2.side) ui->discSideLabelAm2->setText("Side 1");
        else ui->discSideLabelAm2->setText("Side 2");

        if (secondField.vbi.statusCodeAm2.teletext) ui->teletextLabelAm2->setText("Present on disc");
        else ui->teletextLabelAm2->setText("Not present on disc");

        if (secondField.vbi.statusCodeAm2.copy) ui->copyAllowedLabelAm2->setText("Yes");
        else ui->copyAllowedLabelAm2->setText("No");

        if (secondField.vbi.statusCodeAm2.standard) ui->standardVideoLabelAm2->setText("Yes");
        else ui->standardVideoLabelAm2->setText("No");

        if (secondField.vbi.statusCodeAm2.soundMode ==  0) ui->soundModeLabelAm2->setText("Stereo");
        if (secondField.vbi.statusCodeAm2.soundMode ==  1) ui->soundModeLabelAm2->setText("Mono");
        if (secondField.vbi.statusCodeAm2.soundMode ==  2) ui->soundModeLabelAm2->setText("Audio sub-carriers off");
        if (secondField.vbi.statusCodeAm2.soundMode ==  3) ui->soundModeLabelAm2->setText("Bilingual");
        if (secondField.vbi.statusCodeAm2.soundMode ==  4) ui->soundModeLabelAm2->setText("Stereo_Stereo");
        if (secondField.vbi.statusCodeAm2.soundMode ==  5) ui->soundModeLabelAm2->setText("Stereo_Bilingual");
        if (secondField.vbi.statusCodeAm2.soundMode ==  6) ui->soundModeLabelAm2->setText("Cross Channel Stereo");
        if (secondField.vbi.statusCodeAm2.soundMode ==  7) ui->soundModeLabelAm2->setText("Bilingual_Bilingual");
        if (secondField.vbi.statusCodeAm2.soundMode ==  8) ui->soundModeLabelAm2->setText("Mono dump");
        if (secondField.vbi.statusCodeAm2.soundMode ==  9) ui->soundModeLabelAm2->setText("Stereo dump");
        if (secondField.vbi.statusCodeAm2.soundMode == 10) ui->soundModeLabelAm2->setText("Bilingual dump");
        if (secondField.vbi.statusCodeAm2.soundMode == 11) ui->soundModeLabelAm2->setText("Future use/unknown");
    } else {
        ui->cxLabelAm2->setText("Invalid");
        ui->discSizeLabelAm2->setText("Invalid");
        ui->discSideLabelAm2->setText("Invalid");
        ui->teletextLabelAm2->setText("Invalid");
        ui->copyAllowedLabelAm2->setText("Invalid");
        ui->standardVideoLabelAm2->setText("Invalid");
        ui->soundModeLabelAm2->setText("Invalid");
    }
}
