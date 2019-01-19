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

    bool process(QString primaryFilename, QString secondaryFilename, QString outputFilename, bool reverse);

signals:

public slots:

private:
    SourceVideo primarySourceVideo;
    SourceVideo secondarySourceVideo;

    LdDecodeMetaData primaryLdDecodeMetaData;
    LdDecodeMetaData::VideoParameters primaryVideoParameters;
    LdDecodeMetaData secondaryLdDecodeMetaData;
    LdDecodeMetaData::VideoParameters secondaryVideoParameters;

    LdDecodeMetaData outputLdDecodeMetaData;

    qint32 linesReplaced;
    qint32 dropoutsReplaced;
    qint32 failedReplaced;

    qint32 getMatchingSecondaryFrame(bool isDiscCav, qint32 seqFrameNumber, qint32 leadinOffset);

    qint32 getCavFrameNumber(qint32 frameSeqNumber, LdDecodeMetaData *ldDecodeMetaData);
    qint32 getClvFrameNumber(qint32 frameSeqNumber, LdDecodeMetaData *ldDecodeMetaData);

    QByteArray processField(qint32 primarySeqFieldNumber, qint32 secondarySeqFieldNumber);
    qint32 assessLineQuality(LdDecodeMetaData::Field field, qint32 lineNumber);
    QByteArray replaceVideoLineData(QByteArray primaryFieldData, QByteArray secondaryFieldData, qint32 lineNumber);
    QByteArray replaceVideoDropoutData(QByteArray primaryFieldData, QByteArray secondaryFieldData,
                                                qint32 lineNumber, qint32 startx, qint32 endx);
};

#endif // COMBINE_H
