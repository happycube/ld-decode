/************************************************************************

    capturequalityindexdialog.cpp

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

#include "capturequalityindexdialog.h"
#include "ui_capturequalityindexdialog.h"

CaptureQualityIndexDialog::CaptureQualityIndexDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::CaptureQualityIndexDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);
    maxY = 0;
    minY = 100;

    // Set up the chart view
    plot = new QwtPlot();
    grid = new QwtPlotGrid();
    curve = new QwtPlotCurve();
    points = new QPolygonF();

    ui->verticalLayout->addWidget(plot);
}

CaptureQualityIndexDialog::~CaptureQualityIndexDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void CaptureQualityIndexDialog::startUpdate()
{
    removeChartContents();
    maxY = 0;
    minY = 100;
}

// Remove the axes and series from the chart, giving ownership back to this object
void CaptureQualityIndexDialog::removeChartContents()
{
    points->clear();
    plot->replot();
}

// Add a data point to the chart
void CaptureQualityIndexDialog::addDataPoint(qint32 fieldNumber, qreal cqi)
{
    points->append(QPointF(fieldNumber, cqi));

    // Keep track of the maximum and minimum Y values
    if (cqi > maxY) maxY = cqi;
    if (cqi < minY) minY = cqi;
}

// Finish the update and render the graph
void CaptureQualityIndexDialog::finishUpdate(qint32 numberOfFields, qint32 fieldsPerDataPoint)
{
    // Set the chart title
    plot->setTitle("Capture Quality Index (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");

    // Set the background and grid
    plot->setCanvasBackground(Qt::white);
    grid->attach(plot);

    // Define the x-axis
    plot->setAxisScale(QwtPlot::xBottom, 0, numberOfFields, (numberOfFields / 10) + 1);
    plot->setAxisTitle(QwtPlot::xBottom, "Field number");

    // Define the y-axis
    if (maxY < 10) plot->setAxisScale(QwtPlot::yLeft, minY, minY + 10);
    else plot->setAxisScale(QwtPlot::yLeft, minY, maxY);
    plot->setAxisTitle(QwtPlot::yLeft, "Capture Quality Index (%)");

    // Attach the curve data to the chart
    curve->setTitle("Capture Quality Index");
    curve->setPen(Qt::magenta, 1);
    curve->setRenderHint(QwtPlotItem::RenderAntialiased, true);
    curve->setSamples(*points);
    curve->attach(plot);

    // Update the axis
    plot->updateAxes();

    // Render the chart
    plot->maximumSize();
    plot->show();
}
