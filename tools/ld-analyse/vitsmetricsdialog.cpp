/************************************************************************

    vitsmetricsdialog.cpp

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

#include "vitsmetricsdialog.h"
#include "ui_vitsmetricsdialog.h"

VitsMetricsDialog::VitsMetricsDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::VitsMetricsDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);
}

VitsMetricsDialog::~VitsMetricsDialog()
{
    delete ui;
}

void VitsMetricsDialog::updateVitsMetrics(LdDecodeMetaData::Field firstField, LdDecodeMetaData::Field secondField)
{
    qDebug() << "VitsMetricsDialog::updateVitsMetrics(): Called";

    if (firstField.vitsMetrics.inUse || secondField.vitsMetrics.inUse) {
        if (firstField.vitsMetrics.wSNR > 0) ui->whiteSNRLabel->setText(QString::number(firstField.vitsMetrics.wSNR));
        else ui->whiteSNRLabel->setText(QString::number(secondField.vitsMetrics.wSNR));

        if (firstField.vitsMetrics.bPSNR > 0) ui->blackLinePSNRLabel->setText(QString::number(firstField.vitsMetrics.bPSNR));
        else ui->blackLinePSNRLabel->setText(QString::number(secondField.vitsMetrics.bPSNR));
    } else {
        ui->whiteSNRLabel->setText("0");
        ui->blackLinePSNRLabel->setText("0");
    }
}
