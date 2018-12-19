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

void VbiDialog::updateVbi(LdDecodeMetaData::Field topField, LdDecodeMetaData::Field bottomField)
{
    qDebug() << "VbiDialog::updateVbi(): Called";

    if (!topField.vbi.inUse && !bottomField.vbi.inUse) {
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

    if (topField.vbi.type != LdDecodeMetaData::VbiDiscTypes::unknownDiscType) {
        if (topField.vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) ui->discTypeLabel->setText("CAV");
        if (topField.vbi.type == LdDecodeMetaData::VbiDiscTypes::clv) ui->discTypeLabel->setText("CLV");
    } else {
        if (bottomField.vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) ui->discTypeLabel->setText("CAV");
        if (bottomField.vbi.type == LdDecodeMetaData::VbiDiscTypes::clv) ui->discTypeLabel->setText("CLV");
        if (bottomField.vbi.type == LdDecodeMetaData::VbiDiscTypes::unknownDiscType) ui->discTypeLabel->setText("Unknown");
    }

    if (topField.vbi.leadIn || bottomField.vbi.leadIn) ui->leadInLabel->setText("Yes");
    else ui->leadInLabel->setText("No");

    if (topField.vbi.leadOut || bottomField.vbi.leadOut) ui->leadOutLabel->setText("Yes");
    else ui->leadOutLabel->setText("No");

    if (topField.vbi.userCode.isEmpty() && bottomField.vbi.userCode.isEmpty()) ui->userCodeLabel->setText("Not present");
    else {
        if (!topField.vbi.userCode.isEmpty()) ui->userCodeLabel->setText(topField.vbi.userCode);
        else ui->userCodeLabel->setText(bottomField.vbi.userCode);
    }

    if (topField.vbi.picNo != -1) ui->pictureNumberLabel->setText(QString::number(topField.vbi.picNo));
    else if (bottomField.vbi.picNo != -1) ui->pictureNumberLabel->setText(QString::number(bottomField.vbi.picNo));
    else ui->pictureNumberLabel->setText("Unknown");

    if (topField.vbi.picStop || bottomField.vbi.picStop) ui->pictureStopCodeLabel->setText("Yes");
    else ui->pictureStopCodeLabel->setText("No");

    if (topField.vbi.chNo != -1) ui->chapterNumberLabel->setText(QString::number(topField.vbi.chNo));
    if (bottomField.vbi.chNo != -1) ui->chapterNumberLabel->setText(QString::number(bottomField.vbi.chNo));
    else ui->chapterNumberLabel->setText("Unknown");

    if (topField.vbi.timeCode.hr != -1 && topField.vbi.timeCode.min != -1) {
        ui->clvTimeCodeLabel->setText(QString::number(topField.vbi.timeCode.hr) + ":" + QString::number(topField.vbi.timeCode.min));
    } else if (bottomField.vbi.timeCode.hr != -1 && bottomField.vbi.timeCode.min != -1) {
        ui->clvTimeCodeLabel->setText(QString::number(bottomField.vbi.timeCode.hr) + ":" + QString::number(bottomField.vbi.timeCode.min));
    } else ui->clvTimeCodeLabel->setText("Unknown");

    if (topField.vbi.clvPicNo.sec != -1 && topField.vbi.clvPicNo.picNo != -1) {
        ui->clvPictureNumberLabel->setText(QString::number(topField.vbi.clvPicNo.sec) + "." + QString::number(topField.vbi.clvPicNo.picNo));
    } else if (bottomField.vbi.clvPicNo.sec != -1 && bottomField.vbi.clvPicNo.picNo != -1) {
        ui->clvPictureNumberLabel->setText(QString::number(bottomField.vbi.clvPicNo.sec) + "." + QString::number(bottomField.vbi.clvPicNo.picNo));
    } else {
        ui->clvPictureNumberLabel->setText("Unknown");
    }

    // Display original programme status
    if (topField.vbi.statusCode.valid) {
        if (topField.vbi.statusCode.cx) ui->cxLabel->setText("On");
        else ui->cxLabel->setText("Off");

        if (topField.vbi.statusCode.size) ui->discSizeLabel->setText("12 inch disc");
        else ui->discSizeLabel->setText("8 inch disc");

        if (topField.vbi.statusCode.side) ui->discSideLabel->setText("Side 1");
        else ui->discSideLabel->setText("Side 2");

        if (topField.vbi.statusCode.teletext) ui->teletextLabel->setText("Present on disc");
        else ui->teletextLabel->setText("Not present on disc");

        if (topField.vbi.statusCode.dump) ui->programmeDumpLabel->setText("Yes");
        else ui->programmeDumpLabel->setText("No");

        if (topField.vbi.statusCode.fm) ui->fmFmMultiplexLabel->setText("Yes");
        else ui->fmFmMultiplexLabel->setText("No");

        if (topField.vbi.statusCode.digital) ui->digitalLabel->setText("Yes");
        else ui->digitalLabel->setText("No");

        if (topField.vbi.statusCode.parity) ui->parityCorrectLabel->setText("Yes");
        else ui->parityCorrectLabel->setText("No");

        if (topField.vbi.statusCode.soundMode ==  0) ui->soundModeLabel->setText("Stereo");
        if (topField.vbi.statusCode.soundMode ==  1) ui->soundModeLabel->setText("Mono");
        if (topField.vbi.statusCode.soundMode ==  2) ui->soundModeLabel->setText("Audio sub-carriers off");
        if (topField.vbi.statusCode.soundMode ==  3) ui->soundModeLabel->setText("Bilingual");
        if (topField.vbi.statusCode.soundMode ==  4) ui->soundModeLabel->setText("Stereo_Stereo");
        if (topField.vbi.statusCode.soundMode ==  5) ui->soundModeLabel->setText("Stereo_Bilingual");
        if (topField.vbi.statusCode.soundMode ==  6) ui->soundModeLabel->setText("Cross Channel Stereo");
        if (topField.vbi.statusCode.soundMode ==  7) ui->soundModeLabel->setText("Bilingual_Bilingual");
        if (topField.vbi.statusCode.soundMode ==  8) ui->soundModeLabel->setText("Mono dump");
        if (topField.vbi.statusCode.soundMode ==  9) ui->soundModeLabel->setText("Stereo dump");
        if (topField.vbi.statusCode.soundMode == 10) ui->soundModeLabel->setText("Bilingual dump");
        if (topField.vbi.statusCode.soundMode == 11) ui->soundModeLabel->setText("Future use/unknown");
    } else if (bottomField.vbi.statusCode.valid) {
        if (bottomField.vbi.statusCode.cx) ui->cxLabel->setText("On");
        else ui->cxLabel->setText("Off");

        if (bottomField.vbi.statusCode.size) ui->discSizeLabel->setText("12 inch disc");
        else ui->discSizeLabel->setText("8 inch disc");

        if (bottomField.vbi.statusCode.side) ui->discSideLabel->setText("Side 1");
        else ui->discSideLabel->setText("Side 2");

        if (bottomField.vbi.statusCode.teletext) ui->teletextLabel->setText("Present on disc");
        else ui->teletextLabel->setText("Not present on disc");

        if (bottomField.vbi.statusCode.dump) ui->programmeDumpLabel->setText("Yes");
        else ui->programmeDumpLabel->setText("No");

        if (bottomField.vbi.statusCode.fm) ui->fmFmMultiplexLabel->setText("Yes");
        else ui->fmFmMultiplexLabel->setText("No");

        if (bottomField.vbi.statusCode.digital) ui->digitalLabel->setText("Yes");
        else ui->digitalLabel->setText("No");

        if (bottomField.vbi.statusCode.parity) ui->parityCorrectLabel->setText("Yes");
        else ui->parityCorrectLabel->setText("No");

        if (bottomField.vbi.statusCode.soundMode ==  0) ui->soundModeLabel->setText("Stereo");
        if (bottomField.vbi.statusCode.soundMode ==  1) ui->soundModeLabel->setText("Mono");
        if (bottomField.vbi.statusCode.soundMode ==  2) ui->soundModeLabel->setText("Audio sub-carriers off");
        if (bottomField.vbi.statusCode.soundMode ==  3) ui->soundModeLabel->setText("Bilingual");
        if (bottomField.vbi.statusCode.soundMode ==  4) ui->soundModeLabel->setText("Stereo_Stereo");
        if (bottomField.vbi.statusCode.soundMode ==  5) ui->soundModeLabel->setText("Stereo_Bilingual");
        if (bottomField.vbi.statusCode.soundMode ==  6) ui->soundModeLabel->setText("Cross Channel Stereo");
        if (bottomField.vbi.statusCode.soundMode ==  7) ui->soundModeLabel->setText("Bilingual_Bilingual");
        if (bottomField.vbi.statusCode.soundMode ==  8) ui->soundModeLabel->setText("Mono dump");
        if (bottomField.vbi.statusCode.soundMode ==  9) ui->soundModeLabel->setText("Stereo dump");
        if (bottomField.vbi.statusCode.soundMode == 10) ui->soundModeLabel->setText("Bilingual dump");
        if (bottomField.vbi.statusCode.soundMode == 11) ui->soundModeLabel->setText("Future use/unknown");
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
    if (topField.vbi.statusCodeAm2.valid) {
        if (topField.vbi.statusCodeAm2.cx) ui->cxLabelAm2->setText("On");
        else ui->cxLabelAm2->setText("Off");

        if (topField.vbi.statusCodeAm2.size) ui->discSizeLabelAm2->setText("12 inch disc");
        else ui->discSizeLabelAm2->setText("8 inch disc");

        if (topField.vbi.statusCodeAm2.side) ui->discSideLabelAm2->setText("Side 1");
        else ui->discSideLabelAm2->setText("Side 2");

        if (topField.vbi.statusCodeAm2.teletext) ui->teletextLabelAm2->setText("Present on disc");
        else ui->teletextLabelAm2->setText("Not present on disc");

        if (topField.vbi.statusCodeAm2.copy) ui->copyAllowedLabelAm2->setText("Yes");
        else ui->copyAllowedLabelAm2->setText("No");

        if (topField.vbi.statusCodeAm2.standard) ui->standardVideoLabelAm2->setText("Yes");
        else ui->standardVideoLabelAm2->setText("No");

        if (topField.vbi.statusCodeAm2.soundMode ==  0) ui->soundModeLabelAm2->setText("Stereo");
        if (topField.vbi.statusCodeAm2.soundMode ==  1) ui->soundModeLabelAm2->setText("Mono");
        if (topField.vbi.statusCodeAm2.soundMode ==  2) ui->soundModeLabelAm2->setText("Audio sub-carriers off");
        if (topField.vbi.statusCodeAm2.soundMode ==  3) ui->soundModeLabelAm2->setText("Bilingual");
        if (topField.vbi.statusCodeAm2.soundMode ==  4) ui->soundModeLabelAm2->setText("Stereo_Stereo");
        if (topField.vbi.statusCodeAm2.soundMode ==  5) ui->soundModeLabelAm2->setText("Stereo_Bilingual");
        if (topField.vbi.statusCodeAm2.soundMode ==  6) ui->soundModeLabelAm2->setText("Cross Channel Stereo");
        if (topField.vbi.statusCodeAm2.soundMode ==  7) ui->soundModeLabelAm2->setText("Bilingual_Bilingual");
        if (topField.vbi.statusCodeAm2.soundMode ==  8) ui->soundModeLabelAm2->setText("Mono dump");
        if (topField.vbi.statusCodeAm2.soundMode ==  9) ui->soundModeLabelAm2->setText("Stereo dump");
        if (topField.vbi.statusCodeAm2.soundMode == 10) ui->soundModeLabelAm2->setText("Bilingual dump");
        if (topField.vbi.statusCodeAm2.soundMode == 11) ui->soundModeLabelAm2->setText("Future use/unknown");
    } else if (bottomField.vbi.statusCodeAm2.valid) {
        if (bottomField.vbi.statusCodeAm2.cx) ui->cxLabelAm2->setText("On");
        else ui->cxLabelAm2->setText("Off");

        if (bottomField.vbi.statusCodeAm2.size) ui->discSizeLabelAm2->setText("12 inch disc");
        else ui->discSizeLabelAm2->setText("8 inch disc");

        if (bottomField.vbi.statusCodeAm2.side) ui->discSideLabelAm2->setText("Side 1");
        else ui->discSideLabelAm2->setText("Side 2");

        if (bottomField.vbi.statusCodeAm2.teletext) ui->teletextLabelAm2->setText("Present on disc");
        else ui->teletextLabelAm2->setText("Not present on disc");

        if (bottomField.vbi.statusCodeAm2.copy) ui->copyAllowedLabelAm2->setText("Yes");
        else ui->copyAllowedLabelAm2->setText("No");

        if (bottomField.vbi.statusCodeAm2.standard) ui->standardVideoLabelAm2->setText("Yes");
        else ui->standardVideoLabelAm2->setText("No");

        if (bottomField.vbi.statusCodeAm2.soundMode ==  0) ui->soundModeLabelAm2->setText("Stereo");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  1) ui->soundModeLabelAm2->setText("Mono");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  2) ui->soundModeLabelAm2->setText("Audio sub-carriers off");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  3) ui->soundModeLabelAm2->setText("Bilingual");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  4) ui->soundModeLabelAm2->setText("Stereo_Stereo");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  5) ui->soundModeLabelAm2->setText("Stereo_Bilingual");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  6) ui->soundModeLabelAm2->setText("Cross Channel Stereo");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  7) ui->soundModeLabelAm2->setText("Bilingual_Bilingual");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  8) ui->soundModeLabelAm2->setText("Mono dump");
        if (bottomField.vbi.statusCodeAm2.soundMode ==  9) ui->soundModeLabelAm2->setText("Stereo dump");
        if (bottomField.vbi.statusCodeAm2.soundMode == 10) ui->soundModeLabelAm2->setText("Bilingual dump");
        if (bottomField.vbi.statusCodeAm2.soundMode == 11) ui->soundModeLabelAm2->setText("Future use/unknown");
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
