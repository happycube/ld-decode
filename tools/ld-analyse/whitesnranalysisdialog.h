/******************************************************************************
 * whitesnranalysisdialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef WHITESNRANALYSISDIALOG_H
#define WHITESNRANALYSISDIALOG_H

#include <QDialog>
#include <cmath>
#include <QPen>
#include "plotwidget.h"

namespace Ui {
class WhiteSnrAnalysisDialog;
}

class WhiteSnrAnalysisDialog : public QDialog
{
    Q_OBJECT

public:
    explicit WhiteSnrAnalysisDialog(QWidget *parent = nullptr);
    ~WhiteSnrAnalysisDialog();

    void startUpdate(qint32 _numberOfFrames);
    void addDataPoint(qint32 frameNumber, double whiteSnr);
    void finishUpdate(qint32 _currentFrameNumber);
    void updateFrameMarker(qint32 _currentFrameNumber);

private slots:
    void onPlotAreaChanged();

private:
    void removeChartContents();
    void generateTrendLine();

    Ui::WhiteSnrAnalysisDialog *ui;
    PlotWidget *plot;
    PlotSeries *whiteSeries;
    PlotSeries *trendSeries;
    PlotMarker *plotMarker;

    double maxY;
    qint32 numberOfFrames;
    QVector<QPointF> whitePoints;
    QVector<QPointF> trendPoints;
    QVector<double> tlPoint;
};

#endif // WHITESNRANALYSISDIALOG_H
