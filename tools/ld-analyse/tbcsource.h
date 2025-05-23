/************************************************************************

    tbcsource.h

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2022 Simon Inns
    Copyright (C) 2021-2022 Adam Sampson

    This file is part of ld-decode-tools.

    ld-analyse is free software: you can redistribute it and/or
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

#ifndef TBCSOURCE_H
#define TBCSOURCE_H

#include <QObject>
#include <QImage>
#include <QPainter>
#include <QtConcurrent/QtConcurrent>
#include <QDebug>

// TBC library includes
#include "sourcevideo.h"
#include "lddecodemetadata.h"
#include "linenumber.h"
#include "vbidecoder.h"
#include "videoiddecoder.h"
#include "vitcdecoder.h"
#include "filters.h"

// Chroma decoder includes
#include "configuration.h"
#include "palcolour.h"
#include "comb.h"
#include "monodecoder.h"

class TbcSource : public QObject
{
    Q_OBJECT
public:
    explicit TbcSource(QObject *parent = nullptr);

    struct ScanLineData {
        QString systemDescription;
        LineNumber lineNumber;
        QVector<qint32> composite;
        QVector<qint32> luma;
        QVector<bool> isDropout;
        qint32 blackIre;
        qint32 whiteIre;
        qint32 fieldWidth;
        qint32 colourBurstStart;
        qint32 colourBurstEnd;
        qint32 activeVideoStart;
        qint32 activeVideoEnd;
        bool isActiveLine;
    };

    void loadSource(QString inputFileName);
    void unloadSource();
    bool getIsSourceLoaded();
    void saveSourceJson();
    QString getCurrentSourceFilename();
    QString getLastIOError();

    void setHighlightDropouts(bool _state);
    void setChromaDecoder(bool _state);
    void setFieldView(bool _state);
    void setFieldOrder(bool _state);
	void setCombine(bool _state);
    bool getHighlightDropouts();
    bool getChromaDecoder();
    bool getFieldOrder();

    enum ViewMode {
        FRAME_VIEW,
        SPLIT_VIEW,
        FIELD_VIEW,
    };
    void setViewMode(ViewMode viewMode);
    void setStretchField(bool _stretch);

    ViewMode getViewMode();
    bool getFrameViewEnabled();
    bool getFieldViewEnabled();
    bool getSplitViewEnabled();
    bool getStretchField();

    enum SourceMode {
        ONE_SOURCE,
        LUMA_SOURCE,
        CHROMA_SOURCE,
        BOTH_SOURCES,
    };
    SourceMode getSourceMode();
    void setSourceMode(SourceMode sourceMode);

    void load(qint32 frameNumber, qint32 fieldNumber);

    QImage getImage();
    qint32 getNumberOfFrames();
    qint32 getNumberOfFields();
    bool getIsWidescreen();
    VideoSystem getSystem();
    QString getSystemDescription();
    qint32 getFrameHeight();
    qint32 getFrameWidth();

    VbiDecoder::Vbi getFrameVbi();
    bool getIsFrameVbiValid();
    VideoIdDecoder::VideoId getFrameVideoId();
    bool getIsFrameVideoIdValid();
    VitcDecoder::Vitc getFrameVitc();
    bool getIsFrameVitcValid();

    QVector<double> getBlackSnrGraphData();
    QVector<double> getWhiteSnrGraphData();
    QVector<double> getDropOutGraphData();
    QVector<double> getVisibleDropOutGraphData();
    qint32 getGraphDataSize();

    bool getIsDropoutPresent();

    const LdDecodeMetaData::VideoParameters &getVideoParameters();
    void setVideoParameters(const LdDecodeMetaData::VideoParameters &videoParameters);

    const ComponentFrame &getComponentFrame();
    ScanLineData getScanLineData(qint32 scanLine);

    qint32 getFirstFieldNumber();
    qint32 getSecondFieldNumber();

    qint32 getCcData0();
    qint32 getCcData1();

    void setChromaConfiguration(const PalColour::Configuration &palConfiguration, const Comb::Configuration &ntscConfiguration,
                                const OutputWriter::Configuration &outputConfiguration);
    const PalColour::Configuration &getPalConfiguration();
    const Comb::Configuration &getNtscConfiguration();
    const MonoDecoder::MonoConfiguration &getMonoConfiguration();
    const OutputWriter::Configuration &getOutputConfiguration();

    qint32 startOfNextChapter(qint32 currentFrameNumber);
    qint32 startOfChapter(qint32 currentFrameNumber);

signals:
    void busy(QString information);
    void finishedLoading(bool success);
    void finishedSaving(bool success);

private slots:
    void finishBackgroundLoad();
    void finishBackgroundSave();

private:
    bool sourceReady;

    // Frame data
    QVector<double> blackSnrGraphData;
    QVector<double> whiteSnrGraphData;
    QVector<double> dropoutGraphData;
    QVector<double> visibleDropoutGraphData;

    // Image options
    bool chromaOn;
    bool dropoutsOn;
    bool reverseFoOn;
    bool stretchFieldOn;
    ViewMode viewMode;

    // Source globals
    SourceVideo sourceVideo;
    SourceVideo chromaSourceVideo;
    SourceMode sourceMode;
    LdDecodeMetaData ldDecodeMetaData;
    QString currentSourceFilename;
    QString currentJsonFilename;
    QString lastIOError;

    // Chroma decoder objects
    PalColour palColour;
    Comb ntscColour;
	MonoDecoder monoDecoder;
    OutputWriter outputWriter;

    // VBI decoders
    VbiDecoder vbiDecoder;
    VideoIdDecoder videoIdDecoder;
    VitcDecoder vitcDecoder;

    // Background loader globals
    QFutureWatcher<bool> watcher;
    QFuture<bool> future;

    // Metadata for the loaded frame
    qint32 firstFieldNumber, secondFieldNumber;
    LdDecodeMetaData::Field firstField, secondField;
    qint32 loadedFieldNumber, loadedFrameNumber;

    // Source fields needed to decode the loaded frame
    QVector<SourceField> inputFields;
    QVector<SourceField> chromaInputFields;
    qint32 inputStartIndex, inputEndIndex;
    bool inputFieldsValid;

    // Chroma decoder output for the loaded frame
    QVector<ComponentFrame> componentFrames;
    QVector<ComponentFrame> yFrames;
    QVector<ComponentFrame> cFrames;
    bool decodedFrameValid;

    // RGB image data for the loaded frame
    QImage cache;
    bool cacheValid;

    // Chroma decoder configuration
    PalColour::Configuration palConfiguration;
    Comb::Configuration ntscConfiguration;
	MonoDecoder::MonoConfiguration monoConfiguration;
    OutputWriter::Configuration outputConfiguration;
	bool combine = false;

    // Chapter map
    QVector<qint32> chapterMap;

    void resetState();
    void invalidateImageCache();
    void configureChromaDecoder();
    void loadInputFields();
    void decodeFrame();
    QImage generateQImage();
    QImage generateChromaImage();
    QImage generateMonoImage();
    void generateData();
    bool startBackgroundLoad(QString sourceFilename);
    bool startBackgroundSave(QString jsonFilename);
};

#endif // TBCSOURCE_H
