/************************************************************************

    busydialog.cpp

    ld-combine - TBC combination and enhancement tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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

#include "busydialog.h"
#include "ui_busydialog.h"

BusyDialog::BusyDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::BusyDialog)
{
    ui->setupUi(this);
    showProgress(false);

    setWindowFlags(Qt::Window | Qt::FramelessWindowHint);
}

BusyDialog::~BusyDialog()
{
    delete ui;
}

void BusyDialog::setMessage(QString message)
{
    ui->messageLabel->setText(message);
}

void BusyDialog::setProgress(qint32 progress)
{
    if (progress < 0) progress = 0;
    if (progress > 100) progress = 100;

    ui->progressBar->setValue(progress);
}

void BusyDialog::showProgress(bool state)
{
    if (!state) ui->progressBar->hide();
    else ui->progressBar->show();
}
