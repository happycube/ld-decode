/************************************************************************

    ntscprocess.h

    ld-process-ntsc - IEC NTSC specific processor for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-ntsc is free software: you can redistribute it and/or
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

#ifndef NTSCPROCESS_H
#define NTSCPROCESS_H

#include <QObject>

#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "fmcode.h"
#include "whiteflag.h"

class NtscProcess : public QObject
{
    Q_OBJECT
public:
    explicit NtscProcess(QObject *parent = nullptr);

    bool process(QString inputFileName);

signals:

public slots:

private:
    QByteArray getActiveVideoLine(SourceField *sourceField, qint32 fieldLine,
                                            LdDecodeMetaData::VideoParameters videoParameters);
};

#endif // NTSCPROCESS_H
