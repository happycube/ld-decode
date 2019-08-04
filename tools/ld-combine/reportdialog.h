/************************************************************************

    reportdialog.h

    ld-combine - TBC combination and enhancement tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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

#ifndef REPORTDIALOG_H
#define REPORTDIALOG_H

#include <QDialog>

namespace Ui {
class ReportDialog;
}

class ReportDialog : public QDialog
{
    Q_OBJECT

public:
    explicit ReportDialog(QWidget *parent = nullptr);
    ~ReportDialog();

    void clearReport();
    void showReport(QStringList report);

private:
    Ui::ReportDialog *ui;
};

#endif // REPORTDIALOG_H
