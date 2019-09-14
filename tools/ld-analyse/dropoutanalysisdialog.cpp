/************************************************************************

    dropoutanalysisdialog.cpp

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

#include "dropoutanalysisdialog.h"
#include "ui_dropoutanalysisdialog.h"

DropoutAnalysisDialog::DropoutAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::DropoutAnalysisDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    chartOwnsContents = false;
    maxY = 0;

    // Set up the chart view
    chartView.setChart(&chart);
    chartView.setRubberBand(QChartView::HorizontalRubberBand);
    chartView.setRenderHint(QPainter::Antialiasing);

    ui->verticalLayout->addWidget(&chartView);
}

DropoutAnalysisDialog::~DropoutAnalysisDialog()
{
    removeChartContents();
    delete ui;
}

// Get ready for an update
void DropoutAnalysisDialog::startUpdate()
{
    removeChartContents();
    qLineSeries.clear();

    // Create the QLineSeries
    qLineSeries.setColor(Qt::blue);

    maxY = 0;
}

// Remove the axes and series from the chart, giving ownership back to this object
void DropoutAnalysisDialog::removeChartContents()
{
    if (!chartOwnsContents) return;

    chart.removeAxis(&axisX);
    chart.removeAxis(&axisY);
    chart.removeSeries(&qLineSeries);

    chartOwnsContents = false;
}

// Add a data point to the chart
void DropoutAnalysisDialog::addDataPoint(qint32 fieldNumber, qreal doLength)
{
    qLineSeries.append(fieldNumber, doLength);
    // Keep track of the maximum Y value
    if (doLength > maxY) maxY = doLength;
}

// Finish the update and render the graph
void DropoutAnalysisDialog::finishUpdate(qint32 numberOfFields, qint32 fieldsPerDataPoint)
{
    // Create the chart
    chart.setTitle("Dropout loss analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");
    chart.legend()->hide();

    // Create the X axis
    axisX.setMin(0);
    axisX.setTickCount(10);
    if (numberOfFields < 10) axisX.setMax(10);
    else axisX.setMax(numberOfFields);
    axisX.setTitleText("Field number");
    axisX.setLabelFormat("%i");

    // Create the Y axis
    axisY.setMin(0);
    axisY.setTickCount(10);
    if (maxY < 10) axisY.setMax(10);
    else axisY.setMax(maxY);
    axisY.setTitleText("Dropout length (in dots)");
    axisY.setLabelFormat("%i");

    // Attach the axis to the chart
    chart.addAxis(&axisX, Qt::AlignBottom);
    chart.addAxis(&axisY, Qt::AlignLeft);

    // Attach the series to the chart
    chart.addSeries(&qLineSeries);

    // The chart now owns the axes and series
    chartOwnsContents = true;

    // Attach the axis to the QLineSeries
    qLineSeries.attachAxis(&axisX);
    qLineSeries.attachAxis(&axisY);

    // Render
    chartView.repaint();
}

void DropoutAnalysisDialog::on_reset_pushButton_clicked()
{
    chart.zoomReset();
}

