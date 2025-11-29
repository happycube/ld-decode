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

DropoutAnalysisDialog::DropoutAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::DropoutAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    // Set up the chart view
    plot = new QwtPlot();
    zoomer = new QwtPlotZoomer(plot->canvas());
    panner = new QwtPlotPanner(plot->canvas());
    grid = new QwtPlotGrid();
    curve = new QwtPlotCurve();
    points = new QPolygonF();
    plotMarker = new QwtPlotMarker();

    ui->verticalLayout->addWidget(plot);

    // Set the maximum Y scale to 0
    maxY = 0;

    // Set the default number of frames
    numberOfFrames = 0;

    // Connect to scale changed slot
#ifdef Q_OS_WIN32
    // Workaround for linker issue with Qwt on windows
    connect(
        plot->axisWidget(QwtPlot::xBottom), SIGNAL( scaleDivChanged() ),
        this, SLOT( scaleDivChangedSlot() )
    );
#else
    connect(plot->axisWidget(QwtPlot::xBottom), &QwtScaleWidget::scaleDivChanged, this, &DropoutAnalysisDialog::scaleDivChangedSlot);
#endif
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
    points->reserve(numberOfFrames);
}

// Remove the axes and series from the chart, giving ownership back to this object
void DropoutAnalysisDialog::removeChartContents()
{
    maxY = 0;
    points->clear();
    plot->replot();
}

// Add a data point to the chart
void DropoutAnalysisDialog::addDataPoint(qint32 frameNumber, double doLength)
{
    points->append(QPointF(static_cast<qreal>(frameNumber), static_cast<qreal>(doLength)));

    // Keep track of the maximum Y value
    if (doLength > maxY) maxY = doLength;
}

// Finish the update and render the graph
void DropoutAnalysisDialog::finishUpdate(qint32 _currentFrameNumber)
{
    // Set the chart title
    plot->setTitle("Dropout Loss Analysis");

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
    curve->setPen(Qt::darkMagenta, 1);
    curve->setRenderHint(QwtPlotItem::RenderAntialiased, true);
    curve->setSamples(*points);
    curve->attach(plot);

    // Define the plot marker
    plotMarker->setLineStyle(QwtPlotMarker::VLine);
    plotMarker->setLinePen(Qt::blue, 2, Qt::SolidLine);
    plotMarker->setXValue(static_cast<double>(_currentFrameNumber));
    plotMarker->attach(plot);

    // Update the axis
    plot->updateAxes();

    // Update the plot zoomer base
    zoomer->setZoomBase(true);

    // Set the plot zoomer mouse controls
    zoomer->setMousePattern(QwtEventPattern::MouseSelect2, Qt::RightButton, Qt::ControlModifier);
    zoomer->setMousePattern(QwtEventPattern::MouseSelect3, Qt::RightButton);

    // Set the plot zoomer colour
    zoomer->setRubberBandPen(QPen(Qt::red, 2, Qt::DotLine));
    zoomer->setTrackerPen(QPen(Qt::red));

    // Update the plot panner
    panner->setAxisEnabled(QwtPlot::yRight, false);
    panner->setMouseButton(Qt::MiddleButton);

    // Render the chart
    plot->maximumSize();
    plot->show();
}

// Method to update the frame marker
void DropoutAnalysisDialog::updateFrameMarker(qint32 _currentFrameNumber)
{
    plotMarker->setXValue(static_cast<double>(_currentFrameNumber));
    plot->replot();
}

void DropoutAnalysisDialog::scaleDivChangedSlot()
{
    // If user zooms all the way out, reapply axis scale defaults
    if (zoomer->zoomRectIndex() == 0) {
        plot->setAxisScale(QwtPlot::xBottom, 0, numberOfFrames, (numberOfFrames / 10));
        if (maxY < 10) plot->setAxisScale(QwtPlot::yLeft, 0, 10);
        else plot->setAxisScale(QwtPlot::yLeft, 0, maxY);
        plot->replot();
    }
}
