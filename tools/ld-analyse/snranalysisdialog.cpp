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

    // Set up the chart
    chart.legend()->hide();

    // Set up the X axis
    axisX.setTitleText("Field number");
    axisX.setLabelFormat("%i");
    chart.addAxis(&axisX, Qt::AlignBottom);

    // Set up the Y axis
    axisY.setTitleText("SNR (in dB)");
    axisY.setLabelFormat("%i");
    axisY.setTickCount(1000);
    chart.addAxis(&axisY, Qt::AlignLeft);

    // Set up the chart view
    chartView = new QChartView(&chart);
    chartView->setRenderHint(QPainter::Antialiasing);
    chartView->setRubberBand(QChartView::HorizontalRubberBand);
    ui->verticalLayout->addWidget(chartView);
    chartView->repaint();    

    firstRun = true;
}

SnrAnalysisDialog::~SnrAnalysisDialog()
{
    delete ui;
}

void SnrAnalysisDialog::updateChart(LdDecodeMetaData *ldDecodeMetaData)
{
    // Remove series before updating to prevent GUI updates
    if (!firstRun) {
        chart.removeSeries(&blackSeries);
        chart.removeSeries(&whiteSeries);
    }
    else firstRun = false;

    blackSeries.clear();
    whiteSeries.clear();

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
        blackSeries.append(fieldNumber, blackSnrTotal);
        whiteSeries.append(fieldNumber, whiteSnrTotal);
    }

    // Update the chart
    chart.setTitle("SNR analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");

    axisX.setMin(0);
    axisX.setTickCount(10);
    if (ldDecodeMetaData->getNumberOfFields() < 10) axisX.setMax(10);
    else axisX.setMax(ldDecodeMetaData->getNumberOfFields());

    axisY.setTickCount(10);
    axisY.setMax(maximumSNR + 5.0); // +5 to give a little space at the top of the window
    if ((minimumSNR - 5.0) > 0) axisY.setMin(minimumSNR - 5);
    else axisY.setMin(0);

    chart.addSeries(&blackSeries);
    chart.addSeries(&whiteSeries);

    blackSeries.setColor(Qt::black);
    whiteSeries.setColor(Qt::gray);
    axisX.setTickCount(10);
    blackSeries.attachAxis(&axisX);
    whiteSeries.attachAxis(&axisX);
    blackSeries.attachAxis(&axisY);
    whiteSeries.attachAxis(&axisY);

    chartView->repaint();
}

void SnrAnalysisDialog::on_pushButton_clicked()
{
    chart.zoomReset();
}

void SnrAnalysisDialog::on_blackPSNR_checkBox_clicked()
{
    if (ui->blackPSNR_checkBox->isChecked()) blackSeries.show();
    else blackSeries.hide();
}

void SnrAnalysisDialog::on_whiteSNR_checkBox_clicked()
{
    if (ui->whiteSNR_checkBox->isChecked()) whiteSeries.show();
    else whiteSeries.hide();
}
