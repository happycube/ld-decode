/************************************************************************

    blacksnranalysisdialog.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2021 Simon Inns

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

#include "blacksnranalysisdialog.h"
#include "ui_blacksnranalysisdialog.h"

BlackSnrAnalysisDialog::BlackSnrAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::BlackSnrAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    // Set up the chart view
    plot = new QwtPlot();
    zoomer = new QwtPlotZoomer(plot->canvas());
    panner = new QwtPlotPanner(plot->canvas());
    grid = new QwtPlotGrid();
    blackCurve = new QwtPlotCurve();
    blackPoints = new QPolygonF();
    plotMarker = new QwtPlotMarker();

    ui->verticalLayout->addWidget(plot);

    // Set the maximum Y scale to 48
    maxY = 48;

    // Set the default number of frames
    numberOfFrames = 0;

    // Connect to scale changed slot
    connect(((QObject*)plot->axisWidget(QwtPlot::xBottom)) , SIGNAL(scaleDivChanged () ), this, SLOT(scaleDivChangedSlot () ));
}

BlackSnrAnalysisDialog::~BlackSnrAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void BlackSnrAnalysisDialog::startUpdate()
{
    removeChartContents();
}

// Remove the axes and series from the chart, giving ownership back to this object
void BlackSnrAnalysisDialog::removeChartContents()
{
    maxY = 48;
    blackPoints->clear();
    plot->replot();
}

// Add a data point to the chart
void BlackSnrAnalysisDialog::addDataPoint(qint32 frameNumber, qreal blackSnr)
{
    if (!std::isnan(static_cast<float>(blackSnr))) {
        qDebug() << "Frame number" << frameNumber;
        blackPoints->append(QPointF(frameNumber, blackSnr));
        if (blackSnr > maxY) maxY = ceil(blackSnr); // Round up
    }
}

// Finish the update and render the graph
void BlackSnrAnalysisDialog::finishUpdate(qint32 _numberOfFrames, qint32 _currentFrameNumber)
{
    numberOfFrames = _numberOfFrames;

    // Set the chart title
    plot->setTitle("Black SNR Analysis");

    // Set the background and grid
    plot->setCanvasBackground(Qt::white);
    grid->attach(plot);

    // Define the x-axis
    plot->setAxisScale(QwtPlot::xBottom, 0, numberOfFrames, (numberOfFrames / 10));
    plot->setAxisTitle(QwtPlot::xBottom, "Frame number");

    // Define the y-axis (with a fixed scale)
    plot->setAxisScale(QwtPlot::yLeft, 20, maxY, 2);
    plot->setAxisTitle(QwtPlot::yLeft, "SNR (in dB)");

    // Attach the black curve data to the chart
    blackCurve->setTitle("Black SNR");
    blackCurve->setPen(Qt::black, 1);
    blackCurve->setRenderHint(QwtPlotItem::RenderAntialiased, true);
    blackCurve->setSamples(*blackPoints);
    blackCurve->attach(plot);

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
    panner->setMouseButton(Qt::MidButton);

    // Render the chart
    plot->maximumSize();
    plot->show();

}

// Method to update the frame marker
void BlackSnrAnalysisDialog::updateFrameMarker(qint32 _currentFrameNumber)
{
    plotMarker->setXValue(static_cast<double>(_currentFrameNumber));
    plot->replot();
}

void BlackSnrAnalysisDialog::scaleDivChangedSlot()
{
    // If user zooms all the way out, reapply axis scale defaults
    if (zoomer->zoomRectIndex() == 0) {
        plot->setAxisScale(QwtPlot::xBottom, 0, numberOfFrames, (numberOfFrames / 10));
        plot->setAxisScale(QwtPlot::yLeft, 20, maxY, 2);
        plot->replot();
    }
}

