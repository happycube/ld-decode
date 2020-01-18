/************************************************************************

    snranalysisdialog.cpp

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

#include "snranalysisdialog.h"
#include "ui_snranalysisdialog.h"

SnrAnalysisDialog::SnrAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::SnrAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);
    maxSnr = 0;
    minSnr = 1000;

    // Set up the chart view
    plot = new QwtPlot();
    grid = new QwtPlotGrid();
    blackCurve = new QwtPlotCurve();
    whiteCurve = new QwtPlotCurve();
    blackPoints = new QPolygonF();
    whitePoints = new QPolygonF();

    ui->verticalLayout->addWidget(plot);
}

SnrAnalysisDialog::~SnrAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void SnrAnalysisDialog::startUpdate()
{
    removeChartContents();
    maxSnr = 0;
    minSnr = 1000;
}

// Remove the axes and series from the chart, giving ownership back to this object
void SnrAnalysisDialog::removeChartContents()
{
    blackPoints->clear();
    whitePoints->clear();
    plot->replot();
}

// Add a data point to the chart
void SnrAnalysisDialog::addDataPoint(qint32 fieldNumber, qreal blackSnr, qreal whiteSnr)
{
    if (!std::isnan(static_cast<float>(blackSnr))) blackPoints->append(QPointF(fieldNumber, blackSnr));
    if (!std::isnan(static_cast<float>(whiteSnr))) whitePoints->append(QPointF(fieldNumber, whiteSnr));

    // Keep track of the minimum and maximum SNR values
    if (blackSnr < minSnr) minSnr = blackSnr;
    if (whiteSnr < minSnr) minSnr = whiteSnr;
    if (blackSnr > maxSnr) maxSnr = blackSnr;
    if (whiteSnr > maxSnr) maxSnr = whiteSnr;
}

// Finish the update and render the graph
void SnrAnalysisDialog::finishUpdate(qint32 numberOfFields, qint32 fieldsPerDataPoint)
{
    // Set the chart title
    plot->setTitle("SNR analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");

    // Set the background and grid
    plot->setCanvasBackground(Qt::white);
    grid->attach(plot);

    // Define the x-axis
    plot->setAxisScale(QwtPlot::xBottom, 0, numberOfFields, (numberOfFields / 10) + 1);
    plot->setAxisTitle(QwtPlot::xBottom, "Field number");

    // Define the y-axis
    plot->setAxisScale(QwtPlot::yLeft, floor(minSnr - 1), ceil(maxSnr + 1),
                       static_cast<qint32>(ceil(maxSnr + 1) - floor(minSnr - 1) + 1) / 10);
    plot->setAxisTitle(QwtPlot::yLeft, "SNR (in dB)");

    // Attach the black curve data to the chart
    blackCurve->setTitle("Black SNR");
    blackCurve->setPen(Qt::black, 1);
    blackCurve->setRenderHint(QwtPlotItem::RenderAntialiased, true);
    blackCurve->setSamples(*blackPoints);
    blackCurve->attach(plot);

    // Attach the white curve data to the chart
    whiteCurve->setTitle("White SNR");
    whiteCurve->setPen(Qt::gray, 1);
    whiteCurve->setRenderHint(QwtPlotItem::RenderAntialiased, true);
    whiteCurve->setSamples(*whitePoints);
    whiteCurve->attach(plot);

    // Update the axis
    plot->updateAxes();

    // Render the chart
    plot->maximumSize();
    plot->show();
}

void SnrAnalysisDialog::on_blackPSNR_checkBox_clicked()
{
    if (ui->blackPSNR_checkBox->isChecked()) blackCurve->attach(plot);
    else blackCurve->detach();
    plot->replot();
}

void SnrAnalysisDialog::on_whiteSNR_checkBox_clicked()
{
    if (ui->whiteSNR_checkBox->isChecked()) whiteCurve->attach(plot);
    else whiteCurve->detach();
    plot->replot();
}

