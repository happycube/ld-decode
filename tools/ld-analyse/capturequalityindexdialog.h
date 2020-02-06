/************************************************************************

    capturequalityindexdialog.h

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2020 Simon Inns

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

#ifndef CAPTUREQUALITYINDEXDIALOG_H
#define CAPTUREQUALITYINDEXDIALOG_H

#include <QDialog>
#include <qwt_plot.h>
#include <qwt_plot_canvas.h>
#include <qwt_legend.h>
#include <qwt_plot_grid.h>
#include <qwt_plot_curve.h>

#include "lddecodemetadata.h"

namespace Ui {
class CaptureQualityIndexDialog;
}

class CaptureQualityIndexDialog : public QDialog
{
    Q_OBJECT

public:
    explicit CaptureQualityIndexDialog(QWidget *parent = nullptr);
    ~CaptureQualityIndexDialog();

    void startUpdate();
    void addDataPoint(qint32 fieldNumber, qreal cqi);
    void finishUpdate(qint32 numberOfFields, qint32 fieldsPerDataPoint);

private:
    void removeChartContents();

    Ui::CaptureQualityIndexDialog *ui;
    QwtPlot *plot;
    QwtLegend *legend;
    QwtPlotGrid *grid;
    QPolygonF *points;
    QwtPlotCurve *curve;

    qreal maxY;
    qreal minY;
};

#endif // CAPTUREQUALITYINDEXDIALOG_H
