/******************************************************************************
 * videoparametersdialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2022 Adam Sampson
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef VIDEOPARAMETERSDIALOG_H
#define VIDEOPARAMETERSDIALOG_H

#include <QAbstractButton>
#include <QDialog>

#include "lddecodemetadata.h"

namespace Ui {
class VideoParametersDialog;
}

class VideoParametersDialog : public QDialog
{
    Q_OBJECT

public:
    explicit VideoParametersDialog(QWidget *parent = nullptr);
    ~VideoParametersDialog();

    void setVideoParameters(const LdDecodeMetaData::VideoParameters &videoParameters);

signals:
    void videoParametersChanged(const LdDecodeMetaData::VideoParameters &videoParameters);

public slots:
    void levelSelected(qint32 level);

private slots:
    void on_blackLevelSpinBox_valueChanged(int value);
    void on_whiteLevelSpinBox_valueChanged(int value);
    void on_activeVideoStartSpinBox_valueChanged(int value);
    void on_activeVideoWidthSpinBox_valueChanged(int value);

    void on_blackLevelResetButton_clicked();
    void on_blackLevelAltResetButton_clicked();
    void on_whiteLevelResetButton_clicked();
    void on_activeVideoStartResetButton_clicked();
    void on_activeVideoWidthResetButton_clicked();

    void on_aspectRatioButtonGroup_buttonClicked(QAbstractButton *button);

private:
    Ui::VideoParametersDialog *ui;
    LdDecodeMetaData::VideoParameters videoParameters;
    qint32 originalActiveVideoStart = -1;
    qint32 originalActiveVideoWidth = -1;

    void updateDialog();
};

#endif // VIDEOPARAMETERSDIALOG_H
