#include "capturequalityindexdialog.h"
#include "ui_capturequalityindexdialog.h"

CaptureQualityIndexDialog::CaptureQualityIndexDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::CaptureQualityIndexDialog)
{
    ui->setupUi(this);
}

CaptureQualityIndexDialog::~CaptureQualityIndexDialog()
{
    delete ui;
}
