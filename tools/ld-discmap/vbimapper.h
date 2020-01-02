/************************************************************************

    vbimapper.h

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019 Simon Inns

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

#ifndef VBIMAPPER_H
#define VBIMAPPER_H

#include <QObject>
#include <QDebug>

// TBC library includes
#include "lddecodemetadata.h"
#include "vbidecoder.h"

class VbiMapper : public QObject
{
    Q_OBJECT
public:
    explicit VbiMapper(QObject *parent = nullptr);

    struct Frame {
        qint32 firstField;
        qint32 secondField;
        bool isMissing;
        bool isMarkedForDeletion;
        bool isCorruptVbi;
        qint32 vbiFrameNumber;
        qint32 syncConf;
        qint32 bSnr;
        qint32 dropOutLevel;

        // Override < to allow struct to be sorted
        bool operator < (const Frame& frame) const {
            return (vbiFrameNumber < frame.vbiFrameNumber);
        }
    };

    bool create(LdDecodeMetaData &ldDecodeMetaData);

    qint32 getNumberOfFrames();
    qint32 getStartFrame();
    qint32 getEndFrame();
    Frame getFrame(qint32 frameNumber);
    bool isDiscCav();

signals:

public slots:

private:
    bool isSourcePal;

    enum DiscType {
        discType_clv,
        discType_cav,
        discType_unknown
    };
    DiscType discType;

    QVector<Frame> frames;
    qint32 vbiStartFrameNumber;
    qint32 vbiEndFrameNumber;

    bool discCheck(LdDecodeMetaData &ldDecodeMetaData);
    bool createInitialMap(LdDecodeMetaData &ldDecodeMetaData);
    void correctFrameNumbering();
    void removeCorruptFrames();
    void removeDuplicateFrames();
    void detectMissingFrames();
    bool isNtscAmendment2ClvFrameNumber(qint32 frameNumber);
};

#endif // VBIMAPPER_H
