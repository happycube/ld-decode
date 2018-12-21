/************************************************************************

    ntscdialog.cpp

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

#include "ntscdialog.h"
#include "ui_ntscdialog.h"

NtscDialog::NtscDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::NtscDialog)
{
    ui->setupUi(this);
}

NtscDialog::~NtscDialog()
{
    delete ui;
}

void NtscDialog::updateNtsc(LdDecodeMetaData::Field topField, LdDecodeMetaData::Field bottomField)
{
    qDebug() << "NtscDialog::updateNtsc(): Called";

    if (!topField.ntsc.inUse && !bottomField.ntsc.inUse) {
        ui->fmCodeDataLabel->setText("Invalid");
        ui->fieldFlagLabel->setText("Invalid");
        ui->whiteFlagLabel->setText("Invalid");

        return;
    }

    QString fmCodeData;
    QString fieldFlag;
    QString whiteFlag;

    if (topField.ntsc.inUse) {
        if (topField.ntsc.isFmCodeDataValid) fmCodeData = QString::number(topField.ntsc.fmCodeData) + " / ";
        else fmCodeData = "None / ";

        if (topField.ntsc.fieldFlag) fieldFlag = "First field / ";
        else fieldFlag = "Second field / ";

        if (topField.ntsc.whiteFlag) whiteFlag = "White / ";
        else whiteFlag = "Black / ";
    }

    if (bottomField.ntsc.inUse) {
        if (bottomField.ntsc.isFmCodeDataValid) fmCodeData += QString::number(bottomField.ntsc.fmCodeData);
        else fmCodeData += "None";

        if (bottomField.ntsc.fieldFlag) fieldFlag += "First field";
        else fieldFlag += "Second field";

        if (bottomField.ntsc.whiteFlag) whiteFlag += "White";
        else whiteFlag += "Black";
    }

    // Update the labels
    ui->fmCodeDataLabel->setText(fmCodeData);
    ui->fieldFlagLabel->setText(fieldFlag);
    ui->whiteFlagLabel->setText(whiteFlag);
}
