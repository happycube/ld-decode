/******************************************************************************
 * dropoutanalysisdialog.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "dropoutanalysisdialog.h"
#include "ui_dropoutanalysisdialog.h"

#include <QPen>
#include <QDebug>
#include <cmath>

DropoutAnalysisDialog::DropoutAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::DropoutAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    // Set up the plot widget
    plot = new PlotWidget(this);
    ui->verticalLayout->addWidget(plot);

    // Set up curve and marker
    curve = plot->addCurve("Dropout Length");
    curve->setPen(QPen(Qt::red, 1));
    
    plotMarker = plot->addMarker();
    plotMarker->setStyle(PlotMarker::VLine);
    plotMarker->setPen(QPen(Qt::blue, 2));

    // Set the maximum Y scale to 0
    maxY = 0;

    // Set the default number of frames
    numberOfFrames = 0;

    // Connect to plot area changed signal
    connect(plot, &PlotWidget::plotAreaChanged, this, &DropoutAnalysisDialog::onPlotAreaChanged);
}

DropoutAnalysisDialog::~DropoutAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void DropoutAnalysisDialog::startUpdate(qint32 _numberOfFrames)
{
    removeChartContents();
    numberOfFrames = _numberOfFrames;
    points.reserve(numberOfFrames);
}

// Remove the axes and series from the chart, giving ownership back to this object
void DropoutAnalysisDialog::removeChartContents()
{
    maxY = 0;
    points.clear();
    plot->replot();
}

// Add a data point to the chart
void DropoutAnalysisDialog::addDataPoint(qint32 frameNumber, double doLength)
{
    // Validate that dropout length makes physical sense
    if (doLength < 0) {
        qWarning() << "Warning: Frame" << frameNumber << "has negative dropout length:" << doLength;
        doLength = 0; // Clamp to 0 since negative dropouts don't make sense
    }
    
    points.append(QPointF(static_cast<qreal>(frameNumber), static_cast<qreal>(doLength)));

    // Keep track of the maximum Y value (minimum is always 0)
    if (doLength > maxY) maxY = doLength;
}

// Finish the update and render the graph
void DropoutAnalysisDialog::finishUpdate(qint32 _currentFrameNumber)
{
    // Set up plot properties
    plot->setCanvasBackground(Qt::white);
    plot->setGridEnabled(true);
    plot->setZoomEnabled(true);
    plot->setPanEnabled(true);
    plot->setYAxisIntegerLabels(true); // Dropouts should be whole numbers
    
    // Set axis titles and ranges
    plot->setAxisTitle(Qt::Horizontal, "Frame number");
    plot->setAxisTitle(Qt::Vertical, "Dropout length (in dots)");
    plot->setAxisRange(Qt::Horizontal, 0, numberOfFrames);
    
    // Calculate appropriate Y-axis range (dropout lengths should always be >= 0)
    // Round to whole numbers since fractions of dropouts aren't meaningful
    double yMax = (maxY < 10) ? 10 : ceil(maxY + (maxY * 0.1)); // Add 10% padding and round up
    plot->setAxisRange(Qt::Vertical, 0, yMax);

    // Set the dropout curve data (change color to dark magenta)
    curve->setPen(QPen(Qt::darkMagenta, 1));
    curve->setData(points);

    // Set the frame marker position
    plotMarker->setPosition(QPointF(static_cast<double>(_currentFrameNumber), yMax / 2));

    // Render the plot
    plot->replot();
}

// Method to update the frame marker
void DropoutAnalysisDialog::updateFrameMarker(qint32 _currentFrameNumber)
{
    double yMax = (maxY < 10) ? 10 : ceil(maxY + (maxY * 0.1));
    plotMarker->setPosition(QPointF(static_cast<double>(_currentFrameNumber), yMax / 2));
    plot->replot();
}

void DropoutAnalysisDialog::onPlotAreaChanged()
{
    // Handle plot area changes if needed
    // The PlotWidget handles zoom/pan internally
}
