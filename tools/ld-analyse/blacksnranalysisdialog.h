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
#include <qwt_plot.h>
#include <qwt_plot_canvas.h>
#include <qwt_legend.h>
#include <qwt_plot_grid.h>
#include <qwt_plot_curve.h>
#include <qwt_plot_zoomer.h>
#include <qwt_plot_panner.h>
#include <qwt_scale_widget.h>
#include <qwt_scale_draw.h>
#include <qwt_plot_marker.h>

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

private slots:
    void scaleDivChangedSlot();

private:
    void removeChartContents();
    void generateTrendLine();

    Ui::BlackSnrAnalysisDialog *ui;
    QwtPlotZoomer *zoomer;
    QwtPlotPanner *panner;
    QwtPlot *plot;
    QwtLegend *legend;
    QwtPlotGrid *grid;
    QPolygonF *blackPoints;
    QwtPlotCurve *blackCurve;
    QPolygonF *trendPoints;
    QwtPlotCurve *trendCurve;
    QwtPlotMarker *plotMarker;

    double maxY;
    qint32 numberOfFrames;
    QVector<double> tlPoint;
};

#endif // BLACKSNRANALYSISDIALOG_H
