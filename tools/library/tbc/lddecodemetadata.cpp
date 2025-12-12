/******************************************************************************
 * lddecodemetadata.cpp
 * ld-decode-tools TBC library
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 * SPDX-FileCopyrightText: 2022 Ryan Holtz
 * SPDX-FileCopyrightText: 2022-2023 Adam Sampson
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "lddecodemetadata.h"

#include "sqliteio.h"

#include <cassert>
#include <stdexcept>
#include <QFileInfo>
#include <QDebug>
#include <QMap>
#include <QMultiMap>
#include <QVariant>
#include "tbc/logging.h"

// Default values used when configuring VideoParameters for a particular video system.
// See the comments in VideoParameters for the meanings of these values.
// For descriptions of the systems, see ITU BT.1700.
struct VideoSystemDefaults {
    VideoSystem system;
    const char *name;
    double fSC;
    qint32 minActiveFrameLine;
    qint32 firstActiveFieldLine;
    qint32 lastActiveFieldLine;
    qint32 firstActiveFrameLine;
    qint32 lastActiveFrameLine;
};

static constexpr VideoSystemDefaults palDefaults {
    PAL,
    "PAL",
    (283.75 * 15625) + 25,
    2,
    22, 308,
    // Interlaced line 44 is PAL line 23 (the first active half-line)
    // Interlaced line 619 is PAL line 623 (the last active half-line)
    44, 620,
};

static constexpr VideoSystemDefaults ntscDefaults {
    NTSC,
    "NTSC",
    315.0e6 / 88.0,
    1,
    20, 259,
    // Interlaced line 40 is NTSC line 21 (the closed-caption line before the first active half-line)
    // Interlaced line 524 is NTSC line 263 (the last active half-line)
    40, 525,
};

static constexpr VideoSystemDefaults palMDefaults {
    PAL_M,
    "PAL-M",
    5.0e6 * (63.0 / 88.0) * (909.0 / 910.0),
    ntscDefaults.minActiveFrameLine,
    ntscDefaults.firstActiveFieldLine, ntscDefaults.lastActiveFieldLine,
    ntscDefaults.firstActiveFrameLine, ntscDefaults.lastActiveFrameLine,
};

// These must be in the same order as enum VideoSystem
static constexpr VideoSystemDefaults VIDEO_SYSTEM_DEFAULTS[] = {
    palDefaults,
    ntscDefaults,
    palMDefaults,
};

// Return appropriate defaults for the selected video system
static const VideoSystemDefaults &getSystemDefaults(const LdDecodeMetaData::VideoParameters &videoParameters)
{
    return VIDEO_SYSTEM_DEFAULTS[videoParameters.system];
}

// Look up a video system by name.
// Return true and set system if found; if not found, return false.
bool parseVideoSystemName(QString name, VideoSystem &system)
{
    // Search VIDEO_SYSTEM_DEFAULTS for a matching name
    for (const auto &defaults: VIDEO_SYSTEM_DEFAULTS) {
        if (name == defaults.name) {
            system = defaults.system;
            return true;
        }
    }
    return false;
}

// Read VBI from SQLite
void LdDecodeMetaData::Vbi::read(SqliteReader &reader, int captureId, int fieldId)
{
    int vbi0, vbi1, vbi2;
    if (reader.readFieldVbi(captureId, fieldId, vbi0, vbi1, vbi2)) {
        vbiData[0] = vbi0;
        vbiData[1] = vbi1;
        vbiData[2] = vbi2;
        inUse = true;
    } else {
        inUse = false;
    }
}

// Write VBI to SQLite
void LdDecodeMetaData::Vbi::write(SqliteWriter &writer, int captureId, int fieldId) const
{
    if (inUse) {
        writer.writeFieldVbi(captureId, fieldId, vbiData[0], vbiData[1], vbiData[2]);
    }
}

// Read VideoParameters from SQLite (handled in main read method)
void LdDecodeMetaData::VideoParameters::read(SqliteReader &reader, int captureId)
{
    // This method is no longer used - data is read directly in LdDecodeMetaData::read
}

// Write VideoParameters to SQLite (handled in main write method)
void LdDecodeMetaData::VideoParameters::write(SqliteWriter &writer, int captureId) const
{
    // This method is no longer used - data is written directly in LdDecodeMetaData::write
}

// Read VitsMetrics from SQLite
void LdDecodeMetaData::VitsMetrics::read(SqliteReader &reader, int captureId, int fieldId)
{
    double wSnr, bPsnr;
    if (reader.readFieldVitsMetrics(captureId, fieldId, wSnr, bPsnr)) {
        this->wSNR = wSnr;
        this->bPSNR = bPsnr;
        inUse = true;
    } else {
        inUse = false;
    }
}

// Write VitsMetrics to SQLite
void LdDecodeMetaData::VitsMetrics::write(SqliteWriter &writer, int captureId, int fieldId) const
{
    if (inUse) {
        writer.writeFieldVitsMetrics(captureId, fieldId, wSNR, bPSNR);
    }
}

// Read Ntsc from SQLite (data is read from main field record)
void LdDecodeMetaData::Ntsc::read(SqliteReader &reader, int captureId, int fieldId, ClosedCaption &closedCaption)
{
    // NTSC data is read directly from the field_record table in readFields
    // Closed caption is read separately
    closedCaption.read(reader, captureId, fieldId);
}

// Write Ntsc to SQLite (data is written to main field record)
void LdDecodeMetaData::Ntsc::write(SqliteWriter &writer, int captureId, int fieldId) const
{
    // NTSC data is written directly to the field_record table in Field::write
    // This method is essentially a no-op since the data is handled elsewhere
}

// Read Vitc from SQLite
void LdDecodeMetaData::Vitc::read(SqliteReader &reader, int captureId, int fieldId)
{
    int vitcDataArray[8];
    if (reader.readFieldVitc(captureId, fieldId, vitcDataArray)) {
        for (int i = 0; i < 8; i++) {
            vitcData[i] = vitcDataArray[i];
        }
        inUse = true;
    } else {
        inUse = false;
    }
}

// Write Vitc to SQLite
void LdDecodeMetaData::Vitc::write(SqliteWriter &writer, int captureId, int fieldId) const
{
    if (inUse) {
        int vitcDataArray[8];
        for (int i = 0; i < 8; i++) {
            vitcDataArray[i] = vitcData[i];
        }
        writer.writeFieldVitc(captureId, fieldId, vitcDataArray);
    }
}

// Read ClosedCaption from SQLite
void LdDecodeMetaData::ClosedCaption::read(SqliteReader &reader, int captureId, int fieldId)
{
    int data0Val, data1Val;
    if (reader.readFieldClosedCaption(captureId, fieldId, data0Val, data1Val)) {
        data0 = data0Val;
        data1 = data1Val;
        inUse = true;
    } else {
        inUse = false;
    }
}

// Write ClosedCaption to SQLite
void LdDecodeMetaData::ClosedCaption::write(SqliteWriter &writer, int captureId, int fieldId) const
{
    if (inUse) {
        writer.writeFieldClosedCaption(captureId, fieldId, data0, data1);
    }
}

// Read PcmAudioParameters from SQLite (handled in main read method)
void LdDecodeMetaData::PcmAudioParameters::read(SqliteReader &reader, int captureId)
{
    // This method is no longer used - data is read directly in LdDecodeMetaData::read
}

// Write PcmAudioParameters to SQLite (handled in main write method)
void LdDecodeMetaData::PcmAudioParameters::write(SqliteWriter &writer, int captureId) const
{
    // This method is no longer used - data is written directly in LdDecodeMetaData::write
}

// Read Field from SQLite (data is read in readFields)
void LdDecodeMetaData::Field::read(SqliteReader &reader, int captureId)
{
    // This method is no longer used - data is read directly in LdDecodeMetaData::readFields
}

// Write Field to SQLite
void LdDecodeMetaData::Field::write(SqliteWriter &writer, int captureId) const
{
    // Convert seqNo (1-indexed) to fieldId (0-indexed)
    int fieldId = seqNo - 1;
    
    // Write main field record with NTSC data embedded
    writer.writeField(captureId, fieldId, audioSamples, decodeFaults, diskLoc,
                     efmTValues, fieldPhaseID, fileLoc, isFirstField, medianBurstIRE,
                     pad, syncConf, ntsc.isFmCodeDataValid, ntsc.fmCodeData,
                     ntsc.fieldFlag, ntsc.isVideoIdDataValid, ntsc.videoIdData,
                     ntsc.whiteFlag);

    // Write optional field data
    vitsMetrics.write(writer, captureId, fieldId);
    vbi.write(writer, captureId, fieldId);
    vitc.write(writer, captureId, fieldId);
    closedCaption.write(writer, captureId, fieldId);
    dropOuts.write(writer, captureId, fieldId);
}

LdDecodeMetaData::LdDecodeMetaData()
{
    clear();
}

// Reset the metadata to the defaults
void LdDecodeMetaData::clear()
{
    // Default to the standard still-frame field order (of first field first)
    isFirstFieldFirst = true;

    // Reset the parameters to their defaults
    videoParameters = VideoParameters();
    pcmAudioParameters = PcmAudioParameters();

    fields.clear();
}

// Read all metadata from SQLite file
bool LdDecodeMetaData::read(QString fileName)
{
    if (!QFileInfo::exists(fileName)) {
        qCritical() << "SQLite input file does not exist:" << fileName;
        return false;
    }

    clear();

    try {
        SqliteReader reader(fileName);
        
        int captureId;
        QString system, decoder, gitBranch, gitCommit, captureNotes;
        double videoSampleRate;
        int activeVideoStart, activeVideoEnd, fieldWidth, fieldHeight, numberOfSequentialFields;
        int colourBurstStart, colourBurstEnd, white16bIre, black16bIre;
        bool isMapped, isSubcarrierLocked, isWidescreen;

        // Read capture metadata
        if (!reader.readCaptureMetadata(captureId, system, decoder, gitBranch, gitCommit,
                                       videoSampleRate, activeVideoStart, activeVideoEnd,
                                       fieldWidth, fieldHeight, numberOfSequentialFields,
                                       colourBurstStart, colourBurstEnd, isMapped,
                                       isSubcarrierLocked, isWidescreen, white16bIre,
                                       black16bIre, captureNotes)) {
            qCritical() << "Failed to read capture metadata from SQLite file";
            return false;
        }

        // Set video parameters
        videoParameters.numberOfSequentialFields = numberOfSequentialFields;
        if (!parseVideoSystemName(system, videoParameters.system)) {
            qCritical() << "Unknown video system:" << system;
            return false;
        }
        videoParameters.isSubcarrierLocked = isSubcarrierLocked;
        videoParameters.isWidescreen = isWidescreen;
        videoParameters.colourBurstStart = colourBurstStart;
        videoParameters.colourBurstEnd = colourBurstEnd;
        videoParameters.activeVideoStart = activeVideoStart;
        videoParameters.activeVideoEnd = activeVideoEnd;
        videoParameters.white16bIre = white16bIre;
        videoParameters.black16bIre = black16bIre;
        videoParameters.fieldWidth = fieldWidth;
        videoParameters.fieldHeight = fieldHeight;
        videoParameters.sampleRate = videoSampleRate;
        videoParameters.isMapped = isMapped;
        videoParameters.tapeFormat = captureNotes;
        videoParameters.gitBranch = gitBranch;
        videoParameters.gitCommit = gitCommit;
        videoParameters.isValid = true;

        // Read PCM audio parameters if they exist
        int bits;
        bool isSigned, isLittleEndian;
        double audioSampleRate;
        if (reader.readPcmAudioParameters(captureId, bits, isSigned, isLittleEndian, audioSampleRate)) {
            pcmAudioParameters.bits = bits;
            pcmAudioParameters.isSigned = isSigned;
            pcmAudioParameters.isLittleEndian = isLittleEndian;
            pcmAudioParameters.sampleRate = audioSampleRate;
            pcmAudioParameters.isValid = true;
        }

        // Read all fields
        readFields(reader, captureId);

    } catch (SqliteReader::Error &error) {
        qCritical() << "Reading SQLite file failed:" << error.what();
        return false;
    }

    // Now we know the video system, initialise the rest of VideoParameters
    initialiseVideoSystemParameters();

    // Generate the PCM audio map based on the field metadata
    generatePcmAudioMap();

    return true;
}

// Write all metadata out to an SQLite file
bool LdDecodeMetaData::write(QString fileName) const
{
    // Check if we're updating an existing file or creating a new one
    bool isUpdate = QFileInfo::exists(fileName);
    int captureId = 1; // Default for new files
    
    if (isUpdate) {
        // Try to read the existing capture_id from the file
        try {
            SqliteReader reader(fileName);
            QString existingSystem, existingDecoder, existingGitBranch, existingGitCommit, existingCaptureNotes;
            double existingVideoSampleRate;
            int existingActiveVideoStart, existingActiveVideoEnd, existingFieldWidth, existingFieldHeight;
            int existingNumberOfSequentialFields, existingColourBurstStart, existingColourBurstEnd;
            int existingWhite16bIre, existingBlack16bIre;
            bool existingIsMapped, existingIsSubcarrierLocked, existingIsWidescreen;
            
            if (reader.readCaptureMetadata(captureId, existingSystem, existingDecoder, 
                                         existingGitBranch, existingGitCommit, existingVideoSampleRate,
                                         existingActiveVideoStart, existingActiveVideoEnd, 
                                         existingFieldWidth, existingFieldHeight, existingNumberOfSequentialFields,
                                         existingColourBurstStart, existingColourBurstEnd,
                                         existingIsMapped, existingIsSubcarrierLocked, existingIsWidescreen,
                                         existingWhite16bIre, existingBlack16bIre, existingCaptureNotes)) {
                tbcDebugStream() << "Updating existing SQLite file with capture_id:" << captureId;
            } else {
                qWarning() << "Could not read existing capture metadata, treating as new file";
                isUpdate = false;
                captureId = 1;
            }
        } catch (...) {
            qWarning() << "Error reading existing SQLite file, treating as new file";
            isUpdate = false;
            captureId = 1;
        }
    }

    try {
        SqliteWriter writer(fileName);
        
        // Only create schema for new files
        if (!isUpdate) {
            if (!writer.createSchema()) {
                qCritical() << "Failed to create SQLite schema";
                return false;
            }
        }

        if (!writer.beginTransaction()) {
            qCritical() << "Failed to begin transaction";
            return false;
        }

        // Write or update capture metadata
        QString systemName = getVideoSystemDescription();
        if (isUpdate) {
            // Update existing capture metadata
            if (!writer.updateCaptureMetadata(captureId, systemName, "ld-decode", // TODO: make decoder configurable
                                            videoParameters.gitBranch, videoParameters.gitCommit,
                                            videoParameters.sampleRate, videoParameters.activeVideoStart, 
                                            videoParameters.activeVideoEnd, videoParameters.fieldWidth,
                                            videoParameters.fieldHeight, videoParameters.numberOfSequentialFields,
                                            videoParameters.colourBurstStart, videoParameters.colourBurstEnd,
                                            videoParameters.isMapped, videoParameters.isSubcarrierLocked,
                                            videoParameters.isWidescreen, videoParameters.white16bIre,
                                            videoParameters.black16bIre, videoParameters.tapeFormat)) {
                writer.rollbackTransaction();
                return false;
            }
        } else {
            // Create new capture metadata
            captureId = writer.writeCaptureMetadata(
                systemName, "ld-decode", // TODO: make decoder configurable
                videoParameters.gitBranch, videoParameters.gitCommit,
                videoParameters.sampleRate, videoParameters.activeVideoStart, 
                videoParameters.activeVideoEnd, videoParameters.fieldWidth,
                videoParameters.fieldHeight, videoParameters.numberOfSequentialFields,
                videoParameters.colourBurstStart, videoParameters.colourBurstEnd,
                videoParameters.isMapped, videoParameters.isSubcarrierLocked,
                videoParameters.isWidescreen, videoParameters.white16bIre,
                videoParameters.black16bIre, videoParameters.tapeFormat);

            if (captureId == -1) {
                writer.rollbackTransaction();
                return false;
            }
        }

        // Write PCM audio parameters if they exist
        if (pcmAudioParameters.isValid) {
            if (!writer.writePcmAudioParameters(captureId, pcmAudioParameters.bits,
                                              pcmAudioParameters.isSigned,
                                              pcmAudioParameters.isLittleEndian,
                                              pcmAudioParameters.sampleRate)) {
                writer.rollbackTransaction();
                return false;
            }
        }

        // Write all fields
        writeFields(writer, captureId);

        if (!writer.commitTransaction()) {
            qCritical() << "Failed to commit transaction";
            return false;
        }

    } catch (SqliteWriter::Error &error) {
        qCritical() << "Writing SQLite file failed:" << error.what();
        return false;
    }

    return true;
}

// Read array of Fields from SQLite (optimized version)
void LdDecodeMetaData::readFields(SqliteReader &reader, int captureId)
{
    QSqlQuery fieldsQuery;
    if (!reader.readFields(captureId, fieldsQuery)) {
        return;
    }

    // Pre-read all optional field data in bulk for performance
    QSqlQuery vitsQuery, vbiQuery, vitcQuery, ccQuery, dropoutsQuery;
    reader.readAllFieldVitsMetrics(captureId, vitsQuery);
    reader.readAllFieldVbi(captureId, vbiQuery);
    reader.readAllFieldVitc(captureId, vitcQuery);
    reader.readAllFieldClosedCaptions(captureId, ccQuery);
    reader.readAllFieldDropouts(captureId, dropoutsQuery);

    // Create lookup maps for fast field data retrieval
    QMap<int, QPair<double, double>> vitsMap;
    QMap<int, QVector<int>> vbiMap, vitcMap, ccMap;
    QMultiMap<int, QVector<int>> dropoutsMap;

    // Populate VITS metrics map
    while (vitsQuery.next()) {
        int fieldId = vitsQuery.value("field_id").toInt();
        double wSnr = vitsQuery.value("w_snr").toDouble();
        double bPsnr = vitsQuery.value("b_psnr").toDouble();
        vitsMap[fieldId] = qMakePair(wSnr, bPsnr);
    }

    // Populate VBI map
    while (vbiQuery.next()) {
        int fieldId = vbiQuery.value("field_id").toInt();
        QVector<int> vbiData = {vbiQuery.value("vbi0").toInt(), 
                               vbiQuery.value("vbi1").toInt(), 
                               vbiQuery.value("vbi2").toInt()};
        vbiMap[fieldId] = vbiData;
    }

    // Populate VITC map
    while (vitcQuery.next()) {
        int fieldId = vitcQuery.value("field_id").toInt();
        QVector<int> vitcData;
        for (int i = 0; i < 8; i++) {
            vitcData.append(vitcQuery.value(QString("vitc%1").arg(i)).toInt());
        }
        vitcMap[fieldId] = vitcData;
    }

    // Populate closed captions map
    while (ccQuery.next()) {
        int fieldId = ccQuery.value("field_id").toInt();
        QVector<int> ccData = {ccQuery.value("data0").toInt(), 
                              ccQuery.value("data1").toInt()};
        ccMap[fieldId] = ccData;
    }

    // Populate dropouts map
    while (dropoutsQuery.next()) {
        int fieldId = dropoutsQuery.value("field_id").toInt();
        QVector<int> dropoutData = {dropoutsQuery.value("startx").toInt(),
                                   dropoutsQuery.value("endx").toInt(),
                                   dropoutsQuery.value("field_line").toInt()};
        dropoutsMap.insert(fieldId, dropoutData);
    }

    // Process main field records and apply cached data
    while (fieldsQuery.next()) {
        Field field;
        
        // Note: field_id in database is 0-indexed, but seqNo should be 1-indexed
        int fieldId = fieldsQuery.value("field_id").toInt();
        field.seqNo = fieldId + 1;
        field.isFirstField = SqliteValue::toBoolOrDefault(fieldsQuery, "is_first_field");
        field.syncConf = SqliteValue::toIntOrDefault(fieldsQuery, "sync_conf", 0);
        field.medianBurstIRE = SqliteValue::toDoubleOrDefault(fieldsQuery, "median_burst_ire", 0.0);
        field.fieldPhaseID = SqliteValue::toIntOrDefault(fieldsQuery, "field_phase_id");
        field.audioSamples = SqliteValue::toIntOrDefault(fieldsQuery, "audio_samples");
        field.diskLoc = SqliteValue::toDoubleOrDefault(fieldsQuery, "disk_loc");
        field.fileLoc = SqliteValue::toLongLongOrDefault(fieldsQuery, "file_loc");
        field.decodeFaults = SqliteValue::toIntOrDefault(fieldsQuery, "decode_faults");
        field.efmTValues = SqliteValue::toIntOrDefault(fieldsQuery, "efm_t_values");
        field.pad = SqliteValue::toBoolOrDefault(fieldsQuery, "pad");

        // Read NTSC data from the main field record
        field.ntsc.isFmCodeDataValid = fieldsQuery.value("ntsc_is_fm_code_data_valid").toInt() == 1;
        field.ntsc.fmCodeData = fieldsQuery.value("ntsc_fm_code_data").toInt();
        field.ntsc.fieldFlag = fieldsQuery.value("ntsc_field_flag").toInt() == 1;
        field.ntsc.isVideoIdDataValid = fieldsQuery.value("ntsc_is_video_id_data_valid").toInt() == 1;
        field.ntsc.videoIdData = fieldsQuery.value("ntsc_video_id_data").toInt();
        field.ntsc.whiteFlag = fieldsQuery.value("ntsc_white_flag").toInt() == 1;
        field.ntsc.inUse = field.ntsc.isFmCodeDataValid || field.ntsc.isVideoIdDataValid;

        // Apply cached optional field data
        if (vitsMap.contains(fieldId)) {
            field.vitsMetrics.wSNR = vitsMap[fieldId].first;
            field.vitsMetrics.bPSNR = vitsMap[fieldId].second;
            field.vitsMetrics.inUse = true;
        }

        if (vbiMap.contains(fieldId)) {
            QVector<int> vbiData = vbiMap[fieldId];
            field.vbi.vbiData[0] = vbiData[0];
            field.vbi.vbiData[1] = vbiData[1]; 
            field.vbi.vbiData[2] = vbiData[2];
            field.vbi.inUse = true;
        }

        if (vitcMap.contains(fieldId)) {
            QVector<int> vitcData = vitcMap[fieldId];
            for (int i = 0; i < 8 && i < vitcData.size(); i++) {
                field.vitc.vitcData[i] = vitcData[i];
            }
            field.vitc.inUse = true;
        }

        if (ccMap.contains(fieldId)) {
            QVector<int> ccData = ccMap[fieldId];
            field.closedCaption.data0 = ccData[0];
            field.closedCaption.data1 = ccData[1];
            field.closedCaption.inUse = true;
        }

        if (dropoutsMap.contains(fieldId)) {
            field.dropOuts.clear();
            auto dropouts = dropoutsMap.values(fieldId);
            for (const auto& dropout : dropouts) {
                field.dropOuts.append(dropout[0], dropout[1], dropout[2]);
            }
        }

        fields.push_back(field);
    }
}

// Write array of Fields to SQLite
void LdDecodeMetaData::writeFields(SqliteWriter &writer, int captureId) const
{
    for (const Field &field : fields) {
        field.write(writer, captureId);
    }
}

// This method returns the videoParameters metadata
const LdDecodeMetaData::VideoParameters &LdDecodeMetaData::getVideoParameters()
{
    if (!videoParameters.isValid) {
        throw std::runtime_error("VideoParameters not initialized - metadata file may not have been read successfully");
    }
    return videoParameters;
}

// This method sets the videoParameters metadata
void LdDecodeMetaData::setVideoParameters(const LdDecodeMetaData::VideoParameters &_videoParameters)
{
    videoParameters = _videoParameters;
    videoParameters.isValid = true;
}

// This method returns the pcmAudioParameters metadata
const LdDecodeMetaData::PcmAudioParameters &LdDecodeMetaData::getPcmAudioParameters()
{
    if (!pcmAudioParameters.isValid) {
        throw std::runtime_error("PcmAudioParameters not initialized - metadata file may not have been read successfully");
    }
    return pcmAudioParameters;
}

// This method sets the pcmAudioParameters metadata
void LdDecodeMetaData::setPcmAudioParameters(const LdDecodeMetaData::PcmAudioParameters &_pcmAudioParameters)
{
    pcmAudioParameters = _pcmAudioParameters;
    pcmAudioParameters.isValid = true;
}

// Based on the video system selected, set default values for the members of
// VideoParameters that aren't obtained from the metadata.
void LdDecodeMetaData::initialiseVideoSystemParameters()
{
    const VideoSystemDefaults &defaults = getSystemDefaults(videoParameters);
    videoParameters.fSC = defaults.fSC;

    // Set default LineParameters
    LdDecodeMetaData::LineParameters lineParameters;
    processLineParameters(lineParameters);
}

// Validate LineParameters and apply them to the VideoParameters
void LdDecodeMetaData::processLineParameters(LdDecodeMetaData::LineParameters &lineParameters)
{
    lineParameters.applyTo(videoParameters);
}

// Validate and apply to a set of VideoParameters
void LdDecodeMetaData::LineParameters::applyTo(LdDecodeMetaData::VideoParameters &videoParameters)
{
    const bool firstFieldLineExists = firstActiveFieldLine != -1;
    const bool lastFieldLineExists = lastActiveFieldLine != -1;
    const bool firstFrameLineExists = firstActiveFrameLine != -1;
    const bool lastFrameLineExists = lastActiveFrameLine != -1;

    const VideoSystemDefaults &defaults = getSystemDefaults(videoParameters);
    const qint32 minFirstFrameLine = defaults.minActiveFrameLine;
    const qint32 defaultFirstFieldLine = defaults.firstActiveFieldLine;
    const qint32 defaultLastFieldLine = defaults.lastActiveFieldLine;
    const qint32 defaultFirstFrameLine = defaults.firstActiveFrameLine;
    const qint32 defaultLastFrameLine = defaults.lastActiveFrameLine;

    // Validate and potentially fix the first active field line.
    if (firstActiveFieldLine < 1 || firstActiveFieldLine > defaultLastFieldLine) {
        if (firstFieldLineExists) {
            qInfo().nospace() << "Specified first active field line " << firstActiveFieldLine << " out of bounds (1 to "
                              << defaultLastFieldLine << "), resetting to default (" << defaultFirstFieldLine << ").";
        }
        firstActiveFieldLine = defaultFirstFieldLine;
    }

    // Validate and potentially fix the last active field line.
    if (lastActiveFieldLine < 1 || lastActiveFieldLine > defaultLastFieldLine) {
        if (lastFieldLineExists) {
            qInfo().nospace() << "Specified last active field line " << lastActiveFieldLine << " out of bounds (1 to "
                              << defaultLastFieldLine << "), resetting to default (" << defaultLastFieldLine << ").";
        }
        lastActiveFieldLine = defaultLastFieldLine;
    }

    // Range-check the first and last active field lines.
    if (firstActiveFieldLine > lastActiveFieldLine) {
       qInfo().nospace() << "Specified last active field line " << lastActiveFieldLine << " is before specified first active field line"
                         << firstActiveFieldLine << ", resetting to defaults (" << defaultFirstFieldLine << "-" << defaultLastFieldLine << ").";
        firstActiveFieldLine = defaultFirstFieldLine;
        lastActiveFieldLine = defaultLastFieldLine;
    }

    // Validate and potentially fix the first active frame line.
    if (firstActiveFrameLine < minFirstFrameLine || firstActiveFrameLine > defaultLastFrameLine) {
        if (firstFrameLineExists) {
            qInfo().nospace() << "Specified first active frame line " << firstActiveFrameLine << " out of bounds (" << minFirstFrameLine << " to "
                              << defaultLastFrameLine << "), resetting to default (" << defaultFirstFrameLine << ").";
        }
        firstActiveFrameLine = defaultFirstFrameLine;
    }

    // Validate and potentially fix the last active frame line.
    if (lastActiveFrameLine < minFirstFrameLine || lastActiveFrameLine > defaultLastFrameLine) {
        if (lastFrameLineExists) {
            qInfo().nospace() << "Specified last active frame line " << lastActiveFrameLine << " out of bounds (" << minFirstFrameLine << " to "
                              << defaultLastFrameLine << "), resetting to default (" << defaultLastFrameLine << ").";
        }
        lastActiveFrameLine = defaultLastFrameLine;
    }

    // Range-check the first and last active frame lines.
    if (firstActiveFrameLine > lastActiveFrameLine) {
        qInfo().nospace() << "Specified last active frame line " << lastActiveFrameLine << " is before specified first active frame line"
                          << firstActiveFrameLine << ", resetting to defaults (" << defaultFirstFrameLine << "-" << defaultLastFrameLine << ").";
        firstActiveFrameLine = defaultFirstFrameLine;
        lastActiveFrameLine = defaultLastFrameLine;
    }

    // Store the new values back into videoParameters
    videoParameters.firstActiveFieldLine = firstActiveFieldLine;
    videoParameters.lastActiveFieldLine = lastActiveFieldLine;
    videoParameters.firstActiveFrameLine = firstActiveFrameLine;
    videoParameters.lastActiveFrameLine = lastActiveFrameLine;
}

// This method gets the metadata for the specified sequential field number (indexed from 1 (not 0!))
const LdDecodeMetaData::Field &LdDecodeMetaData::getField(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getField(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    return fields[fieldNumber];
}

// This method gets the VITS metrics metadata for the specified sequential field number
const LdDecodeMetaData::VitsMetrics &LdDecodeMetaData::getFieldVitsMetrics(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldVitsMetrics(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    return fields[fieldNumber].vitsMetrics;
}

// This method gets the VBI metadata for the specified sequential field number
const LdDecodeMetaData::Vbi &LdDecodeMetaData::getFieldVbi(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldVbi(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    return fields[fieldNumber].vbi;
}

// This method gets the NTSC metadata for the specified sequential field number
const LdDecodeMetaData::Ntsc &LdDecodeMetaData::getFieldNtsc(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldNtsc(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    return fields[fieldNumber].ntsc;
}

// This method gets the VITC metadata for the specified sequential field number
const LdDecodeMetaData::Vitc &LdDecodeMetaData::getFieldVitc(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldVitc(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    return fields[fieldNumber].vitc;
}

// This method gets the Closed Caption metadata for the specified sequential field number
const LdDecodeMetaData::ClosedCaption &LdDecodeMetaData::getFieldClosedCaption(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldClosedCaption(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    return fields[fieldNumber].closedCaption;
}

// This method gets the drop-out metadata for the specified sequential field number
const DropOuts &LdDecodeMetaData::getFieldDropOuts(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldDropOuts(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    return fields[fieldNumber].dropOuts;
}

// This method sets the field metadata for a field
void LdDecodeMetaData::updateField(const LdDecodeMetaData::Field &field, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::updateFieldVitsMetrics(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber] = field;
}

// This method sets the field VBI metadata for a field
void LdDecodeMetaData::updateFieldVitsMetrics(const LdDecodeMetaData::VitsMetrics &vitsMetrics, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::updateFieldVitsMetrics(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber].vitsMetrics = vitsMetrics;
}

// This method sets the field VBI metadata for a field
void LdDecodeMetaData::updateFieldVbi(const LdDecodeMetaData::Vbi &vbi, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::updateFieldVbi(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber].vbi = vbi;
}

// This method sets the field NTSC metadata for a field
void LdDecodeMetaData::updateFieldNtsc(const LdDecodeMetaData::Ntsc &ntsc, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::updateFieldNtsc(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber].ntsc = ntsc;
}

// This method sets the VITC metadata for a field
void LdDecodeMetaData::updateFieldVitc(const LdDecodeMetaData::Vitc &vitc, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::updateFieldVitc(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber].vitc = vitc;
}

// This method sets the Closed Caption metadata for a field
void LdDecodeMetaData::updateFieldClosedCaption(const LdDecodeMetaData::ClosedCaption &closedCaption, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::updateFieldClosedCaption(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber].closedCaption = closedCaption;
}

// This method sets the field dropout metadata for a field
void LdDecodeMetaData::updateFieldDropOuts(const DropOuts &dropOuts, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::updateFieldDropOuts(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber].dropOuts = dropOuts;
}

// This method clears the field dropout metadata for a field
void LdDecodeMetaData::clearFieldDropOuts(qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;
    if (fieldNumber < 0 || fieldNumber >= getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::clearFieldDropOuts(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    fields[fieldNumber].dropOuts.clear();
}

// This method appends a new field to the existing metadata
void LdDecodeMetaData::appendField(const LdDecodeMetaData::Field &field)
{
    // Ensure sequential numbering stays contiguous when writing out
    LdDecodeMetaData::Field fieldCopy = field;
    fieldCopy.seqNo = fields.size() + 1;
    fields.append(fieldCopy);

    videoParameters.numberOfSequentialFields = fields.size();
}

// Method to get the available number of fields (according to the metadata)
qint32 LdDecodeMetaData::getNumberOfFields()
{
    return fields.size();
}

// Method to set the available number of fields
// XXX This is unnecessary given appendField
void LdDecodeMetaData::setNumberOfFields(qint32 numberOfFields)
{
    videoParameters.numberOfSequentialFields = numberOfFields;
}

// A note about fields, frames and still-frames:
//
// There is a lot of confusing terminology around fields and the order in which
// they should be combined to make a 'frame'.  Basically, (taking NTSC as an example)
// a frame consists of frame lines numbered from 1 to 525.  A frame is made from two
// fields, one field contains field lines 1 to 262.5 and another 263 to 525 (although
// for convenence the 'half-lines' are usually treated as one full line and ignored
// so both fields contain a total of 263 lines of which 1 is ignored).
//
// When a frame is created, the field containing field lines 1-263 is interlaced
// with the field containing 263-525 creating a frame with field lines 1, 263, 2, 264
// and so on.  This 'frame' is then considered to contain frame lines 1-525.
//
// The field containing the first line of the frame is called the 'first field' and
// the field containing the second line of the frame is called the 'second field'.
//
// However, other names exist:
//
// Even/Odd - where the 'odd' field contains the odd line numbers 1, 3, 5, etc. This is
// the same as the 'first' field so odd = first and even = second.
//
// Upper/lower - where the 'upper' field contains the upper-part of each combination.
// This is the same as the first field so upper = first and lower = second.
//
// With a standard TV, as long as one field is first and the other is second, the only
// thing a TV requires is that the sequence of fields is constant.  They are simply
// displayed one set of fields after another to form a frame which is part of a
// moving image.
//
// This is an issue for 'still-frames' as, if the video sequence consists of
// still images (rather than motion), pausing at any given point can result in a
// frame containing a first field from one image and a second field from another
// as there is no concept of 'frame' in the video (just a sequence of first and
// second fields).
//
// Since digital formats are frame based (not field) this is an issue, as there
// is no way (from the video data) to tell how to combine fields into a
// still-frame (rather than just 'a frame').  The LaserDisc mastering could be
// in the order first field/second field = still-frame or second field/first field
// = still frame.
//
// This is why the following methods use the "isFirstFieldFirst" flag (which is
// a little confusing in itself).
//
// There are two ways to determine the 'isFirstFieldFirst'.  The first method is by
// user observation (it's pretty clear on a still-frame when it is wrong), the other
// (used by LaserDisc players) is to look for a CAV picture number in the VBI data
// of the field.  The IEC specification states that the picture number should only be
// in the first field of a frame. (Note: CLV discs don't really have to follow this
// as there are no 'still-frames' allowed by the original format).
//
// This gets even more confusing for NTSC discs using pull-down, where the sequence
// of fields making up the frames isn't even, so some field-pairs aren't considered
// to contain the first field of a still-frame (and when pausing the LaserDisc
// player will never use certain fields to render the still-frame).  Wikipedia is
// your friend if you want to learn more about it.
//
// Determining the correct setting of 'isFirstFieldFirst' is therefore outside of
// the shared-library scope.

// Method to get the available number of still-frames
qint32 LdDecodeMetaData::getNumberOfFrames()
{
    qint32 frameOffset = 0;

    // If the first field in the TBC input isn't the expected first field,
    // skip it when counting the number of still-frames
    if (isFirstFieldFirst) {
        // Expecting first field first
        if (!getField(1).isFirstField) frameOffset = 1;
    } else {
        // Expecting second field first
        if (getField(1).isFirstField) frameOffset = 1;
    }

    return (getNumberOfFields() / 2) - frameOffset;
}

// Method to get the first and second field numbers based on the frame number
// If field = 1 return the firstField, otherwise return second field
qint32 LdDecodeMetaData::getFieldNumber(qint32 frameNumber, qint32 field)
{
    qint32 firstFieldNumber = 0;
    qint32 secondFieldNumber = 0;

    // Verify the frame number
    if (frameNumber < 1) {
        qCritical() << "Invalid frame number, cannot determine fields";
        return -1;
    }

    // Calculate the first and last fields based on the position in the TBC
    if (isFirstFieldFirst) {
        // Expecting TBC file to provide still-frames as first field / second field
        firstFieldNumber = (frameNumber * 2) - 1;
        secondFieldNumber = firstFieldNumber + 1;
    } else {
        // Expecting TBC file to provide still-frames as second field / first field
        secondFieldNumber = (frameNumber * 2) - 1;
        firstFieldNumber = secondFieldNumber + 1;
    }

    // If the field number pointed to by firstFieldNumber doesn't have
    // isFirstField set, move forward field by field until the current
    // field does
    while (!getField(firstFieldNumber).isFirstField) {
        firstFieldNumber++;
        secondFieldNumber++;

        // Give up if we reach the end of the available fields
        if (firstFieldNumber > getNumberOfFields() || secondFieldNumber > getNumberOfFields()) {
            qCritical() << "Attempting to get field number failed - no isFirstField in metadata before end of file";
            firstFieldNumber = -1;
            secondFieldNumber = -1;
            break;
        }
    }

    // Range check the first field number
    if (firstFieldNumber > getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldNumber(): First field number exceed the available number of fields!";
        firstFieldNumber = -1;
        secondFieldNumber = -1;
    }

    // Range check the second field number
    if (secondFieldNumber > getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldNumber(): Second field number exceed the available number of fields!";
        firstFieldNumber = -1;
        secondFieldNumber = -1;
    }

    // Test for a buggy TBC file...
    if (getField(secondFieldNumber).isFirstField) {
        qCritical() << "LdDecodeMetaData::getFieldNumber(): Both of the determined fields have isFirstField set - the TBC source video is probably broken...";
    }

    if (field == 1) return firstFieldNumber; else return secondFieldNumber;
}

// Method to get the first field number based on the frame number
qint32 LdDecodeMetaData::getFirstFieldNumber(qint32 frameNumber)
{
    return getFieldNumber(frameNumber, 1);
}

// Method to get the second field number based on the frame number
qint32 LdDecodeMetaData::getSecondFieldNumber(qint32 frameNumber)
{
    return getFieldNumber(frameNumber, 2);
}

// Method to set the isFirstFieldFirst flag
void LdDecodeMetaData::setIsFirstFieldFirst(bool flag)
{
    isFirstFieldFirst = flag;
}

// Method to get the isFirstFieldFirst flag
bool LdDecodeMetaData::getIsFirstFieldFirst()
{
    return isFirstFieldFirst;
}

// Method to convert a CLV time code into an equivalent frame number (to make
// processing the timecodes easier)
qint32 LdDecodeMetaData::convertClvTimecodeToFrameNumber(LdDecodeMetaData::ClvTimecode clvTimeCode)
{
    // Calculate the frame number
    qint32 frameNumber = 0;
    VideoParameters videoParameters = getVideoParameters();

    // Check for invalid CLV timecode
    if (clvTimeCode.hours == -1 || clvTimeCode.minutes == -1 || clvTimeCode.seconds == -1 || clvTimeCode.pictureNumber == -1) {
        return -1;
    }

    if (clvTimeCode.hours != -1) {
        if (videoParameters.system == PAL) frameNumber += clvTimeCode.hours * 3600 * 25;
        else frameNumber += clvTimeCode.hours * 3600 * 30;
    }

    if (clvTimeCode.minutes != -1) {
        if (videoParameters.system == PAL) frameNumber += clvTimeCode.minutes * 60 * 25;
        else frameNumber += clvTimeCode.minutes * 60 * 30;
    }

    if (clvTimeCode.seconds != -1) {
        if (videoParameters.system == PAL) frameNumber += clvTimeCode.seconds * 25;
        else frameNumber += clvTimeCode.seconds * 30;
    }

    if (clvTimeCode.pictureNumber != -1) {
        frameNumber += clvTimeCode.pictureNumber;
    }

    return frameNumber;
}

// Method to convert a frame number into an equivalent CLV timecode
LdDecodeMetaData::ClvTimecode LdDecodeMetaData::convertFrameNumberToClvTimecode(qint32 frameNumber)
{
    ClvTimecode clvTimecode;

    clvTimecode.hours = 0;
    clvTimecode.minutes = 0;
    clvTimecode.seconds = 0;
    clvTimecode.pictureNumber = 0;

    if (getVideoParameters().system == PAL) {
        clvTimecode.hours = frameNumber / (3600 * 25);
        frameNumber -= clvTimecode.hours * (3600 * 25);

        clvTimecode.minutes = frameNumber / (60 * 25);
        frameNumber -= clvTimecode.minutes * (60 * 25);

        clvTimecode.seconds = frameNumber / 25;
        frameNumber -= clvTimecode.seconds * 25;

        clvTimecode.pictureNumber = frameNumber;
    } else {
        clvTimecode.hours = frameNumber / (3600 * 30);
        frameNumber -= clvTimecode.hours * (3600 * 30);

        clvTimecode.minutes = frameNumber / (60 * 30);
        frameNumber -= clvTimecode.minutes * (60 * 30);

        clvTimecode.seconds = frameNumber / 30;
        frameNumber -= clvTimecode.seconds * 30;

        clvTimecode.pictureNumber = frameNumber;
    }

    return clvTimecode;
}

// Method to return a description string for the current video format
QString LdDecodeMetaData::getVideoSystemDescription() const
{
    return getSystemDefaults(videoParameters).name;
}

// Private method to generate a map of the PCM audio data (used by the sourceAudio library)
// Note: That the map unit is "stereo sample pairs"; so each unit represents 2 16-bit samples
// for a total of 4 bytes per unit.
void LdDecodeMetaData::generatePcmAudioMap()
{
    pcmAudioFieldStartSampleMap.clear();
    pcmAudioFieldLengthMap.clear();

    tbcDebugStream() << "LdDecodeMetaData::generatePcmAudioMap(): Generating PCM audio map...";

    // Get the number of fields and resize the maps
    qint32 numberOfFields = getVideoParameters().numberOfSequentialFields;
    pcmAudioFieldStartSampleMap.resize(numberOfFields + 1);
    pcmAudioFieldLengthMap.resize(numberOfFields + 1);

    for (qint32 fieldNo = 0; fieldNo < numberOfFields; fieldNo++) {
        // Each audio sample is 16 bit - and there are 2 samples per stereo pair
        pcmAudioFieldLengthMap[fieldNo] = static_cast<qint32>(getField(fieldNo+1).audioSamples);

        if (fieldNo == 0) {
            // First field starts at 0 units
            pcmAudioFieldStartSampleMap[fieldNo] = 0;
        } else {
            // Every following field's start position is the start+length of the previous
            pcmAudioFieldStartSampleMap[fieldNo] = pcmAudioFieldStartSampleMap[fieldNo - 1] + pcmAudioFieldLengthMap[fieldNo - 1];
        }
    }
}

// Method to get the start sample location of the specified sequential field number
qint32 LdDecodeMetaData::getFieldPcmAudioStart(qint32 sequentialFieldNumber)
{
    if (pcmAudioFieldStartSampleMap.size() < sequentialFieldNumber) return -1;
    // Field numbers are 1 indexed, but our map is 0 indexed
    return pcmAudioFieldStartSampleMap[sequentialFieldNumber - 1];
}

// Method to get the sample length of the specified sequential field number
qint32 LdDecodeMetaData::getFieldPcmAudioLength(qint32 sequentialFieldNumber)
{
    if (pcmAudioFieldLengthMap.size() < sequentialFieldNumber) return -1;
    // Field numbers are 1 indexed, but our map is 0 indexed
    return pcmAudioFieldLengthMap[sequentialFieldNumber - 1];
}
