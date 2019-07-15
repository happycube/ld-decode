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

    isFirstRun = true;
    minSnr = -1000.0;

    // Set up the chart view
    chartView.setChart(&chart);
    chartView.setRubberBand(QChartView::HorizontalRubberBand);
    chartView.setRenderHint(QPainter::Antialiasing);

    ui->verticalLayout->addWidget(&chartView);
}

SnrAnalysisDialog::~SnrAnalysisDialog()
{
    delete ui;
}

// Get ready for an update
void SnrAnalysisDialog::startUpdate()
{
    if (!isFirstRun) {
        chart.removeAxis(&axisX);
        chart.removeAxis(&axisY);
        chart.removeSeries(&blackQLineSeries);
        chart.removeSeries(&whiteQLineSeries);
    } else isFirstRun = false;
    blackQLineSeries.clear();
    whiteQLineSeries.clear();

    // Create the QLineSeries
    blackQLineSeries.setColor(Qt::black);
    whiteQLineSeries.setColor(Qt::gray);

    minSnr = -1000.0;
}

// Add a data point to the chart
void SnrAnalysisDialog::addDataPoint(qint32 fieldNumber, qreal blackSnr, qreal whiteSnr)
{
    blackQLineSeries.append(fieldNumber, blackSnr);
    whiteQLineSeries.append(fieldNumber, whiteSnr);

    // Keep track of the minimum Y value
    if (blackSnr < minSnr) minSnr = blackSnr;
    if (whiteSnr < minSnr) minSnr = whiteSnr;
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
    axisY.setTickCount(10);
    axisY.setTitleText("SNR (in dB)");
    axisY.setLabelFormat("%i");

    // Attach the axis to the chart
    chart.addAxis(&axisX, Qt::AlignBottom);
    chart.addAxis(&axisY, Qt::AlignLeft);

    // Attach the series to the chart
    chart.addSeries(&blackQLineSeries);
    chart.addSeries(&whiteQLineSeries);

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
