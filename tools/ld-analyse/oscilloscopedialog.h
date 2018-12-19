/************************************************************************

    oscilloscopedialog.cpp

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

#ifndef OSCILLOSCOPEDIALOG_H
#define OSCILLOSCOPEDIALOG_H

#include <QDialog>
#include <QGraphicsPixmapItem>
#include <QPainter>
#include <QDebug>

#include "sourcevideo.h"
#include "lddecodemetadata.h"

namespace Ui {
class OscilloscopeDialog;
}

class OscilloscopeDialog : public QDialog
{
    Q_OBJECT

public:
    explicit OscilloscopeDialog(QWidget *parent = nullptr);
    ~OscilloscopeDialog();

    void showTraceImage(QByteArray topFieldData, QByteArray bottomFieldData, LdDecodeMetaData::VideoParameters videoParameters, qint32 scanLine);

signals:
    void scanLineChanged(qint32 scanLine);

private slots:
    void on_previousPushButton_clicked();
    void on_nextPushButton_clicked();
    void on_scanLineSpinBox_valueChanged(int arg1);
    void on_YCcheckBox_clicked();
    void on_YcheckBox_clicked();
    void on_CcheckBox_clicked();

private:
    Ui::OscilloscopeDialog *ui;
    qint32 maximumScanLines;

    QImage getFieldLineTraceImage(QByteArray rgbData, LdDecodeMetaData::VideoParameters frameParameters, qint32 fieldLine);
};

#endif // OSCILLOSCOPEDIALOG_H
