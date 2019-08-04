/************************************************************************

    discmap.h

    ld-combine - TBC combination and enhancement tool
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

#ifndef DISCMAP_H
#define DISCMAP_H

#include <QObject>
#include <QDebug>

// TBC library includes
#include "lddecodemetadata.h"
#include "vbidecoder.h"

class DiscMap : public QObject
{
    Q_OBJECT
public:
    explicit DiscMap(QObject *parent = nullptr);

    bool create(LdDecodeMetaData &ldDecodeMetaData);
    QStringList getReport();

signals:

public slots:

private:
    bool isSourcePal;
    QStringList mapReport;

    enum DiscType {
        discType_clv,
        discType_cav,
        discType_unknown
    };
    DiscType discType;

    struct Frame {
        qint32 firstField;
        qint32 secondField;
        bool isMissing;
        bool isLeadInOrOut;
        bool isMarkedForDeletion;
        qint32 vbiFrameNumber;
        qint32 syncConf;
        qint32 bSnr;
        qint32 dropOutLevel;

        // Override < to allow struct to be sorted
        bool operator < (const Frame& frame) const {
            return (vbiFrameNumber < frame.vbiFrameNumber);
        }
    };
    QVector<Frame> frames;

    bool sanityCheck(LdDecodeMetaData &ldDecodeMetaData);
    bool createInitialMap(LdDecodeMetaData &ldDecodeMetaData);
    void correctFrameNumbering();
    void removeDuplicateFrames();
    void detectMissingFrames();
};

#endif // DISCMAP_H
