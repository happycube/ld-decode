#include "aboutdialog.h"
#include "ui_aboutdialog.h"

AboutDialog::AboutDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::AboutDialog)
{
    ui->setupUi(this);

    ui->gitVersionLabel->setText(QString("Build - Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
}

AboutDialog::~AboutDialog()
{
    delete ui;
}
