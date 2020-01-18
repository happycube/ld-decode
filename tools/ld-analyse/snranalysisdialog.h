/************************************************************************

    snranalysisdialog.h

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

#ifndef SNRANALYSISDIALOG_H
#define SNRANALYSISDIALOG_H

/* workaround for Macs */
#if defined(__APPLE__)
#define isnanf(X) isnan((double)(X))
#endif

#include <QDialog>
/* Workaround to compile on Mac. Similar may need to be done for other non-ubuntu distros */
#if defined(__APPLE__)
#include <qwt_plot.h>
#include <qwt_plot_canvas.h>
#include <qwt_legend.h>
#include <qwt_plot_grid.h>
#include <qwt_plot_curve.h>
#else
#include <qwt/qwt_plot.h>
#include <qwt/qwt_plot_canvas.h>
#include <qwt/qwt_legend.h>
#include <qwt/qwt_plot_grid.h>
#include <qwt/qwt_plot_curve.h>
#endif

#include "lddecodemetadata.h"

namespace Ui {
class SnrAnalysisDialog;
}

class SnrAnalysisDialog : public QDialog
{
    Q_OBJECT

public:
    explicit SnrAnalysisDialog(QWidget *parent = nullptr);
    ~SnrAnalysisDialog();

    void startUpdate();
    void addDataPoint(qint32 fieldNumber, qreal blackSnr, qreal whiteSnr);
    void finishUpdate(qint32 numberOfFields, qint32 fieldsPerDataPoint);

private slots:
    void on_blackPSNR_checkBox_clicked();
    void on_whiteSNR_checkBox_clicked();

private:
    void removeChartContents();

    Ui::SnrAnalysisDialog *ui;
    QwtPlot *plot;
    QwtLegend *legend;
    QwtPlotGrid *grid;
    QPolygonF *blackPoints;
    QPolygonF *whitePoints;
    QwtPlotCurve *blackCurve;
    QwtPlotCurve *whiteCurve;

    qreal maxSnr;
    qreal minSnr;
};

#endif // SNRANALYSISDIALOG_H
