#ifndef DROPOUTANALYSISDIALOG_H
#define DROPOUTANALYSISDIALOG_H

#include <QDialog>
#include <QtCharts>

#include "lddecodemetadata.h"

using namespace QtCharts;

namespace Ui {
class DropoutAnalysisDialog;
}

class DropoutAnalysisDialog : public QDialog
{
    Q_OBJECT

public:
    explicit DropoutAnalysisDialog(QWidget *parent = nullptr);
    ~DropoutAnalysisDialog();

    void updateChart(LdDecodeMetaData *ldDecodeMetaData);

private:
    Ui::DropoutAnalysisDialog *ui;

    QChart *chart;
    QLineSeries *series;
    QChartView *chartView;
    QValueAxis *axisX;
    QValueAxis *axisY;
};

#endif // DROPOUTANALYSISDIALOG_H
