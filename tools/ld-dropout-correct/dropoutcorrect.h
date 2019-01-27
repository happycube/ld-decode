/************************************************************************

    dropoutcorrect.h

    ld-dropout-correct - Dropout correction for ld-decode
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

#ifndef DROPOUTCORRECT_H
#define DROPOUTCORRECT_H

#include <QObject>

#include "sourcevideo.h"
#include "lddecodemetadata.h"

class DropOutCorrect : public QObject
{
    Q_OBJECT
public:
    explicit DropOutCorrect(QObject *parent = nullptr);
    bool process(QString inputFileName, QString outputFileName, bool reverse);

signals:

public slots:

private:
    enum Location {
        visibleLine,
        colourBurst,
        unknown
    };

    struct DropOutLocation {
        qint32 fieldLine;
        qint32 startx;
        qint32 endx;
        Location location;
    };

    struct Replacement {
        bool isFirstField;
        qint32 fieldLine;
    };

    LdDecodeMetaData ldDecodeMetaData;
    LdDecodeMetaData::VideoParameters videoParameters;

    QVector<DropOutLocation> populateDropoutsVector(LdDecodeMetaData::Field field);
    QVector<DropOutLocation> setDropOutLocations(QVector<DropOutLocation> dropOuts);
    Replacement findReplacementLine(QVector<DropOutLocation>firstFieldDropouts, QVector<DropOutLocation> secondFieldDropouts, qint32 dropOutIndex, bool isColourBurst);
};

#endif // DROPOUTCORRECT_H
