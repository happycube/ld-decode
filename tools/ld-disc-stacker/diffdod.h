/************************************************************************

    diffdod.h

    ld-disc-stacker - Disc stacking for ld-decode
    Copyright (C) 2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-disc-stacker is free software: you can redistribute it and/or
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

#ifndef DIFFDOD_H
#define DIFFDOD_H

#include <QCoreApplication>
#include <QDebug>

class DiffDod
{
public:
    DiffDod();

    QVector<quint16> process(QVector<quint16> inputValues);

private:
    quint16 median(QVector<quint16> v);
};

#endif // DIFFDOD_H
