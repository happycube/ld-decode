/******************************************************************************
 * jsonconverter.cpp
 * ld-json-converter - JSON converter tool for ld-decode
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "jsonconverter.h"
#include <QDebug>
#include <QFileInfo>
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QSqlError>
#include <QDir>

JsonConverter::JsonConverter(const QString &inputJsonFilename, const QString &outputSqliteFilename)
    : m_inputJsonFilename(inputJsonFilename), m_outputSqliteFilename(outputSqliteFilename)
{

}

JsonConverter::~JsonConverter()
{
    if (m_database.isOpen()) {
        m_database.close();
    }
}

bool JsonConverter::process()
{
    qInfo() << "Processing JSON file:" << m_inputJsonFilename;
    
    // Check if input file exists
    QFileInfo inputFile(m_inputJsonFilename);
    if (!inputFile.exists()) {
        qCritical() << "Input JSON file does not exist:" << m_inputJsonFilename;
        return false;
    }
    
    // Load the JSON metadata using local TBC library
    LdDecodeMetaData metaData;
    if (!metaData.read(m_inputJsonFilename)) {
        qCritical() << "Failed to read JSON file:" << m_inputJsonFilename;
        return false;
    }
    
    qInfo() << "Successfully loaded JSON metadata";
    
    // Report on the contents
    reportJsonContents(metaData);
    
    qInfo() << "JSON analysis complete. Output SQLite file will be:" << m_outputSqliteFilename;
    
    // Create and setup the SQLite database
    if (!createDatabase()) {
        qCritical() << "Failed to create SQLite database";
        return false;
    }
    
    // Create the database schema
    if (!createSchema()) {
        qCritical() << "Failed to create database schema";
        return false;
    }
    
    // Insert the data
    if (!insertData(metaData)) {
        qCritical() << "Failed to insert data into database";
        return false;
    }
    
    qInfo() << "SQLite database created successfully:" << m_outputSqliteFilename;
    
    return true;
}

void JsonConverter::reportJsonContents(LdDecodeMetaData &metaData)
{
    qInfo() << "=== JSON Content Analysis ===";
    
    // Basic information
    qInfo() << "Video System:" << metaData.getVideoSystemDescription();
    qInfo() << "Number of Fields:" << metaData.getNumberOfFields();
    qInfo() << "Number of Frames:" << metaData.getNumberOfFrames();
    qInfo() << "First Field First:" << (metaData.getIsFirstFieldFirst() ? "Yes" : "No");
    
    // Comprehensive Video parameters matching README schema
    const LdDecodeMetaData::VideoParameters &videoParams = metaData.getVideoParameters();
    qInfo() << "Video Parameters:";
    qInfo() << "  System:" << (videoParams.system == PAL ? "PAL" : 
                                (videoParams.system == NTSC ? "NTSC" : "PAL_M"));
    qInfo() << "  Field Width:" << videoParams.fieldWidth << "pixels";
    qInfo() << "  Field Height:" << videoParams.fieldHeight << "lines";
    qInfo() << "  Video Sample Rate:" << QString::number(videoParams.sampleRate, 'f', 0).toLongLong() << "Hz";
    qInfo() << "  Active Video Start:" << videoParams.activeVideoStart;
    qInfo() << "  Active Video End:" << videoParams.activeVideoEnd;
    qInfo() << "  Colour Burst Start:" << videoParams.colourBurstStart;
    qInfo() << "  Colour Burst End:" << videoParams.colourBurstEnd;
    qInfo() << "  White 16b IRE:" << videoParams.white16bIre;
    qInfo() << "  Black 16b IRE:" << videoParams.black16bIre;
    qInfo() << "  Is Mapped:" << (videoParams.isMapped ? "Yes" : "No");
    qInfo() << "  Is Subcarrier Locked:" << (videoParams.isSubcarrierLocked ? "Yes" : "No");
    qInfo() << "  Is Widescreen:" << (videoParams.isWidescreen ? "Yes" : "No");
    if (!videoParams.gitBranch.isEmpty()) {
        qInfo() << "  Git Branch:" << videoParams.gitBranch;
    }
    if (!videoParams.gitCommit.isEmpty()) {
        qInfo() << "  Git Commit:" << videoParams.gitCommit;
    }
    if (!videoParams.tapeFormat.isEmpty()) {
        qInfo() << "  Tape Format:" << videoParams.tapeFormat;
    }
    
    // PCM Audio parameters (if present)
    const LdDecodeMetaData::PcmAudioParameters &audioParams = metaData.getPcmAudioParameters();
    if (audioParams.sampleRate > 0) {
        qInfo() << "PCM Audio Parameters:";
        qInfo() << "  Sample Rate:" << audioParams.sampleRate << "Hz";
        qInfo() << "  Bits per Sample:" << audioParams.bits;
        qInfo() << "  Is Signed:" << (audioParams.isSigned ? "Yes" : "No");
        qInfo() << "  Is Little Endian:" << (audioParams.isLittleEndian ? "Yes" : "No");
    } else {
        qInfo() << "PCM Audio Parameters: Not present";
    }
    
    // Count different types of data objects as per schema
    qint32 fieldsWithVbi = 0;
    qint32 fieldsWithVitc = 0;
    qint32 fieldsWithClosedCaptions = 0;
    qint32 fieldsWithVitsMetrics = 0;
    qint32 fieldsWithNtsc = 0;
    qint32 totalDropouts = 0;
    qint32 fieldsWithAudio = 0;
    qint32 paddedFields = 0;
    
    // Analyze each field for detailed statistics
    for (qint32 fieldNum = 1; fieldNum <= metaData.getNumberOfFields(); fieldNum++) {
        const LdDecodeMetaData::Field &field = metaData.getField(fieldNum);
        
        // Count padded fields
        if (field.pad) paddedFields++;
        
        // Count fields with audio samples
        if (field.audioSamples > 0) fieldsWithAudio++;
        
        // Count VBI data
        const LdDecodeMetaData::Vbi &vbi = metaData.getFieldVbi(fieldNum);
        if (vbi.inUse) fieldsWithVbi++;
        
        // Count VITC data
        const LdDecodeMetaData::Vitc &vitc = metaData.getFieldVitc(fieldNum);
        if (vitc.inUse) fieldsWithVitc++;
        
        // Count Closed Caption data
        const LdDecodeMetaData::ClosedCaption &cc = metaData.getFieldClosedCaption(fieldNum);
        if (cc.inUse) fieldsWithClosedCaptions++;
        
        // Count VITS Metrics
        const LdDecodeMetaData::VitsMetrics &vits = metaData.getFieldVitsMetrics(fieldNum);
        if (vits.inUse) fieldsWithVitsMetrics++;
        
        // Count NTSC data
        const LdDecodeMetaData::Ntsc &ntsc = metaData.getFieldNtsc(fieldNum);
        if (ntsc.inUse) fieldsWithNtsc++;
        
        // Count dropouts
        const DropOuts &dropouts = metaData.getFieldDropOuts(fieldNum);
        totalDropouts += dropouts.size();
    }
    
    qInfo() << "Field Data Objects Summary:";
    qInfo() << "  Fields with VBI data:" << fieldsWithVbi << "(" << 
               QString::number(100.0 * fieldsWithVbi / metaData.getNumberOfFields(), 'f', 1).toDouble() << "%)";
    qInfo() << "  Fields with VITC data:" << fieldsWithVitc << "(" << 
               QString::number(100.0 * fieldsWithVitc / metaData.getNumberOfFields(), 'f', 1).toDouble() << "%)";
    qInfo() << "  Fields with Closed Caption data:" << fieldsWithClosedCaptions << "(" << 
               QString::number(100.0 * fieldsWithClosedCaptions / metaData.getNumberOfFields(), 'f', 1).toDouble() << "%)";
    qInfo() << "  Fields with VITS Metrics:" << fieldsWithVitsMetrics << "(" << 
               QString::number(100.0 * fieldsWithVitsMetrics / metaData.getNumberOfFields(), 'f', 1).toDouble() << "%)";
    if (videoParams.system == NTSC) {
        qInfo() << "  Fields with NTSC data:" << fieldsWithNtsc << "(" << 
                   QString::number(100.0 * fieldsWithNtsc / metaData.getNumberOfFields(), 'f', 1).toDouble() << "%)";
    }
    qInfo() << "  Fields with Audio samples:" << fieldsWithAudio << "(" << 
               QString::number(100.0 * fieldsWithAudio / metaData.getNumberOfFields(), 'f', 1).toDouble() << "%)";
    qInfo() << "  Padded fields (no valid video):" << paddedFields << "(" << 
               QString::number(100.0 * paddedFields / metaData.getNumberOfFields(), 'f', 1).toDouble() << "%)";
    qInfo() << "  Total Dropout objects:" << totalDropouts;
    
    // Summary for conversion planning
    qInfo() << "SQLite Conversion Planning:";
    qInfo() << "  Main capture record: 1 row";
    qInfo() << "  PCM audio parameters:" << (audioParams.sampleRate > 0 ? "1 row" : "0 rows (no audio)");
    qInfo() << "  Field records:" << metaData.getNumberOfFields() << "rows";
    qInfo() << "  VBI rows:" << fieldsWithVbi;
    qInfo() << "  VITC rows:" << fieldsWithVitc;
    qInfo() << "  Closed Caption rows:" << fieldsWithClosedCaptions;
    qInfo() << "  VITS Metrics rows:" << fieldsWithVitsMetrics;
    qInfo() << "  Dropout rows:" << totalDropouts;
    
    qInfo() << "=== End Analysis ===";
}

bool JsonConverter::createDatabase()
{
    // Remove existing database file if it exists
    QFileInfo dbFile(m_outputSqliteFilename);
    if (dbFile.exists()) {
        if (!QDir().remove(m_outputSqliteFilename)) {
            qCritical() << "Failed to remove existing database file:" << m_outputSqliteFilename;
            return false;
        }
    }
    
    // Create the database connection
    m_database = QSqlDatabase::addDatabase("QSQLITE");
    m_database.setDatabaseName(m_outputSqliteFilename);
    
    if (!m_database.open()) {
        qCritical() << "Failed to open SQLite database:" << m_database.lastError().text();
        return false;
    }
    
    qInfo() << "SQLite database created and opened successfully";
    return true;
}

bool JsonConverter::createSchema()
{
    QSqlQuery query(m_database);
    
    // Set schema version
    if (!query.exec("PRAGMA user_version = 1;")) {
        qCritical() << "Failed to set schema version:" << query.lastError().text();
        return false;
    }
    
    // Create capture table
    if (!query.exec(
        "CREATE TABLE capture ("
        "    capture_id INTEGER PRIMARY KEY,"
        "    system TEXT NOT NULL"
        "        CHECK (system IN ('NTSC','PAL','PAL_M')),"
        "    decoder TEXT NOT NULL"
        "        CHECK (decoder IN ('ld-decode','vhs-decode')),"
        "    git_branch TEXT,"
        "    git_commit TEXT,"
        "    video_sample_rate REAL,"
        "    active_video_start INTEGER,"
        "    active_video_end INTEGER,"
        "    field_width INTEGER,"
        "    field_height INTEGER,"
        "    number_of_sequential_fields INTEGER,"
        "    colour_burst_start INTEGER,"
        "    colour_burst_end INTEGER,"
        "    is_mapped INTEGER"
        "        CHECK (is_mapped IN (0,1)),"
        "    is_subcarrier_locked INTEGER"
        "        CHECK (is_subcarrier_locked IN (0,1)),"
        "    is_widescreen INTEGER"
        "        CHECK (is_widescreen IN (0,1)),"
        "    white_16b_ire INTEGER,"
        "    black_16b_ire INTEGER,"
        "    capture_notes TEXT"
        ");"
    )) {
        qCritical() << "Failed to create capture table:" << query.lastError().text();
        return false;
    }
    
    // Create pcm_audio_parameters table
    if (!query.exec(
        "CREATE TABLE pcm_audio_parameters ("
        "    capture_id INTEGER PRIMARY KEY"
        "        REFERENCES capture(capture_id) ON DELETE CASCADE,"
        "    bits INTEGER,"
        "    is_signed INTEGER"
        "        CHECK (is_signed IN (0,1)),"
        "    is_little_endian INTEGER"
        "        CHECK (is_little_endian IN (0,1)),"
        "    sample_rate REAL"
        ");"
    )) {
        qCritical() << "Failed to create pcm_audio_parameters table:" << query.lastError().text();
        return false;
    }
    
    // Create field_record table
    if (!query.exec(
        "CREATE TABLE field_record ("
        "    capture_id INTEGER NOT NULL"
        "        REFERENCES capture(capture_id) ON DELETE CASCADE,"
        "    field_id INTEGER NOT NULL,"
        "    audio_samples INTEGER,"
        "    decode_faults INTEGER,"
        "    disk_loc REAL,"
        "    efm_t_values INTEGER,"
        "    field_phase_id INTEGER,"
        "    file_loc INTEGER,"
        "    is_first_field INTEGER"
        "        CHECK (is_first_field IN (0,1)),"
        "    median_burst_ire REAL,"
        "    pad INTEGER"
        "        CHECK (pad IN (0,1)),"
        "    sync_conf INTEGER,"
        "    ntsc_is_fm_code_data_valid INTEGER"
        "        CHECK (ntsc_is_fm_code_data_valid IN (0,1)),"
        "    ntsc_fm_code_data INTEGER,"
        "    ntsc_field_flag INTEGER"
        "        CHECK (ntsc_field_flag IN (0,1)),"
        "    ntsc_is_video_id_data_valid INTEGER"
        "        CHECK (ntsc_is_video_id_data_valid IN (0,1)),"
        "    ntsc_video_id_data INTEGER,"
        "    ntsc_white_flag INTEGER"
        "        CHECK (ntsc_white_flag IN (0,1)),"
        "    PRIMARY KEY (capture_id, field_id)"
        ");"
    )) {
        qCritical() << "Failed to create field_record table:" << query.lastError().text();
        return false;
    }
    
    // Create vits_metrics table
    if (!query.exec(
        "CREATE TABLE vits_metrics ("
        "    capture_id INTEGER NOT NULL,"
        "    field_id INTEGER NOT NULL,"
        "    b_psnr REAL,"
        "    w_snr REAL,"
        "    FOREIGN KEY (capture_id, field_id)"
        "        REFERENCES field_record(capture_id, field_id)"
        "        ON DELETE CASCADE,"
        "    PRIMARY KEY (capture_id, field_id)"
        ");"
    )) {
        qCritical() << "Failed to create vits_metrics table:" << query.lastError().text();
        return false;
    }
    
    // Create vbi table
    if (!query.exec(
        "CREATE TABLE vbi ("
        "    capture_id INTEGER NOT NULL,"
        "    field_id INTEGER NOT NULL,"
        "    vbi0 INTEGER NOT NULL,"
        "    vbi1 INTEGER NOT NULL,"
        "    vbi2 INTEGER NOT NULL,"
        "    FOREIGN KEY (capture_id, field_id)"
        "        REFERENCES field_record(capture_id, field_id)"
        "        ON DELETE CASCADE,"
        "    PRIMARY KEY (capture_id, field_id)"
        ");"
    )) {
        qCritical() << "Failed to create vbi table:" << query.lastError().text();
        return false;
    }
    
    // Create drop_outs table
    if (!query.exec(
        "CREATE TABLE drop_outs ("
        "    capture_id INTEGER NOT NULL,"
        "    field_id INTEGER NOT NULL,"
        "    field_line INTEGER NOT NULL,"
        "    startx INTEGER NOT NULL,"
        "    endx INTEGER NOT NULL,"
        "    PRIMARY KEY (capture_id, field_id, field_line, startx, endx),"
        "    FOREIGN KEY (capture_id, field_id)"
        "        REFERENCES field_record(capture_id, field_id)"
        "        ON DELETE CASCADE"
        ");"
    )) {
        qCritical() << "Failed to create drop_outs table:" << query.lastError().text();
        return false;
    }
    
    // Create vitc table
    if (!query.exec(
        "CREATE TABLE vitc ("
        "    capture_id INTEGER NOT NULL,"
        "    field_id INTEGER NOT NULL,"
        "    vitc0 INTEGER NOT NULL,"
        "    vitc1 INTEGER NOT NULL,"
        "    vitc2 INTEGER NOT NULL,"
        "    vitc3 INTEGER NOT NULL,"
        "    vitc4 INTEGER NOT NULL,"
        "    vitc5 INTEGER NOT NULL,"
        "    vitc6 INTEGER NOT NULL,"
        "    vitc7 INTEGER NOT NULL,"
        "    FOREIGN KEY (capture_id, field_id)"
        "        REFERENCES field_record(capture_id, field_id)"
        "        ON DELETE CASCADE,"
        "    PRIMARY KEY (capture_id, field_id)"
        ");"
    )) {
        qCritical() << "Failed to create vitc table:" << query.lastError().text();
        return false;
    }
    
    // Create closed_caption table
    if (!query.exec(
        "CREATE TABLE closed_caption ("
        "    capture_id INTEGER NOT NULL,"
        "    field_id INTEGER NOT NULL,"
        "    data0 INTEGER,"
        "    data1 INTEGER,"
        "    FOREIGN KEY (capture_id, field_id)"
        "        REFERENCES field_record(capture_id, field_id)"
        "        ON DELETE CASCADE,"
        "    PRIMARY KEY (capture_id, field_id)"
        ");"
    )) {
        qCritical() << "Failed to create closed_caption table:" << query.lastError().text();
        return false;
    }
    
    qInfo() << "Database schema created successfully";
    return true;
}

bool JsonConverter::insertData(LdDecodeMetaData &metaData)
{
    qInfo() << "Starting data insertion...";
    
    QSqlQuery query(m_database);
    
    // Begin transaction for better performance
    if (!m_database.transaction()) {
        qCritical() << "Failed to begin transaction:" << m_database.lastError().text();
        return false;
    }
    
    try {
        // Insert capture record
        const LdDecodeMetaData::VideoParameters &videoParams = metaData.getVideoParameters();
        
        // Determine system string
        QString systemStr;
        switch (videoParams.system) {
            case PAL: systemStr = "PAL"; break;
            case NTSC: systemStr = "NTSC"; break;
            case PAL_M: systemStr = "PAL_M"; break;
            default: systemStr = "PAL"; break;
        }
        
        // Determine decoder from metadata or default to ld-decode
        QString decoder = "ld-decode"; // Default, could be determined from metadata if available
        
        query.prepare(
            "INSERT INTO capture ("
            "capture_id, system, decoder, git_branch, git_commit, "
            "video_sample_rate, active_video_start, active_video_end, "
            "field_width, field_height, number_of_sequential_fields, "
            "colour_burst_start, colour_burst_end, is_mapped, "
            "is_subcarrier_locked, is_widescreen, white_16b_ire, "
            "black_16b_ire, capture_notes"
            ") VALUES ("
            "1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
            ")"
        );
        
        query.bindValue(0, systemStr);
        query.bindValue(1, decoder);
        query.bindValue(2, videoParams.gitBranch.isEmpty() ? QVariant() : videoParams.gitBranch);
        query.bindValue(3, videoParams.gitCommit.isEmpty() ? QVariant() : videoParams.gitCommit);
        query.bindValue(4, videoParams.sampleRate);
        query.bindValue(5, videoParams.activeVideoStart);
        query.bindValue(6, videoParams.activeVideoEnd);
        query.bindValue(7, videoParams.fieldWidth);
        query.bindValue(8, videoParams.fieldHeight);
        query.bindValue(9, metaData.getNumberOfFields());
        query.bindValue(10, videoParams.colourBurstStart);
        query.bindValue(11, videoParams.colourBurstEnd);
        query.bindValue(12, videoParams.isMapped ? 1 : 0);
        query.bindValue(13, videoParams.isSubcarrierLocked ? 1 : 0);
        query.bindValue(14, videoParams.isWidescreen ? 1 : 0);
        query.bindValue(15, videoParams.white16bIre);
        query.bindValue(16, videoParams.black16bIre);
        query.bindValue(17, videoParams.tapeFormat.isEmpty() ? QVariant() : videoParams.tapeFormat);
        
        if (!query.exec()) {
            qCritical() << "Failed to insert capture record:" << query.lastError().text();
            m_database.rollback();
            return false;
        }
        
        // Insert PCM audio parameters if present
        const LdDecodeMetaData::PcmAudioParameters &audioParams = metaData.getPcmAudioParameters();
        if (audioParams.sampleRate > 0) {
            query.prepare(
                "INSERT INTO pcm_audio_parameters ("
                "capture_id, bits, is_signed, is_little_endian, sample_rate"
                ") VALUES (1, ?, ?, ?, ?)"
            );
            
            query.bindValue(0, audioParams.bits);
            query.bindValue(1, audioParams.isSigned ? 1 : 0);
            query.bindValue(2, audioParams.isLittleEndian ? 1 : 0);
            query.bindValue(3, audioParams.sampleRate);
            
            if (!query.exec()) {
                qCritical() << "Failed to insert PCM audio parameters:" << query.lastError().text();
                m_database.rollback();
                return false;
            }
        }
        
        // Insert field records and related data
        qInfo() << "Inserting field records...";
        for (qint32 fieldNum = 1; fieldNum <= metaData.getNumberOfFields(); fieldNum++) {
            const LdDecodeMetaData::Field &field = metaData.getField(fieldNum);
            
            // Convert seqNo to zero-indexed field_id (seqNo - 1)
            qint32 fieldId = fieldNum - 1;
            
            // Insert main field record
            query.prepare(
                "INSERT INTO field_record ("
                "capture_id, field_id, audio_samples, decode_faults, disk_loc, "
                "efm_t_values, field_phase_id, file_loc, is_first_field, "
                "median_burst_ire, pad, sync_conf, ntsc_is_fm_code_data_valid, "
                "ntsc_fm_code_data, ntsc_field_flag, ntsc_is_video_id_data_valid, "
                "ntsc_video_id_data, ntsc_white_flag"
                ") VALUES ("
                "1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")"
            );
            
            query.bindValue(0, fieldId);
            query.bindValue(1, field.audioSamples > 0 ? field.audioSamples : QVariant());
            query.bindValue(2, field.decodeFaults > 0 ? field.decodeFaults : QVariant());
            query.bindValue(3, field.diskLoc > 0.0 ? field.diskLoc : QVariant());
            query.bindValue(4, field.efmTValues > 0 ? field.efmTValues : QVariant());
            query.bindValue(5, field.fieldPhaseID);
            query.bindValue(6, field.fileLoc > 0 ? field.fileLoc : QVariant());
            query.bindValue(7, field.isFirstField ? 1 : 0);
            query.bindValue(8, field.medianBurstIRE);
            query.bindValue(9, field.pad ? 1 : 0);
            query.bindValue(10, field.syncConf);
            
            // NTSC specific fields
            const LdDecodeMetaData::Ntsc &ntsc = metaData.getFieldNtsc(fieldNum);
            if (ntsc.inUse) {
                query.bindValue(11, ntsc.isFmCodeDataValid ? 1 : 0);
                query.bindValue(12, ntsc.fmCodeData);
                query.bindValue(13, ntsc.fieldFlag ? 1 : 0);
                query.bindValue(14, ntsc.isVideoIdDataValid ? 1 : 0);
                query.bindValue(15, ntsc.videoIdData);
                query.bindValue(16, ntsc.whiteFlag ? 1 : 0);
            } else {
                query.bindValue(11, QVariant());
                query.bindValue(12, QVariant());
                query.bindValue(13, QVariant());
                query.bindValue(14, QVariant());
                query.bindValue(15, QVariant());
                query.bindValue(16, QVariant());
            }
            
            if (!query.exec()) {
                qCritical() << "Failed to insert field record for field" << fieldNum << ":" << query.lastError().text();
                m_database.rollback();
                return false;
            }
            
            // Insert VITS metrics if present
            const LdDecodeMetaData::VitsMetrics &vits = metaData.getFieldVitsMetrics(fieldNum);
            if (vits.inUse) {
                query.prepare(
                    "INSERT INTO vits_metrics (capture_id, field_id, b_psnr, w_snr) "
                    "VALUES (1, ?, ?, ?)"
                );
                query.bindValue(0, fieldId);
                query.bindValue(1, vits.bPSNR);
                query.bindValue(2, vits.wSNR);
                
                if (!query.exec()) {
                    qCritical() << "Failed to insert VITS metrics for field" << fieldNum << ":" << query.lastError().text();
                    m_database.rollback();
                    return false;
                }
            }
            
            // Insert VBI data if present
            const LdDecodeMetaData::Vbi &vbi = metaData.getFieldVbi(fieldNum);
            if (vbi.inUse && vbi.vbiData.size() >= 3) {
                query.prepare(
                    "INSERT INTO vbi (capture_id, field_id, vbi0, vbi1, vbi2) "
                    "VALUES (1, ?, ?, ?, ?)"
                );
                query.bindValue(0, fieldId);
                query.bindValue(1, vbi.vbiData[0]);
                query.bindValue(2, vbi.vbiData[1]);
                query.bindValue(3, vbi.vbiData[2]);
                
                if (!query.exec()) {
                    qCritical() << "Failed to insert VBI data for field" << fieldNum << ":" << query.lastError().text();
                    m_database.rollback();
                    return false;
                }
            }
            
            // Insert VITC data if present
            const LdDecodeMetaData::Vitc &vitc = metaData.getFieldVitc(fieldNum);
            if (vitc.inUse && vitc.vitcData.size() >= 8) {
                query.prepare(
                    "INSERT INTO vitc (capture_id, field_id, vitc0, vitc1, vitc2, vitc3, vitc4, vitc5, vitc6, vitc7) "
                    "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                );
                query.bindValue(0, fieldId);
                query.bindValue(1, vitc.vitcData[0]);
                query.bindValue(2, vitc.vitcData[1]);
                query.bindValue(3, vitc.vitcData[2]);
                query.bindValue(4, vitc.vitcData[3]);
                query.bindValue(5, vitc.vitcData[4]);
                query.bindValue(6, vitc.vitcData[5]);
                query.bindValue(7, vitc.vitcData[6]);
                query.bindValue(8, vitc.vitcData[7]);
                
                if (!query.exec()) {
                    qCritical() << "Failed to insert VITC data for field" << fieldNum << ":" << query.lastError().text();
                    m_database.rollback();
                    return false;
                }
            }
            
            // Insert Closed Caption data if present
            const LdDecodeMetaData::ClosedCaption &cc = metaData.getFieldClosedCaption(fieldNum);
            if (cc.inUse) {
                query.prepare(
                    "INSERT INTO closed_caption (capture_id, field_id, data0, data1) "
                    "VALUES (1, ?, ?, ?)"
                );
                query.bindValue(0, fieldId);
                query.bindValue(1, cc.data0 >= 0 ? cc.data0 : QVariant());
                query.bindValue(2, cc.data1 >= 0 ? cc.data1 : QVariant());
                
                if (!query.exec()) {
                    qCritical() << "Failed to insert closed caption data for field" << fieldNum << ":" << query.lastError().text();
                    m_database.rollback();
                    return false;
                }
            }
            
            // Insert dropout data if present
            const DropOuts &dropouts = metaData.getFieldDropOuts(fieldNum);
            for (qint32 i = 0; i < dropouts.size(); i++) {
                query.prepare(
                    "INSERT INTO drop_outs (capture_id, field_id, field_line, startx, endx) "
                    "VALUES (1, ?, ?, ?, ?)"
                );
                query.bindValue(0, fieldId);
                query.bindValue(1, dropouts.fieldLine(i));
                query.bindValue(2, dropouts.startx(i));
                query.bindValue(3, dropouts.endx(i));
                
                if (!query.exec()) {
                    // Check if this is a UNIQUE constraint violation (duplicate dropout)
                    QString errorText = query.lastError().text();
                    if (errorText.contains("UNIQUE constraint failed", Qt::CaseInsensitive)) {
                        qInfo() << "Skipping duplicate dropout in field" << fieldNum << "dropout" << i << ": "
                                << "fieldLine=" << dropouts.fieldLine(i) 
                                << "startx=" << dropouts.startx(i) 
                                << "endx=" << dropouts.endx(i);
                        // Continue processing other dropouts instead of failing
                        continue;
                    } else {
                        // This is a different kind of error, still fail
                        qCritical() << "Failed to insert dropout data for field" << fieldNum << "dropout" << i << ":" << errorText;
                        m_database.rollback();
                        return false;
                    }
                }
            }
            
            // Progress indicator every 1000 fields
            if (fieldNum % 1000 == 0) {
                qInfo() << "Inserted" << fieldNum << "of" << metaData.getNumberOfFields() << "fields...";
            }
        }
        
        // Commit the transaction
        if (!m_database.commit()) {
            qCritical() << "Failed to commit transaction:" << m_database.lastError().text();
            return false;
        }
        
        qInfo() << "Successfully inserted all data into SQLite database";
        return true;
        
    } catch (...) {
        m_database.rollback();
        throw;
    }
}