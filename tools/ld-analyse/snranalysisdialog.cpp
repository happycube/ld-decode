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

    // Set up the chart
    chart.legend()->hide();
    chart.addSeries(&series);

    // Set up the X axis
    axisX.setTitleText("Field number");
    axisX.setLabelFormat("%i");
    axisX.setTickCount(series.count());
    chart.addAxis(&axisX, Qt::AlignBottom);
    series.attachAxis(&axisX);

    // Set up the Y axis
    axisY.setTitleText("Black Peak SNR (in dB)");
    axisY.setLabelFormat("%i");
    axisY.setTickCount(1000);
    chart.addAxis(&axisY, Qt::AlignLeft);
    series.attachAxis(&axisY);

    // Set up the chart view
    chartView = new QChartView(&chart);
    chartView->setRenderHint(QPainter::Antialiasing);
    ui->verticalLayout->addWidget(chartView);
    chartView->repaint();
}

SnrAnalysisDialog::~SnrAnalysisDialog()
{
    delete ui;
}

void SnrAnalysisDialog::updateChart(LdDecodeMetaData *ldDecodeMetaData)
{
    series.clear();

    qreal targetDataPoints = 500;
    qreal averageWidth = qRound(ldDecodeMetaData->getNumberOfFields() / targetDataPoints);
    if (averageWidth < 1) averageWidth = 1; // Ensure we don't divide by zero
    qint32 dataPoints = ldDecodeMetaData->getNumberOfFields() / static_cast<qint32>(averageWidth);
    qint32 fieldsPerDataPoint = ldDecodeMetaData->getNumberOfFields() / dataPoints;

    qint32 fieldNumber = 1;
    qreal maximumBlackPSNR = 0;
    qreal minimumBlackPSNR = 1000.0;
    for (qint32 snrCount = 0; snrCount < dataPoints; snrCount++) {
        qreal snrTotal = 0;
        for (qint32 avCount = 0; avCount < fieldsPerDataPoint; avCount++) {
            LdDecodeMetaData::Field field = ldDecodeMetaData->getField(fieldNumber);

            snrTotal += field.vitsMetrics.blackLinePSNR;
            fieldNumber++;
        }

        // Calculate the average
        snrTotal = snrTotal / static_cast<qreal>(fieldsPerDataPoint);

        // Keep track of the maximum and minimum Y values
        if (snrTotal > maximumBlackPSNR) maximumBlackPSNR = snrTotal;
        if (snrTotal < minimumBlackPSNR) minimumBlackPSNR = snrTotal;

        // Add the result to the series
        series.append(fieldNumber, snrTotal);
    }

    // Update the chart
    chart.setTitle("Black peak SNR analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");

    axisX.setMin(0);
    axisX.setTickCount(10);
    if (ldDecodeMetaData->getNumberOfFields() < 10) axisX.setMax(10);
    else axisX.setMax(ldDecodeMetaData->getNumberOfFields());

    axisY.setTickCount(10);
    axisY.setMax(maximumBlackPSNR + 5.0); // +5 to give a little space at the top of the window
    if ((minimumBlackPSNR - 5.0) > 0) axisY.setMin(minimumBlackPSNR - 5);
    else axisY.setMin(0);

    chartView->repaint();
}
