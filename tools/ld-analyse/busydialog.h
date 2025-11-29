/******************************************************************************
 * busydialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef BUSYDIALOG_H
#define BUSYDIALOG_H

#include <QDialog>

namespace Ui {
class BusyDialog;
}

class BusyDialog : public QDialog
{
    Q_OBJECT

public:
    explicit BusyDialog(QWidget *parent = nullptr);
    ~BusyDialog();

    void setMessage(QString message);

private:
    Ui::BusyDialog *ui;
};

#endif // BUSYDIALOG_H
