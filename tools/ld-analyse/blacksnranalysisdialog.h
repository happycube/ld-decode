/******************************************************************************
 * blacksnranalysisdialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef BLACKSNRANALYSISDIALOG_H
#define BLACKSNRANALYSISDIALOG_H

#include <cmath>

#include <QDialog>
#include <QTimer>
#include <QShowEvent>
#include "plotwidget.h"
#include "lddecodemetadata.h"

namespace Ui {
class BlackSnrAnalysisDialog;
}

class BlackSnrAnalysisDialog : public QDialog
{
    Q_OBJECT

public:
    explicit BlackSnrAnalysisDialog(QWidget *parent = nullptr);
    ~BlackSnrAnalysisDialog();

    void startUpdate(qint32 _numberOfFrames);
    void addDataPoint(qint32 frameNumber, double blackSnr);
    void finishUpdate(qint32 _currentFrameNumber);
    void updateFrameMarker(qint32 _currentFrameNumber);

protected:
    void showEvent(QShowEvent *event) override;

private slots:
    void onPlotAreaChanged();
    void onUpdateTimerTimeout();

private:
    void removeChartContents();
    void generateTrendLine();

    Ui::BlackSnrAnalysisDialog *ui;
    PlotWidget *plot;
    PlotSeries *blackSeries;
    PlotSeries *trendSeries;
    PlotMarker *plotMarker;

    double maxY;
    qint32 numberOfFrames;
    QVector<QPointF> blackPoints;
    QVector<QPointF> trendPoints;
    
    QTimer *updateTimer;
    qint32 pendingFrameNumber;
    bool hasPendingUpdate;
    QVector<double> tlPoint;
};

#endif // BLACKSNRANALYSISDIALOG_H
