/************************************************************************

    lddecodemetadata.h

    ld-decode-tools TBC library
    Copyright (C) 2018-2020 Simon Inns
    Copyright (C) 2022 Ryan Holtz

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

#include <QVector>
#include <QTemporaryFile>
#include <QDebug>
#include <array>

#include "../JsonWax/JsonWax.h"
#include "vbidecoder.h"
#include "dropouts.h"

class LdDecodeMetaData
{

public:

    // VBI Metadata definition
    struct Vbi {
        bool inUse = false;
        std::array<qint32, 3> vbiData { 0, 0, 0 };
    };

    // Pseudo metadata items - these values are populated automatically by the library
    // if not otherwise specified by the user. These are half-open ranges, where lines are
    // numbered sequentially from 1 within each field or interlaced frame.
    struct LineParameters {
        void process(qint32 fieldHeight);

        qint32 firstActiveFieldLine = -1;
        qint32 lastActiveFieldLine = -1;
        qint32 firstActiveFrameLine = -1;
        qint32 lastActiveFrameLine = -1;

        static const qint32 sMinPALFirstActiveFrameLine;
        static const qint32 sDefaultPALFirstActiveFieldLine;
        static const qint32 sDefaultPALLastActiveFieldLine;
        static const qint32 sDefaultPALFirstActiveFrameLine;
        static const qint32 sDefaultPALLastActiveFrameLine;
        static const qint32 sDefaultPALFieldHeightCheck;

        static const qint32 sMinNTSCFirstActiveFrameLine;
        static const qint32 sDefaultNTSCFirstActiveFieldLine;
        static const qint32 sDefaultNTSCLastActiveFieldLine;
        static const qint32 sDefaultNTSCFirstActiveFrameLine;
        static const qint32 sDefaultNTSCLastActiveFrameLine;
        static const qint32 sDefaultNTSCFieldHeightCheck;

        static const qint32 sDefaultAutoFirstActiveFieldLine;
    };

    // Video metadata definition
    struct VideoParameters {
        qint32 numberOfSequentialFields = -1;

        bool isSourcePal = false;
        bool isSubcarrierLocked = false;
        bool isWidescreen = false;

        qint32 colourBurstStart = -1;
        qint32 colourBurstEnd = -1;
        qint32 activeVideoStart = -1;
        qint32 activeVideoEnd = -1;

        qint32 white16bIre = -1;
        qint32 black16bIre = -1;

        qint32 fieldWidth = -1;
        qint32 fieldHeight = -1;
        qint32 sampleRate = -1;
        qint32 fsc = -1;

        bool isMapped = false;

        QString gitBranch;
        QString gitCommit;

        // Copy of the members in LineParameters; filled in based on our LineParameters when retrieving VideoParameters
        qint32 firstActiveFieldLine = -1;
        qint32 lastActiveFieldLine = -1;
        qint32 firstActiveFrameLine = -1;
        qint32 lastActiveFrameLine = -1;

        // Flags if our data has been initialized yet
        bool isValid = false;
    };

    // VITS metrics metadata definition
    struct VitsMetrics {
        bool inUse = false;
        qreal wSNR = 0.0;
        qreal bPSNR = 0.0;

    };

    // NTSC Specific metadata definition
    struct Ntsc {
        bool inUse = false;
        bool isFmCodeDataValid = false;
        qint32 fmCodeData = 0;
        bool fieldFlag = false;
        bool whiteFlag = false;
        qint32 ccData0 = 0;
        qint32 ccData1 = 0;
    };

    // PCM sound metadata definition
    struct PcmAudioParameters {
        qint32 sampleRate = -1;
        bool isLittleEndian = false;
        bool isSigned = false;
        qint32 bits = -1;

        // Flags if our data has been initialized yet
        bool isValid = false;
    };

    // Field metadata definition
    struct Field {
        qint32 seqNo = 0;   // Note: This is the unique primary-key
        bool isFirstField = false;
        qint32 syncConf = 0;
        qreal medianBurstIRE = 0.0;
        qint32 fieldPhaseID = 0;
        qint32 audioSamples = 0;

        VitsMetrics vitsMetrics;
        Vbi vbi;
        Ntsc ntsc;
        DropOuts dropOuts;
        bool pad = false;

        qint32 diskLoc = -1;
        qint32 fileLoc = -1;
        qint32 decodeFaults = -1;
        qint32 efmTValues = -1;
    };

    // CLV timecode (used by frame number conversion methods)
    struct ClvTimecode {
        qint32 hours;
        qint32 minutes;
        qint32 seconds;
        qint32 pictureNumber;
    };

    LdDecodeMetaData();

    // Prevent copying or assignment
    LdDecodeMetaData(const LdDecodeMetaData &) = delete;
    LdDecodeMetaData& operator=(const LdDecodeMetaData &) = delete;

    bool read(QString fileName);
    bool write(QString fileName);

    VideoParameters getVideoParameters();
    void setVideoParameters(VideoParameters _videoParameters);

    PcmAudioParameters getPcmAudioParameters();
    void setPcmAudioParameters(PcmAudioParameters _pcmAudioParam);

    // Handle line parameters
    void processLineParameters(LdDecodeMetaData::LineParameters &_lineParameters);

    // Get field metadata
    Field getField(qint32 sequentialFieldNumber);
    VitsMetrics getFieldVitsMetrics(qint32 sequentialFieldNumber);
    Vbi getFieldVbi(qint32 sequentialFieldNumber);
    Ntsc getFieldNtsc(qint32 sequentialFieldNumber);
    DropOuts getFieldDropOuts(qint32 sequentialFieldNumber);

    // Set field metadata
    void updateField(Field _field, qint32 sequentialFieldNumber);
    void updateFieldVitsMetrics(LdDecodeMetaData::VitsMetrics _vitsMetrics, qint32 sequentialFieldNumber);
    void updateFieldVbi(LdDecodeMetaData::Vbi _vbi, qint32 sequentialFieldNumber);
    void updateFieldNtsc(LdDecodeMetaData::Ntsc _ntsc, qint32 sequentialFieldNumber);
    void updateFieldDropOuts(DropOuts _dropOuts, qint32 sequentialFieldNumber);
    void clearFieldDropOuts(qint32 sequentialFieldNumber);

    void appendField(Field _field);

    void setNumberOfFields(qint32 numberOfFields);
    qint32 getNumberOfFields();
    qint32 getNumberOfFrames();
    qint32 getFirstFieldNumber(qint32 frameNumber);
    qint32 getSecondFieldNumber(qint32 frameNumber);

    void setIsFirstFieldFirst(bool flag);
    bool getIsFirstFieldFirst();

    qint32 convertClvTimecodeToFrameNumber(LdDecodeMetaData::ClvTimecode clvTimeCode);
    LdDecodeMetaData::ClvTimecode convertFrameNumberToClvTimecode(qint32 clvFrameNumber);

    // PCM Analogue audio helper methods
    qint32 getFieldPcmAudioStart(qint32 sequentialFieldNumber);
    qint32 getFieldPcmAudioLength(qint32 sequentialFieldNumber);

private:
    JsonWax json;
    bool isFirstFieldFirst;
    VideoParameters videoParameters;
    LineParameters lineParameters;
    PcmAudioParameters pcmAudioParameters;
    QVector<qint32> pcmAudioFieldStartSampleMap;
    QVector<qint32> pcmAudioFieldLengthMap;

    qint32 getFieldNumber(qint32 frameNumber, qint32 field);
    void generatePcmAudioMap();
};

#endif // LDDECODEMETADATA_H
