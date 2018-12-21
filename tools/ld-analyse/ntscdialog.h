/************************************************************************

    ntscdialog.h

    ld-analyse - TBC output analysis
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
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

#ifndef NTSCDIALOG_H
#define NTSCDIALOG_H

#include <QDialog>

#include "lddecodemetadata.h"

namespace Ui {
class NtscDialog;
}

class NtscDialog : public QDialog
{
    Q_OBJECT

public:
    explicit NtscDialog(QWidget *parent = nullptr);
    ~NtscDialog();

    void updateNtsc(LdDecodeMetaData::Field topField, LdDecodeMetaData::Field bottomField);

private:
    Ui::NtscDialog *ui;
};

#endif // NTSCDIALOG_H
