#ifndef CAPTUREQUALITYINDEXDIALOG_H
#define CAPTUREQUALITYINDEXDIALOG_H

#include <QDialog>

namespace Ui {
class CaptureQualityIndexDialog;
}

class CaptureQualityIndexDialog : public QDialog
{
    Q_OBJECT

public:
    explicit CaptureQualityIndexDialog(QWidget *parent = nullptr);
    ~CaptureQualityIndexDialog();

private:
    Ui::CaptureQualityIndexDialog *ui;
};

#endif // CAPTUREQUALITYINDEXDIALOG_H
