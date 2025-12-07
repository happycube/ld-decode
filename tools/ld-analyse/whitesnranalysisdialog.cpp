/******************************************************************************
 * whitesnranalysisdialog.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "whitesnranalysisdialog.h"
#include "ui_whitesnranalysisdialog.h"

#include <algorithm>

WhiteSnrAnalysisDialog::WhiteSnrAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::WhiteSnrAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    // Set up the plot widget
    plot = new PlotWidget(this);
    plot->updateTheme();
    ui->verticalLayout->addWidget(plot);

    // Set up series and marker
    whiteSeries = plot->addSeries("White SNR");
    whiteSeries->setPen(QPen(Qt::black, 1));
    
    trendSeries = plot->addSeries("Trend line");
    trendSeries->setPen(QPen(Qt::red, 2));
    
    plotMarker = plot->addMarker();
    plotMarker->setStyle(PlotMarker::VLine);
    plotMarker->setPen(QPen(Qt::blue, 2));

    // Set the maximum Y scale to 48
    maxY = 48;

    // Set the default number of frames
    numberOfFrames = 0;

    // Connect to plot area changed signal
    connect(plot, &PlotWidget::plotAreaChanged, this, &WhiteSnrAnalysisDialog::onPlotAreaChanged);
}

WhiteSnrAnalysisDialog::~WhiteSnrAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void WhiteSnrAnalysisDialog::startUpdate(qint32 _numberOfFrames)
{
    removeChartContents();
    numberOfFrames = _numberOfFrames;
    tlPoint.resize(numberOfFrames + 1);
    whitePoints.reserve(numberOfFrames);
}

// Remove the axes and series from the chart, giving ownership back to this object
void WhiteSnrAnalysisDialog::removeChartContents()
{
    maxY = 42;
    whitePoints.clear();
    tlPoint.clear();
    trendPoints.clear();
    plot->replot();
}

// Add a data point to the chart
void WhiteSnrAnalysisDialog::addDataPoint(qint32 frameNumber, double whiteSnr)
{
    if (!std::isnan(whiteSnr)) {
        // Clamp SNR values to minimum threshold (14 dB)
        double clampedSnr = std::max(whiteSnr, 14.0);
        whitePoints.append(QPointF(static_cast<qreal>(frameNumber), static_cast<qreal>(clampedSnr)));
        if (clampedSnr > maxY) maxY = ceil(clampedSnr); // Round up

        // Add to trendline data (use original unclamped value for trend calculation)
        tlPoint[frameNumber] = whiteSnr;
    } else {
        // Add to trendline data (mark as null value)
        tlPoint[frameNumber] = -1;
    }
}

// Finish the update and render the graph
void WhiteSnrAnalysisDialog::finishUpdate(qint32 _currentFrameNumber)
{
    // Set up plot properties
    plot->updateTheme(); // Auto-detect theme and set appropriate background
    plot->setGridEnabled(true);
    plot->setZoomEnabled(true);
    plot->setPanEnabled(true);
    
    // Set axis titles and ranges
    plot->setAxisTitle(Qt::Horizontal, "Frame number");
    plot->setAxisTitle(Qt::Vertical, "SNR (in dB)");
    plot->setAxisRange(Qt::Horizontal, 0, numberOfFrames);
    plot->setAxisRange(Qt::Vertical, 14, maxY);

    // Set the white series data (change color to dark gray)
    whiteSeries->setPen(QPen(Qt::darkGray, 1));
    whiteSeries->setData(whitePoints);

    // Generate and set the trend line
    generateTrendLine();
    trendSeries->setData(trendPoints);

    // Set the frame marker position
    plotMarker->setPosition(QPointF(static_cast<double>(_currentFrameNumber), (maxY + 14) / 2));

    // Render the plot
    plot->replot();
}

// Method to update the frame marker
void WhiteSnrAnalysisDialog::updateFrameMarker(qint32 _currentFrameNumber)
{
    plotMarker->setPosition(QPointF(static_cast<double>(_currentFrameNumber), (maxY + 14) / 2));
    plot->replot();
}

void WhiteSnrAnalysisDialog::onPlotAreaChanged()
{
    // Handle plot area changes if needed
    // The PlotWidget handles zoom/pan internally
}

// Method to generate the trendline points
void WhiteSnrAnalysisDialog::generateTrendLine()
{
    // Only add a trend line if there are 5000 or more frames
    if (numberOfFrames < 5000) return;

    qint32 elements = 0;
    qint32 count = 0;
    double avgSum = 0;
    qint32 target = numberOfFrames / 500; // Number of frames to average

    trendPoints.clear();
    
    for (qint32 f = 0; f < numberOfFrames; f++) {
        if (tlPoint[f] != -1) {
            avgSum += tlPoint[f];
            elements++;
        }
        count++;

        if (count == target) {
            if (avgSum > 0 && elements > 0) {
                avgSum = avgSum / static_cast<double>(elements);
                // Clamp trend line points to minimum threshold (14 dB)
                double clampedAvg = std::max(avgSum, 14.0);
                trendPoints.append(QPointF(f-target, clampedAvg));
            }
            avgSum = 0;
            count = 0;
            elements = 0;
        }
    }
}

