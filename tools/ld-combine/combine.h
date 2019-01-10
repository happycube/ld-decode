/************************************************************************

    combine.h

    ld-combine - Combine TBC files
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

#ifndef COMBINE_H
#define COMBINE_H

#include <QObject>

#include "sourcevideo.h"
#include "lddecodemetadata.h"

class Combine : public QObject
{
    Q_OBJECT
public:
    explicit Combine(QObject *parent = nullptr);

    bool process(QString primaryFilename, QString secondaryFilename, QString outputFilename);

signals:

public slots:

private:
    LdDecodeMetaData primaryLdDecodeMetaData;
    LdDecodeMetaData::VideoParameters primaryVideoParameters;
    LdDecodeMetaData secondaryLdDecodeMetaData;
    LdDecodeMetaData::VideoParameters secondaryVideoParameters;
};

#endif // COMBINE_H
