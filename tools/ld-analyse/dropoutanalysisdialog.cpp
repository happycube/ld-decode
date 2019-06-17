/************************************************************************

    dropoutanalysisdialog.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
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

#include "dropoutanalysisdialog.h"
#include "ui_dropoutanalysisdialog.h"

DropoutAnalysisDialog::DropoutAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::DropoutAnalysisDialog)
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
    axisY.setTitleText("Dropout length (in dots)");
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

DropoutAnalysisDialog::~DropoutAnalysisDialog()
{
    delete ui;
}

void DropoutAnalysisDialog::updateChart(LdDecodeMetaData *ldDecodeMetaData)
{
    series.clear();

    qreal targetDataPoints = 500;
    qreal averageWidth = qRound(ldDecodeMetaData->getNumberOfFields() / targetDataPoints);
    if (averageWidth < 1) averageWidth = 1; // Ensure we don't divide by zero
    qint32 dataPoints = ldDecodeMetaData->getNumberOfFields() / static_cast<qint32>(averageWidth);
    qint32 fieldsPerDataPoint = ldDecodeMetaData->getNumberOfFields() / dataPoints;

    qint32 fieldNumber = 1;
    qint32 maximumDropoutLength = 0;
    for (qint32 dpCount = 0; dpCount < dataPoints; dpCount++) {
        qint32 doLength = 0;
        for (qint32 avCount = 0; avCount < fieldsPerDataPoint; avCount++) {
            LdDecodeMetaData::Field field = ldDecodeMetaData->getField(fieldNumber);

            if (field.dropOuts.startx.size() > 0) {
                // Calculate the total length of the dropouts
                for (qint32 i = 0; i < field.dropOuts.startx.size(); i++) {
                    doLength += field.dropOuts.endx[i] - field.dropOuts.startx[i];
                }
            }

            fieldNumber++;
        }

        // Calculate the average
        doLength = doLength / fieldsPerDataPoint;

        // Keep track of the maximum Y value
        if (doLength > maximumDropoutLength) maximumDropoutLength = doLength;

        // Add the result to the series
        series.append(fieldNumber, doLength);
    }

    // Update the chart
    chart.setTitle("Dropout loss analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");

    axisX.setMin(0);
    axisX.setTickCount(10);
    if (ldDecodeMetaData->getNumberOfFields() < 10) axisX.setMax(10);
    else axisX.setMax(ldDecodeMetaData->getNumberOfFields());

    axisY.setMin(0);
    axisY.setTickCount(10);
    if (maximumDropoutLength < 10) axisY.setMax(10);
    else axisY.setMax(maximumDropoutLength);


    chartView->repaint();
}
