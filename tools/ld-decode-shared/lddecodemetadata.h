/************************************************************************

    lddecodemetadata.h

    ld-decode-tools shared library
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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

#ifndef LDDECODEMETADATA_H
#define LDDECODEMETADATA_H

#include "ld-decode-shared_global.h"

#include <QObject>
#include <QVector>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QFile>
#include <QDebug>

class LDDECODESHAREDSHARED_EXPORT LdDecodeMetaData : public QObject
{
    Q_OBJECT
public:

    // VBI Metadata definition
    enum VbiDiscTypes {
        unknownDiscType,    // 0
        clv,                // 1
        cav                 // 2
    };

    struct vbiTimeCode {
        qint32 hr;
        qint32 min;
    };

    // VBI Sound modes
    enum VbiSoundModes {
        stereo,                 // 0
        mono,                   // 1
        audioSubCarriersOff,    // 2
        bilingual,              // 3
        stereo_stereo,          // 4
        stereo_bilingual,       // 5
        crossChannelStereo,     // 6
        bilingual_bilingual,    // 7
        mono_dump,              // 8
        stereo_dump,            // 9
        bilingual_dump,         // 10
        futureUse               // 11
    };

    struct vbiStatusCode {
        bool valid;                 // Ture = programme status code is valid
        bool cx;                    // True = CX on, false = CX off
        bool size;                  // True = 12" disc, false = 8" disc
        bool side;                  // True = first side, false = second side
        bool teletext;              // True = teletext present, false = teletext not present
        bool dump;                  // True = programme dump on, false = programme dump off
        bool fm;                    // True = FM-FM Multiplex on, false = FM-FM Multiplex off
        bool digital;               // True = digital video, false = analogue video
        VbiSoundModes soundMode;    // The sound mode (see IEC spec)
        bool parity;                // True = status code had valid parity, false = status code is invalid
    };

    struct vbiStatusCodeAm2 {
        bool valid;                 // Ture = programme status code is valid
        bool cx;                    // True = CX on, false = CX off
        bool size;                  // True = 12" disc, false = 8" disc
        bool side;                  // True = first side, false = second side
        bool teletext;              // True = teletext present, false = teletext not present
        bool copy;                  // True = copy allowed, false = copy not allowed
        bool standard;              // True = video signal is standard, false = video signal is future use
        VbiSoundModes soundMode;    // The sound mode (see IEC spec amendment 2)
    };

    struct VbiClvPictureNumber {
        qint32 sec;
        qint32 picNo;
    };

    // Overall container struct for VBI information
    struct Vbi {
        bool inUse;

        qint32 vbi16;
        qint32 vbi17;
        qint32 vbi18;

        VbiDiscTypes type;
        bool leadIn;
        bool leadOut;
        QString userCode;
        qint32 picNo;
        bool picStop;
        qint32 chNo;
        vbiTimeCode timeCode;
        vbiStatusCode statusCode;
        vbiStatusCodeAm2 statusCodeAm2;
        VbiClvPictureNumber clvPicNo;
    };

    // Video metadata definition
    struct VideoParameters {
        qint32 numberOfSequentialFields;

        bool isSourcePal;

        qint32 colourBurstStart;
        qint32 colourBurstEnd;
        qint32 blackLevelStart;
        qint32 blackLevelEnd;
        qint32 activeVideoStart;
        qint32 activeVideoEnd;

        qint32 white16bIre;
        qint32 black16bIre;

        qreal samplesPerUs;

        qint32 fieldWidth;
        qint32 fieldHeight;
        qint32 sampleRate;
        qint32 fsc;
    };

    // Drop-outs metadata definition
    struct DropOuts {
        QVector<qint32> startx;
        QVector<qint32> endx;
        QVector<qint32> fieldLine;
    };

    // VITS metadata definition
    struct Vits {
        bool inUse;
        qreal snr;
    };

    // NTSC Specific metadata definition
    struct Ntsc {
        bool inUse;
        bool isFmCodeDataValid;
        qint32 fmCodeData;
        bool fieldFlag;
        bool whiteFlag;
    };

    // PCM sound metadata definition
    struct PcmAudioParameters {
        qint32 sampleRate;
        bool isLittleEndian;
        bool isSigned;
        qint32 bits;
    };

    // Field metadata definition
    struct Field {
        qint32 seqNo;       // Note: This is the unique primary-key
        bool isFirstField;
        qint32 syncConf;
        qreal medianBurstIRE;
        qint32 fieldPhaseID;

        Vits vits;
        Vbi vbi;
        Ntsc ntsc;
        DropOuts dropOuts;
    };

    // Overall metadata definition
    struct MetaData {
        VideoParameters videoParameters;
        PcmAudioParameters pcmAudioParameters;
        QVector<Field> fields;
    };

    explicit LdDecodeMetaData(QObject *parent = nullptr);

    bool read(QString fileName);
    bool write(QString fileName);

    VideoParameters getVideoParameters(void);
    void setVideoParameters (VideoParameters videoParametersParam);

    PcmAudioParameters getPcmAudioParameters(void);
    void setPcmAudioParameters(PcmAudioParameters pcmAudioParam);

    Field getField(qint32 sequentialFieldNumber);
    void appendField(Field fieldParam);
    void updateField(Field fieldParam, qint32 sequentialFrameNumber);

    qint32 getNumberOfFields(void);
    qint32 getNumberOfFrames(void);
    qint32 getFirstFieldNumber(qint32 frameNumber);
    qint32 getSecondFieldNumber(qint32 frameNumber);

signals:

public slots:

private:
    bool isMetaDataValid;
    MetaData metaData;
    qint32 getFieldNumber(qint32 frameNumber, qint32 field);
};

#endif // LDDECODEMETADATA_H
