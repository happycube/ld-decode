/************************************************************************

    videometadatadialog.cpp

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

#include "videometadatadialog.h"
#include "ui_videometadatadialog.h"

VideoMetadataDialog::VideoMetadataDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::videoMetadataDialog)
{
    ui->setupUi(this);
}

VideoMetadataDialog::~VideoMetadataDialog()
{
    delete ui;
}

void VideoMetadataDialog::updateMetaData(LdDecodeMetaData::VideoParameters videoParameters)
{
    ui->numberOfSequentialFieldsLabel->setText(QString::number(videoParameters.numberOfSequentialFields));
    if (videoParameters.isSourcePal) ui->isSourcePalLabel->setText("True");
    else ui->isSourcePalLabel->setText("False");
    ui->white16IreLabel->setText(QString::number(videoParameters.white16bIre));
    ui->black16IreLabel->setText(QString::number(videoParameters.black16bIre));
}
