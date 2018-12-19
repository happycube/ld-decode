/************************************************************************

    dropoutdetector.cpp

    ld-dropout-detect - Dropout detection for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-detect is free software: you can redistribute it and/or
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

#ifndef DROPOUTDETECTOR_H
#define DROPOUTDETECTOR_H

#include <QObject>

#include "sourcevideo.h"
#include "lddecodemetadata.h"

class DropOutDetector : public QObject
{
    Q_OBJECT
public:
    explicit DropOutDetector(QObject *parent = nullptr);

    bool process(QString inputFileName);

signals:

public slots:

private:
    // Drop-out correction parameters
    struct DocConfiguration {
        qint32 postTriggerWidth;
        qint32 preTriggerReplacement;
        qint32 postTriggerReplacement;
    };

    DocConfiguration docConfiguration;

    LdDecodeMetaData::DropOuts detectDropOuts(QByteArray sourceFieldData, LdDecodeMetaData::VideoParameters videoParameters);
};

#endif // DROPOUTDETECTOR_H
