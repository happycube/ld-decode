/******************************************************************************
 * blacksnranalysisdialog.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "blacksnranalysisdialog.h"
#include "ui_blacksnranalysisdialog.h"

#include <QPen>
#include <algorithm>
#include <algorithm>

BlackSnrAnalysisDialog::BlackSnrAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::BlackSnrAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    // Set up the plot widget
    plot = new PlotWidget(this);
    ui->verticalLayout->addWidget(plot);

    // Set up curves and marker
    blackCurve = plot->addCurve("Black SNR");
    blackCurve->setPen(QPen(Qt::black, 1));
    
    trendCurve = plot->addCurve("Trend line");
    trendCurve->setPen(QPen(Qt::red, 2));
    
    plotMarker = plot->addMarker();
    plotMarker->setStyle(PlotMarker::VLine);
    plotMarker->setPen(QPen(Qt::blue, 2));

    // Set the maximum Y scale to 48
    maxY = 48;

    // Set the default number of frames
    numberOfFrames = 0;

    // Connect to plot area changed signal
    connect(plot, &PlotWidget::plotAreaChanged, this, &BlackSnrAnalysisDialog::onPlotAreaChanged);
}

BlackSnrAnalysisDialog::~BlackSnrAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void BlackSnrAnalysisDialog::startUpdate(qint32 _numberOfFrames)
{
    removeChartContents();
    numberOfFrames = _numberOfFrames;
    tlPoint.resize(numberOfFrames + 1);
    blackPoints.reserve(numberOfFrames);
}

// Remove the axes and series from the chart, giving ownership back to this object
void BlackSnrAnalysisDialog::removeChartContents()
{
    maxY = 48;
    blackPoints.clear();
    tlPoint.clear();
    trendPoints.clear();
    plot->replot();
}

// Add a data point to the chart
void BlackSnrAnalysisDialog::addDataPoint(qint32 frameNumber, double blackSnr)
{
    if (!std::isnan(blackSnr)) {
        // Clamp SNR values to minimum threshold (20 dB)
        double clampedSnr = std::max(blackSnr, 20.0);
        blackPoints.append(QPointF(static_cast<qreal>(frameNumber), static_cast<qreal>(clampedSnr)));
        if (clampedSnr > maxY) maxY = ceil(clampedSnr); // Round up

        // Add to trendline data (use original unclamped value for trend calculation)
        tlPoint[frameNumber] = blackSnr;
    } else {
        // Add to trendline data (mark as null value)
        tlPoint[frameNumber] = -1;
    }
}

// Finish the update and render the graph
void BlackSnrAnalysisDialog::finishUpdate(qint32 _currentFrameNumber)
{
    // Set up plot properties
    plot->setCanvasBackground(Qt::white);
    plot->setGridEnabled(true);
    plot->setZoomEnabled(true);
    plot->setPanEnabled(true);
    
    // Set axis titles and ranges
    plot->setAxisTitle(Qt::Horizontal, "Frame number");
    plot->setAxisTitle(Qt::Vertical, "SNR (in dB)");
    plot->setAxisRange(Qt::Horizontal, 0, numberOfFrames);
    plot->setAxisRange(Qt::Vertical, 20, maxY);

    // Set the black curve data
    blackCurve->setData(blackPoints);

    // Generate and set the trend line
    generateTrendLine();
    trendCurve->setData(trendPoints);

    // Set the frame marker position
    plotMarker->setPosition(QPointF(static_cast<double>(_currentFrameNumber), (maxY + 20) / 2));

    // Render the plot
    plot->replot();
}

// Method to update the frame marker
void BlackSnrAnalysisDialog::updateFrameMarker(qint32 _currentFrameNumber)
{
    plotMarker->setPosition(QPointF(static_cast<double>(_currentFrameNumber), (maxY + 20) / 2));
    plot->replot();
}

void BlackSnrAnalysisDialog::onPlotAreaChanged()
{
    // Handle plot area changes if needed
    // The PlotWidget handles zoom/pan internally
}

// Method to generate the trendline points
void BlackSnrAnalysisDialog::generateTrendLine()
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
                // Clamp trend line points to minimum threshold (20 dB)
                double clampedAvg = std::max(avgSum, 20.0);
                trendPoints.append(QPointF(f-target, clampedAvg));
            }
            avgSum = 0;
            count = 0;
            elements = 0;
        }
    }
}
