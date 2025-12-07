/******************************************************************************
 * visibledropoutanalysisdialog.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "visibledropoutanalysisdialog.h"
#include "ui_visibledropoutanalysisdialog.h"

#include <QPen>
#include <QDebug>
#include <QTimer>
#include <cmath>

VisibleDropOutAnalysisDialog::VisibleDropOutAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::VisibleDropOutAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    // Set up the plot widget
    plot = new PlotWidget(this);
    plot->updateTheme();
    ui->verticalLayout->addWidget(plot);

    // Set up series and marker
    series = plot->addSeries("Visible Dropout Length");
    series->setPen(QPen(Qt::red, 1));
    series->setStyle(PlotSeries::Bars);
    
    plotMarker = plot->addMarker();
    plotMarker->setStyle(PlotMarker::VLine);
    plotMarker->setPen(QPen(Qt::blue, 2));

    // Set the maximum Y scale to 0
    maxY = 0;

    // Set the default number of frames
    numberOfFrames = 0;

    // Set up update throttling timer
    updateTimer = new QTimer(this);
    updateTimer->setSingleShot(true);
    updateTimer->setInterval(16); // ~60fps max update rate
    connect(updateTimer, &QTimer::timeout, this, &VisibleDropOutAnalysisDialog::onUpdateTimerTimeout);
    hasPendingUpdate = false;
    pendingFrameNumber = 0;

    // Connect to plot area changed signal
    connect(plot, &PlotWidget::plotAreaChanged, this, &VisibleDropOutAnalysisDialog::onPlotAreaChanged);
}

VisibleDropOutAnalysisDialog::~VisibleDropOutAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void VisibleDropOutAnalysisDialog::startUpdate(qint32 _numberOfFrames)
{
    removeChartContents();
    numberOfFrames = _numberOfFrames;
    points.reserve(numberOfFrames);
}

// Remove the axes and series from the chart, giving ownership back to this object
void VisibleDropOutAnalysisDialog::removeChartContents()
{
    maxY = 0;
    points.clear();
    plot->replot();
}

// Add a data point to the chart
void VisibleDropOutAnalysisDialog::addDataPoint(qint32 frameNumber, double doLength)
{
    points.append(QPointF(static_cast<qreal>(frameNumber), static_cast<qreal>(doLength)));

    // Keep track of the maximum Y value
    if (doLength > maxY) maxY = doLength;
}

// Finish the update and render the graph
void VisibleDropOutAnalysisDialog::finishUpdate(qint32 _currentFrameNumber)
{
    // Set up plot properties
    plot->updateTheme(); // Auto-detect theme and set appropriate background
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

    // Set the visible dropout curve data with theme-aware color
    QColor dataColor = PlotWidget::isDarkTheme() ? Qt::yellow : Qt::darkMagenta;
    series->setPen(QPen(dataColor, 2));
    series->setData(points);

    // Set the frame marker position
    plotMarker->setPosition(QPointF(static_cast<double>(_currentFrameNumber), yMax / 2));

    // Render the plot
    plot->replot();
}

// Method to update the frame marker (throttled for performance)
void VisibleDropOutAnalysisDialog::updateFrameMarker(qint32 _currentFrameNumber)
{
    // Always store the pending frame number
    pendingFrameNumber = _currentFrameNumber;
    hasPendingUpdate = true;
    
    // Skip timer start if dialog is not visible - update will happen on show
    if (!isVisible()) return;
    
    // Start or restart the timer
    if (!updateTimer->isActive()) {
        updateTimer->start();
    }
}

void VisibleDropOutAnalysisDialog::onUpdateTimerTimeout()
{
    if (!hasPendingUpdate) return;
    
    double yMax = (maxY < 10) ? 10 : ceil(maxY + (maxY * 0.1));
    plotMarker->setPosition(QPointF(static_cast<double>(pendingFrameNumber), yMax / 2));
    // No need to call plot->replot() - marker update() handles the redraw
    
    hasPendingUpdate = false;
}

void VisibleDropOutAnalysisDialog::showEvent(QShowEvent *event)
{
    QDialog::showEvent(event);
    
    // Force immediate marker update if we have a pending position
    if (hasPendingUpdate) {
        onUpdateTimerTimeout();
    }
}

void VisibleDropOutAnalysisDialog::onPlotAreaChanged()
{
    // Handle plot area changes if needed
    // The PlotWidget handles zoom/pan internally
}
