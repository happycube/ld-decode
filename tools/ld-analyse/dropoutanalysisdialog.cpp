#include "dropoutanalysisdialog.h"
#include "ui_dropoutanalysisdialog.h"

DropoutAnalysisDialog::DropoutAnalysisDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::DropoutAnalysisDialog)
{
    ui->setupUi(this);

    // Set up the line series
    series = new QLineSeries();

    // Set up the chart
    chart = new QChart();
    chart->legend()->hide();
    chart->addSeries(series);

    // Set up the X axis
    axisX = new QValueAxis();
    axisX->setTitleText("Field number");
    axisX->setLabelFormat("%i");
    axisX->setTickCount(series->count());
    chart->addAxis(axisX, Qt::AlignBottom);
    series->attachAxis(axisX);

    // Set up the Y axis
    axisY = new QValueAxis();
    axisY->setTitleText("Dropout length (in dots)");
    axisY->setLabelFormat("%i");
    axisY->setTickCount(1000);
    chart->addAxis(axisY, Qt::AlignLeft);
    series->attachAxis(axisY);

    // Set up the chart view
    chartView = new QChartView(chart);
    chartView->setRenderHint(QPainter::Antialiasing);
    ui->verticalLayout->addWidget(chartView);
}

DropoutAnalysisDialog::~DropoutAnalysisDialog()
{
    delete ui;
}

void DropoutAnalysisDialog::updateChart(LdDecodeMetaData *ldDecodeMetaData)
{
    chart->removeSeries(series);
    series->clear();

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
        series->append(fieldNumber, doLength);
    }

    chart->addSeries(series);
    chart->setTitle("Dropout loss analysis (averaged over " + QString::number(fieldsPerDataPoint) + " fields)");

    axisX->setTickCount(10);
    axisX->setMax(ldDecodeMetaData->getNumberOfFields());
    axisX->setMin(0);

    axisY->setTickCount(10);
    axisY->setMax(maximumDropoutLength);
    axisY->setMin(0);

    chartView->repaint();
}
