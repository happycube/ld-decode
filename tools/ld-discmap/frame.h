/************************************************************************

    frame.h

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019-2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-discmap is free software: you can redistribute it and/or
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

#ifndef FRAME_H
#define FRAME_H

#include <QCoreApplication>
#include <QDebug>

class Frame
{
public:
    Frame(const qint32 &seqFrameNumber = -1, const qint32 &vbiFrameNumber = -1, const bool &isPictureStop = false,
          const bool &isPullDown = false, const bool &isLeadInOrOut = false, const bool &isMarkedForDeletion = false,
          const qreal &frameQuality = 0, const bool &isPadded = false);
    ~Frame() = default;
    Frame(const Frame &) = default;
    Frame &operator =(const Frame &) = default;

    // Get
    qint32 seqFrameNumber() const;
    qint32 vbiFrameNumber() const;
    bool isPictureStop() const;
    bool isPullDown() const;
    bool isLeadInOrOut() const;
    bool isMarkedForDeletion() const;
    qreal frameQuality() const;
    bool isPadded() const;

    // Set
    void seqFrameNumber(qint32 value);
    void vbiFrameNumber(qint32 value);
    void isPictureStop(bool value);
    void isPullDown(bool value);
    void isLeadInOrOut(bool value);
    void isMarkedForDeletion(bool value);
    void frameQuality(qreal value);
    void isPadded(bool value);

    // Operators
    bool operator <(const Frame &);

private:
    qint32 m_seqFrameNumber;
    qint32 m_vbiFrameNumber;
    bool m_isPictureStop;
    bool m_isPullDown;
    bool m_isLeadInOrOut;
    bool m_isMarkedForDeletion;
    qreal m_frameQuality;
    bool m_isPadded;
};

// Custom streaming operator for debug
QDebug operator<<(QDebug dbg, const Frame &frame);

// Custom meta-type declaration
Q_DECLARE_METATYPE(Frame);

#endif // FRAME_H
