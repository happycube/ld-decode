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

    chartOwnsContents = false;
    maxSnr = 0;
    minSnr = 1000;

    // Set up the chart view
    chartView.setChart(&chart);
    chartView.setRubberBand(QChartView::HorizontalRubberBand);
    chartView.setRenderHint(QPainter::Antialiasing);

    ui->verticalLayout->addWidget(&chartView);
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
    blackQLineSeries.clear();
    whiteQLineSeries.clear();

    // Create the QLineSeries
    blackQLineSeries.setColor(Qt::black);
    whiteQLineSeries.setColor(Qt::gray);

    maxSnr = 0;
    minSnr = 1000;
}

// Remove the axes and series from the chart, giving ownership back to this object
void SnrAnalysisDialog::removeChartContents()
{
    if (!chartOwnsContents) return;

    chart.removeAxis(&axisX);
    chart.removeAxis(&axisY);
    chart.removeSeries(&blackQLineSeries);
    chart.removeSeries(&whiteQLineSeries);

    chartOwnsContents = false;
}

// Add a data point to the chart
void SnrAnalysisDialog::addDataPoint(qint32 fieldNumber, qreal blackSnr, qreal whiteSnr)
{
    if (!isnanf(static_cast<float>(blackSnr))) blackQLineSeries.append(fieldNumber, blackSnr);
    if (!isnanf(static_cast<float>(whiteSnr))) whiteQLineSeries.append(fieldNumber, whiteSnr);

    // Keep track of the minimum and maximum SNR values
    if (blackSnr < minSnr) minSnr = blackSnr;
    if (whiteSnr < minSnr) minSnr = whiteSnr;
    if (blackSnr > maxSnr) maxSnr = blackSnr;
    if (whiteSnr > maxSnr) maxSnr = whiteSnr;
}

// Finish the update and render the graph
void SnrAnalysisDialog::finishUpdate(qint32 numberOfFields, qint32 fieldsPerDataPoint)
{
    // Create the chart
    chart.setTitle("SNR analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");
    chart.legend()->hide();

    // Create the x axis
    axisX.setMin(0);
    axisX.setTickCount(10);
    if (numberOfFields < 10) axisX.setMax(10);
    else axisX.setMax(numberOfFields);
    axisX.setTitleText("Field number");
    axisX.setLabelFormat("%i");

    // Create the Y axis
    axisY.setMax(ceil(maxSnr + 1));
    axisY.setMin(floor(minSnr - 1));
    axisY.setTickCount(static_cast<qint32>(ceil(maxSnr + 1) - floor(minSnr - 1) + 1));
    axisY.setTitleText("SNR (in dB)");
    axisY.setLabelFormat("%i");

    // Attach the axis to the chart
    chart.addAxis(&axisX, Qt::AlignBottom);
    chart.addAxis(&axisY, Qt::AlignLeft);

    // Attach the series to the chart
    chart.addSeries(&blackQLineSeries);
    chart.addSeries(&whiteQLineSeries);

    // The chart now owns the axes and series
    chartOwnsContents = true;

    // Attach the axis to the QLineSeries
    blackQLineSeries.attachAxis(&axisX);
    whiteQLineSeries.attachAxis(&axisX);
    blackQLineSeries.attachAxis(&axisY);
    whiteQLineSeries.attachAxis(&axisY);

    // Render
    chartView.repaint();
}

void SnrAnalysisDialog::on_pushButton_clicked()
{
    chart.zoomReset();
}

void SnrAnalysisDialog::on_blackPSNR_checkBox_clicked()
{
    if (ui->blackPSNR_checkBox->isChecked()) blackQLineSeries.show();
    else blackQLineSeries.hide();
}

void SnrAnalysisDialog::on_whiteSNR_checkBox_clicked()
{
    if (ui->whiteSNR_checkBox->isChecked()) whiteQLineSeries.show();
    else whiteQLineSeries.hide();
}

