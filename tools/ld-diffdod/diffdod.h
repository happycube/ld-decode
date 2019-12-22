/************************************************************************

    diffdod.h

    ld-diffdod - TBC Differential Drop-Out Detection tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-diffdod is free software: you can redistribute it and/or
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

#include <QObject>
#include <QDebug>
#include <QFile>

#include "tbcsources.h"

class Diffdod : public QObject
{
    Q_OBJECT
public:
    explicit Diffdod(QObject *parent = nullptr);

    bool process(QVector<QString> inputFilenames, bool reverse,
                 qint32 dodThreshold, bool noLumaClip);

private:
    TbcSources tbcSources;

    bool loadInputTbcFiles(QVector<QString> inputFilenames, bool reverse);
};

#endif // DIFFDOD_H
