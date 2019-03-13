/************************************************************************

    tracktime.h

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

#ifndef TRACKTIME_H
#define TRACKTIME_H

#include <QCoreApplication>
#include <QDebug>

class TrackTime
{
public:
    TrackTime(qint32 minutesParam = 0, qint32 secondsParam = 0, qint32 framesParam = 0);

    struct Time {
        qint32 minutes;
        qint32 seconds;
        qint32 frames;
    };

    bool setTime(qint32 minutesParam, qint32 secondsParam, qint32 framesParam);
    bool setTime(TrackTime::Time timeParam);
    void addFrames(qint32 frames);
    Time getTime(void);
    QString getTimeAsQString(void);
    qint32 getFrames(void);

private:
    qint32 trackFrames;
};

#endif // TRACKTIME_H
