/******************************************************************************
 * oscilloscopedialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef OSCILLOSCOPEDIALOG_H
#define OSCILLOSCOPEDIALOG_H

#include <QDialog>
#include <QGraphicsPixmapItem>
#include <QPainter>
#include <QDebug>
#include <QMouseEvent>

#include "tbcsource.h"

namespace Ui {
class OscilloscopeDialog;
}

class OscilloscopeDialog : public QDialog
{
    Q_OBJECT

public:
    explicit OscilloscopeDialog(QWidget *parent = nullptr);
    ~OscilloscopeDialog();

    void showTraceImage(TbcSource::ScanLineData scanLineData, qint32 xCoord, qint32 yCoord, qint32 frameWidth, qint32 frameHeight, bool bothSources);

signals:
    void scopeCoordsChanged(qint32 xCoord, qint32 yCoord);
    void scopeLevelSelect(qint32 value);

private slots:
    void on_previousPushButton_clicked();
    void on_nextPushButton_clicked();
    void on_xCoordSpinBox_valueChanged(int arg1);
    void on_yCoordSpinBox_valueChanged(int arg1);
    void on_YCcheckBox_clicked();
    void on_YcheckBox_clicked();
    void on_CcheckBox_clicked();
    void on_dropoutsCheckBox_clicked();

    void mousePressEvent(QMouseEvent *event);
    void mouseMoveEvent(QMouseEvent *event);

private:
    Ui::OscilloscopeDialog *ui;
    qint32 maximumX;
    qint32 maximumY;
    qint32 scopeWidth;
    qint32 lastScopeX;
    qint32 lastScopeY;

    QImage getFieldLineTraceImage(TbcSource::ScanLineData scanLineData, qint32 pictureDot, bool bothSources);
    void mouseLevelSelect(qint32 oY);
    void mousePictureDotSelect(qint32 oX);
};

#endif // OSCILLOSCOPEDIALOG_H
