/************************************************************************

    f2frame.h

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#ifndef F2FRAME_H
#define F2FRAME_H

#include <QCoreApplication>
#include <QDebug>
#include <QDataStream>

#include "f3frame.h"
#include "Datatypes/tracktime.h"

class F2Frame
{
    friend QDataStream &operator<<(QDataStream &, const F2Frame &);
    friend QDataStream &operator>>(QDataStream &, F2Frame &);

public:
    F2Frame();

    void setData(QByteArray dataParam, QByteArray erasuresParam, bool isDataValid);
    QByteArray getDataSymbols(void);
    QByteArray getErrorSymbols(void);
    bool getDataValid(void);

    void setDiscTime(TrackTime _discTime);
    void setTrackTime(TrackTime _trackTime);
    TrackTime getDiscTime(void);
    TrackTime getTrackTime(void);
    void setTrackNumber(qint32 _trackNumber);
    qint32 getTrackNumber(void);
    void setIsEncoderRunning(bool _isEncoderRunning);
    bool getIsEncoderRunning(void);

private:
    QByteArray dataSymbols;
    QByteArray errorSymbols;
    bool dataValid;

    TrackTime discTime;
    TrackTime trackTime;
    qint32 trackNumber;
    bool isEncoderRunning;
};

#endif // F2FRAME_H
