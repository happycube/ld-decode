/******************************************************************************
 * closedcaptionsdialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef CLOSEDCAPTIONSDIALOG_H
#define CLOSEDCAPTIONSDIALOG_H

#include <QDialog>
#include <QDebug>

namespace Ui {
class ClosedCaptionsDialog;
}

class ClosedCaptionsDialog : public QDialog
{
    Q_OBJECT

public:
    explicit ClosedCaptionsDialog(QWidget *parent = nullptr);
    ~ClosedCaptionsDialog();

    void addData(qint32 frameNumber, qint32 data0, qint32 data1);

private:
    Ui::ClosedCaptionsDialog *ui;
    bool waitingForPreamble;
    qint32 lastFrameNumber;

    qint32 lastNonDisplayCommand;
    qint32 lastDisplayCommand;

    void processCommand(qint32 data0, qint32 data1);
    void resetCaptions();
};

#endif // CLOSEDCAPTIONSDIALOG_H
