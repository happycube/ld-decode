/************************************************************************

    dropoutanalysisdialog.cpp

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

#include "dropoutanalysisdialog.h"
#include "ui_dropoutanalysisdialog.h"

DropoutAnalysisDialog::DropoutAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::DropoutAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);
    maxY = 0;

    // Set up the chart view
    plot = new QwtPlot();
    grid = new QwtPlotGrid();
    curve = new QwtPlotCurve();
    points = new QPolygonF();

    ui->verticalLayout->addWidget(plot);
}

DropoutAnalysisDialog::~DropoutAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void DropoutAnalysisDialog::startUpdate()
{
    removeChartContents();
    maxY = 0;
}

// Remove the axes and series from the chart, giving ownership back to this object
void DropoutAnalysisDialog::removeChartContents()
{
    points->clear();
    plot->replot();
}

// Add a data point to the chart
void DropoutAnalysisDialog::addDataPoint(qint32 frameNumber, qreal doLength)
{
    points->append(QPointF(frameNumber, doLength));

    // Keep track of the maximum Y value
    if (doLength > maxY) maxY = doLength;
}

// Finish the update and render the graph
void DropoutAnalysisDialog::finishUpdate(qint32 numberOfFrames)
{
    // Set the chart title
    plot->setTitle("Dropout loss analysis");

    // Set the background and grid
    plot->setCanvasBackground(Qt::white);
    grid->attach(plot);

    // Define the x-axis
    plot->setAxisScale(QwtPlot::xBottom, 0, numberOfFrames, (numberOfFrames / 10));
    plot->setAxisTitle(QwtPlot::xBottom, "Frame number");

    // Define the y-axis
    if (maxY < 10) plot->setAxisScale(QwtPlot::yLeft, 0, 10);
    else plot->setAxisScale(QwtPlot::yLeft, 0, maxY);
    plot->setAxisTitle(QwtPlot::yLeft, "Dropout length (in dots)");

    // Attach the curve data to the chart
    curve->setTitle("Dropout length");
    curve->setPen(Qt::blue, 1);
    curve->setRenderHint(QwtPlotItem::RenderAntialiased, true);
    curve->setSamples(*points);
    curve->attach(plot);

    // Update the axis
    plot->updateAxes();

    // Render the chart
    plot->maximumSize();
    plot->show();
}


