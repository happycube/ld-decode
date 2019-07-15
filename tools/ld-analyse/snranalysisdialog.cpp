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

void SnrAnalysisDialog::updateChart(LdDecodeMetaData *ldDecodeMetaData)
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

    qreal targetDataPoints = 2000;
    qreal averageWidth = qRound(ldDecodeMetaData->getNumberOfFields() / targetDataPoints);
    if (averageWidth < 1) averageWidth = 1; // Ensure we don't divide by zero
    qint32 dataPoints = ldDecodeMetaData->getNumberOfFields() / static_cast<qint32>(averageWidth);
    qint32 fieldsPerDataPoint = ldDecodeMetaData->getNumberOfFields() / dataPoints;

    qint32 fieldNumber = 1;
    qreal maximumSNR = 0;
    qreal minimumSNR = 1000.0;
    for (qint32 snrCount = 0; snrCount < dataPoints; snrCount++) {
        qreal blackSnrTotal = 0;
        qreal whiteSnrTotal = 0;
        for (qint32 avCount = 0; avCount < fieldsPerDataPoint; avCount++) {
            LdDecodeMetaData::Field field = ldDecodeMetaData->getField(fieldNumber);

            if (field.vitsMetrics.inUse) {
                blackSnrTotal += field.vitsMetrics.bPSNR;
                whiteSnrTotal += field.vitsMetrics.wSNR;
            }
            fieldNumber++;
        }

        // Calculate the average
        if (blackSnrTotal > 0) blackSnrTotal = blackSnrTotal / static_cast<qreal>(fieldsPerDataPoint);
        if (whiteSnrTotal > 0) whiteSnrTotal = whiteSnrTotal / static_cast<qreal>(fieldsPerDataPoint);

        // Keep track of the maximum and minimum Y values
        if (blackSnrTotal > maximumSNR) maximumSNR = blackSnrTotal;
        if (blackSnrTotal < minimumSNR) minimumSNR = blackSnrTotal;
        if (whiteSnrTotal > maximumSNR) maximumSNR = whiteSnrTotal;
        if (whiteSnrTotal < minimumSNR) minimumSNR = whiteSnrTotal;

        // Add the result to the series
        blackQLineSeries.append(fieldNumber, blackSnrTotal);
        whiteQLineSeries.append(fieldNumber, whiteSnrTotal);
    }

    // Create the chart
    chart.setTitle("SNR analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");
    chart.legend()->hide();

    // Create the x axis
    axisX.setMin(0);
    axisX.setTickCount(10);
    if (ldDecodeMetaData->getNumberOfFields() < 10) axisX.setMax(10);
    else axisX.setMax(ldDecodeMetaData->getNumberOfFields());
    axisX.setTitleText("Field number");
    axisX.setLabelFormat("%i");

    // Create the Y axis
    axisY.setTickCount(10);
    axisY.setMax(maximumSNR + 5.0); // +5 to give a little space at the top of the window
    if ((minimumSNR - 5.0) > 0) axisY.setMin(minimumSNR - 5);
    else axisY.setMin(0);
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
