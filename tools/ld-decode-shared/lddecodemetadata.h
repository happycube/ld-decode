/************************************************************************

    lddecodemetadata.h

    ld-decode-tools shared library
    Copyright (C) 2018-2019 Simon Inns

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
//#include <QJsonDocument>
//#include <QJsonObject>
//#include <QJsonArray>
//#include <QFile>
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

    // Overall container struct for VBI information
    struct Vbi {
        bool inUse;

        QVector<qint32> vbiData;
        VbiDiscTypes type;
        QString userCode;
        qint32 picNo;
        qint32 chNo;
        qint32 clvHr;
        qint32 clvMin;
        qint32 clvSec;
        qint32 clvPicNo;
        VbiSoundModes soundMode;
        VbiSoundModes soundModeAm2;

        // Note: These booleans are virtual (and stored in a single int)
        bool leadIn;
        bool leadOut;
        bool picStop;
        bool cx;
        bool size;
        bool side;
        bool teletext;
        bool dump;
        bool fm;
        bool digital;
        bool parity;
        bool copyAm2;
        bool standardAm2;
    };

    // Video metadata definition
    struct VideoParameters {
        qint32 numberOfSequentialFields;

        bool isSourcePal;

        qint32 colourBurstStart;
        qint32 colourBurstEnd;
        qint32 activeVideoStart;
        qint32 activeVideoEnd;

        qint32 white16bIre;
        qint32 black16bIre;

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

    // VITS metrics metadata definition
    struct VitsMetrics {
        bool inUse;
        qreal whiteSNR;
        qreal whiteIRE;
        qreal whiteRFLevel;
        qreal greyPSNR;
        qreal greyIRE;
        qreal greyRFLevel;
        qreal blackLinePreTBCIRE;
        qreal blackLinePostTBCIRE;
        qreal blackLinePSNR;
        qreal blackLineRFLevel;
        qreal syncLevelPSNR;
        qreal syncRFLevel;
        qreal syncToBlackRFRatio;
        qreal syncToWhiteRFRatio;
        qreal blackToWhiteRFRatio;
        qreal ntscWhiteFlagSNR;
        qreal ntscWhiteFlagRFLevel;
        qreal ntscLine19Burst0IRE;
        qreal ntscLine19Burst70IRE;
        qreal ntscLine19ColorPhase;
        qreal ntscLine19ColorRawSNR;
        qreal ntscLine19Color3DPhase;
        qreal ntscLine19Color3DRawSNR;
        qreal palVITSBurst50Level;
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
        qint32 audioSamples;

        VitsMetrics vitsMetrics;
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

    // CLV timecode (used by frame number conversion methods)
    struct ClvTimecode {
        qint32 hours;
        qint32 minutes;
        qint32 seconds;
        qint32 pictureNumber;
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
    void updateField(Field fieldParam, qint32 sequentialFieldNumber);

    qint32 getNumberOfFields(void);
    qint32 getNumberOfFrames(void);
    qint32 getFirstFieldNumber(qint32 frameNumber);
    qint32 getSecondFieldNumber(qint32 frameNumber);

    void setIsFirstFieldFirst(bool flag);
    bool getIsFirstFieldFirst(void);

    VbiDiscTypes getDiscTypeFromVbi(void);

    qint32 convertClvTimecodeToFrameNumber(LdDecodeMetaData::ClvTimecode clvTimeCode);
    LdDecodeMetaData::ClvTimecode convertFrameNumberToClvTimecode(qint32 clvFrameNumber);

signals:

public slots:

private:
    bool isMetaDataValid;
    MetaData metaData;
    bool isFirstFieldFirst;
    qint32 getFieldNumber(qint32 frameNumber, qint32 field);
};

#endif // LDDECODEMETADATA_H
