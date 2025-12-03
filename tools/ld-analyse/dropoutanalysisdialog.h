/******************************************************************************
 * dropoutanalysisdialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef DROPOUTANALYSISDIALOG_H
#define DROPOUTANALYSISDIALOG_H

#include <QDialog>
#include "plotwidget.h"
#include "lddecodemetadata.h"

namespace Ui {
class DropoutAnalysisDialog;
}

class DropoutAnalysisDialog : public QDialog
{
    Q_OBJECT

public:
    explicit DropoutAnalysisDialog(QWidget *parent = nullptr);
    ~DropoutAnalysisDialog();

    void startUpdate(qint32 _numberOfFrames);
    void addDataPoint(qint32 frameNumber, double doLength);
    void finishUpdate(qint32 _currentFrameNumber);
    void updateFrameMarker(qint32 _currentFrameNumber);

private slots:
    void onPlotAreaChanged();

private:
    void removeChartContents();

    Ui::DropoutAnalysisDialog *ui;
    PlotWidget *plot;
    PlotCurve *curve;
    PlotMarker *plotMarker;

    double maxY;
    qint32 numberOfFrames;
    QVector<QPointF> points;
};

#endif // DROPOUTANALYSISDIALOG_H
