/******************************************************************************
 * sqliteio.cpp
 * ld-decode-tools TBC library
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "sqliteio.h"

#include <QSqlDriver>
#include <QUuid>
#include <QDebug>
#include <QFileInfo>
#include <QThread>
#include <QStringList>
#include "tbc/logging.h"

namespace SqliteValue
{
    // Keep legacy "-1 means missing" semantics when SQLite stores NULL
    int toIntOrDefault(const QSqlQuery &query, const char *column, int defaultValue)
    {
        const QVariant value = query.value(column);
        return value.isNull() ? defaultValue : value.toInt();
    }

    qint64 toLongLongOrDefault(const QSqlQuery &query, const char *column, qint64 defaultValue)
    {
        const QVariant value = query.value(column);
        return value.isNull() ? defaultValue : value.toLongLong();
    }

    double toDoubleOrDefault(const QSqlQuery &query, const char *column, double defaultValue)
    {
        const QVariant value = query.value(column);
        return value.isNull() ? defaultValue : value.toDouble();
    }

    bool toBoolOrDefault(const QSqlQuery &query, const char *column, bool defaultValue)
    {
        const QVariant value = query.value(column);
        return value.isNull() ? defaultValue : value.toInt() == 1;
    }
}

// SQL schema as per documentation
static const QString SCHEMA_SQL = R"(
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS capture (
    capture_id INTEGER PRIMARY KEY,
    system TEXT NOT NULL
        CHECK (system IN ('NTSC','PAL','PAL_M')),
    decoder TEXT NOT NULL
        CHECK (decoder IN ('ld-decode','vhs-decode')),
    git_branch TEXT,
    git_commit TEXT,

    video_sample_rate REAL,
    active_video_start INTEGER,
    active_video_end INTEGER,
    field_width INTEGER,
    field_height INTEGER,
    number_of_sequential_fields INTEGER,

    colour_burst_start INTEGER,
    colour_burst_end INTEGER,
    is_mapped INTEGER
        CHECK (is_mapped IN (0,1)),
    is_subcarrier_locked INTEGER
        CHECK (is_subcarrier_locked IN (0,1)),
    is_widescreen INTEGER
        CHECK (is_widescreen IN (0,1)),
    white_16b_ire INTEGER,
    black_16b_ire INTEGER,

    capture_notes TEXT
);

CREATE TABLE IF NOT EXISTS pcm_audio_parameters (
    capture_id INTEGER PRIMARY KEY
        REFERENCES capture(capture_id) ON DELETE CASCADE,
    bits INTEGER,
    is_signed INTEGER
        CHECK (is_signed IN (0,1)),
    is_little_endian INTEGER
        CHECK (is_little_endian IN (0,1)),
    sample_rate REAL
);

CREATE TABLE IF NOT EXISTS field_record (
    capture_id INTEGER NOT NULL
        REFERENCES capture(capture_id) ON DELETE CASCADE,
    field_id INTEGER NOT NULL,
    audio_samples INTEGER,
    decode_faults INTEGER,
    disk_loc REAL,
    efm_t_values INTEGER,
    field_phase_id INTEGER,
    file_loc INTEGER,
    is_first_field INTEGER
        CHECK (is_first_field IN (0,1)),
    median_burst_ire REAL,
    pad INTEGER
        CHECK (pad IN (0,1)),
    sync_conf INTEGER,

    ntsc_is_fm_code_data_valid INTEGER
        CHECK (ntsc_is_fm_code_data_valid IN (0,1)),
    ntsc_fm_code_data INTEGER,
    ntsc_field_flag INTEGER
        CHECK (ntsc_field_flag IN (0,1)),
    ntsc_is_video_id_data_valid INTEGER
        CHECK (ntsc_is_video_id_data_valid IN (0,1)),
    ntsc_video_id_data INTEGER,
    ntsc_white_flag INTEGER
        CHECK (ntsc_white_flag IN (0,1)),

    PRIMARY KEY (capture_id, field_id)
);

CREATE TABLE IF NOT EXISTS vits_metrics (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    w_snr REAL,
    b_psnr REAL,
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);

CREATE TABLE IF NOT EXISTS vbi (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    vbi0 INTEGER,
    vbi1 INTEGER,
    vbi2 INTEGER,
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);

CREATE TABLE IF NOT EXISTS drop_outs (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    startx INTEGER NOT NULL,
    endx INTEGER NOT NULL,
    field_line INTEGER NOT NULL,
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vitc (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    vitc0 INTEGER,
    vitc1 INTEGER,
    vitc2 INTEGER,
    vitc3 INTEGER,
    vitc4 INTEGER,
    vitc5 INTEGER,
    vitc6 INTEGER,
    vitc7 INTEGER,
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);

CREATE TABLE IF NOT EXISTS closed_caption (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    data0 INTEGER,
    data1 INTEGER,
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);
)";

SqliteReader::SqliteReader(const QString &fileName)
{
    // Create connection name based on filename and thread to avoid cross-thread issues
    QString threadId = QString::number(reinterpret_cast<qintptr>(QThread::currentThread()));
    connectionName = "sqlite_reader_" + QFileInfo(fileName).absoluteFilePath().replace('/', '_') + "_thread_" + threadId;
    
    // Check if connection already exists, if so reuse it
    if (QSqlDatabase::contains(connectionName)) {
        db = QSqlDatabase::database(connectionName);
    } else {
        // Create new database connection
        db = QSqlDatabase::addDatabase("QSQLITE", connectionName);
        db.setDatabaseName(fileName);
        
        if (!db.open()) {
            throwError("Failed to open database: " + db.lastError().text().toStdString());
        }
    }
}

SqliteReader::~SqliteReader()
{
    close();
}

void SqliteReader::close()
{
    // Close the database connection
    if (db.isValid() && db.isOpen()) {
        db.close();
    }
    // Don't remove the connection - this causes a Qt warning
    // Qt will clean up connections when the application exits
}

bool SqliteReader::readCaptureMetadata(int &captureId, QString &system, QString &decoder,
                                     QString &gitBranch, QString &gitCommit,
                                     double &videoSampleRate, int &activeVideoStart, int &activeVideoEnd,
                                     int &fieldWidth, int &fieldHeight, int &numberOfSequentialFields,
                                     int &colourBurstStart, int &colourBurstEnd,
                                     bool &isMapped, bool &isSubcarrierLocked, bool &isWidescreen,
                                     int &white16bIre, int &black16bIre, QString &captureNotes)
{
    QSqlQuery query(db);
    query.prepare("SELECT capture_id, system, decoder, git_branch, git_commit, "
                 "video_sample_rate, active_video_start, active_video_end, "
                 "field_width, field_height, number_of_sequential_fields, "
                 "colour_burst_start, colour_burst_end, is_mapped, is_subcarrier_locked, "
                 "is_widescreen, white_16b_ire, black_16b_ire, capture_notes "
                 "FROM capture LIMIT 1");

    if (!query.exec()) {
        qCritical() << "Failed to execute capture metadata query:" << query.lastError().text();
        return false;
    }
    
    if (!query.next()) {
        qCritical() << "No capture metadata found in database - capture table may be empty";
        return false;
    }

    captureId = query.value("capture_id").toInt();
    system = query.value("system").toString();
    decoder = query.value("decoder").toString();
    gitBranch = query.value("git_branch").toString();
    gitCommit = query.value("git_commit").toString();
    videoSampleRate = SqliteValue::toDoubleOrDefault(query, "video_sample_rate");
    activeVideoStart = SqliteValue::toIntOrDefault(query, "active_video_start");
    activeVideoEnd = SqliteValue::toIntOrDefault(query, "active_video_end");
    fieldWidth = SqliteValue::toIntOrDefault(query, "field_width");
    fieldHeight = SqliteValue::toIntOrDefault(query, "field_height");
    numberOfSequentialFields = SqliteValue::toIntOrDefault(query, "number_of_sequential_fields");
    colourBurstStart = SqliteValue::toIntOrDefault(query, "colour_burst_start");
    colourBurstEnd = SqliteValue::toIntOrDefault(query, "colour_burst_end");
    isMapped = SqliteValue::toBoolOrDefault(query, "is_mapped");
    isSubcarrierLocked = SqliteValue::toBoolOrDefault(query, "is_subcarrier_locked");
    isWidescreen = SqliteValue::toBoolOrDefault(query, "is_widescreen");
    white16bIre = SqliteValue::toIntOrDefault(query, "white_16b_ire");
    black16bIre = SqliteValue::toIntOrDefault(query, "black_16b_ire");
    captureNotes = query.value("capture_notes").toString();

    return true;
}

bool SqliteReader::readPcmAudioParameters(int captureId, int &bits, bool &isSigned,
                                        bool &isLittleEndian, double &sampleRate)
{
    QSqlQuery query(db);
    query.prepare("SELECT bits, is_signed, is_little_endian, sample_rate "
                 "FROM pcm_audio_parameters WHERE capture_id = ?");
    query.addBindValue(captureId);

    if (!query.exec() || !query.next()) {
        return false;
    }

    bits = SqliteValue::toIntOrDefault(query, "bits");
    isSigned = SqliteValue::toBoolOrDefault(query, "is_signed");
    isLittleEndian = SqliteValue::toBoolOrDefault(query, "is_little_endian");
    sampleRate = SqliteValue::toDoubleOrDefault(query, "sample_rate");

    return true;
}

bool SqliteReader::readFields(int captureId, QSqlQuery &fieldsQuery)
{
    fieldsQuery = QSqlQuery(db);
    fieldsQuery.prepare("SELECT field_id, audio_samples, decode_faults, disk_loc, "
                       "efm_t_values, field_phase_id, file_loc, is_first_field, "
                       "median_burst_ire, pad, sync_conf, ntsc_is_fm_code_data_valid, "
                       "ntsc_fm_code_data, ntsc_field_flag, ntsc_is_video_id_data_valid, "
                       "ntsc_video_id_data, ntsc_white_flag "
                       "FROM field_record WHERE capture_id = ? ORDER BY field_id");
    fieldsQuery.addBindValue(captureId);

    return fieldsQuery.exec();
}

bool SqliteReader::readFieldVitsMetrics(int captureId, int fieldId, double &wSnr, double &bPsnr)
{
    QSqlQuery query(db);
    query.prepare("SELECT w_snr, b_psnr FROM vits_metrics WHERE capture_id = ? AND field_id = ?");
    query.addBindValue(captureId);
    query.addBindValue(fieldId);

    if (!query.exec() || !query.next()) {
        return false;
    }

    wSnr = query.value("w_snr").toDouble();
    bPsnr = query.value("b_psnr").toDouble();

    return true;
}

bool SqliteReader::readFieldVbi(int captureId, int fieldId, int &vbi0, int &vbi1, int &vbi2)
{
    QSqlQuery query(db);
    query.prepare("SELECT vbi0, vbi1, vbi2 FROM vbi WHERE capture_id = ? AND field_id = ?");
    query.addBindValue(captureId);
    query.addBindValue(fieldId);

    if (!query.exec() || !query.next()) {
        return false;
    }

    vbi0 = query.value("vbi0").toInt();
    vbi1 = query.value("vbi1").toInt();
    vbi2 = query.value("vbi2").toInt();

    return true;
}

bool SqliteReader::readFieldVitc(int captureId, int fieldId, int vitcData[8])
{
    QSqlQuery query(db);
    query.prepare("SELECT vitc0, vitc1, vitc2, vitc3, vitc4, vitc5, vitc6, vitc7 "
                 "FROM vitc WHERE capture_id = ? AND field_id = ?");
    query.addBindValue(captureId);
    query.addBindValue(fieldId);

    if (!query.exec() || !query.next()) {
        return false;
    }

    vitcData[0] = query.value("vitc0").toInt();
    vitcData[1] = query.value("vitc1").toInt();
    vitcData[2] = query.value("vitc2").toInt();
    vitcData[3] = query.value("vitc3").toInt();
    vitcData[4] = query.value("vitc4").toInt();
    vitcData[5] = query.value("vitc5").toInt();
    vitcData[6] = query.value("vitc6").toInt();
    vitcData[7] = query.value("vitc7").toInt();

    return true;
}

bool SqliteReader::readFieldClosedCaption(int captureId, int fieldId, int &data0, int &data1)
{
    QSqlQuery query(db);
    query.prepare("SELECT data0, data1 FROM closed_caption WHERE capture_id = ? AND field_id = ?");
    query.addBindValue(captureId);
    query.addBindValue(fieldId);

    if (!query.exec() || !query.next()) {
        return false;
    }

    data0 = query.value("data0").toInt();
    data1 = query.value("data1").toInt();

    return true;
}

bool SqliteReader::readFieldDropouts(int captureId, int fieldId, QSqlQuery &dropoutsQuery)
{
    dropoutsQuery = QSqlQuery(db);
    dropoutsQuery.prepare("SELECT startx, endx, field_line FROM drop_outs "
                         "WHERE capture_id = ? AND field_id = ? ORDER BY startx");
    dropoutsQuery.addBindValue(captureId);
    dropoutsQuery.addBindValue(fieldId);

    return dropoutsQuery.exec();
}

// Optimized bulk read methods for better performance
bool SqliteReader::readAllFieldVitsMetrics(int captureId, QSqlQuery &vitsQuery)
{
    vitsQuery = QSqlQuery(db);
    vitsQuery.prepare("SELECT field_id, w_snr, b_psnr FROM vits_metrics "
                     "WHERE capture_id = ? ORDER BY field_id");
    vitsQuery.addBindValue(captureId);
    return vitsQuery.exec();
}

bool SqliteReader::readAllFieldVbi(int captureId, QSqlQuery &vbiQuery)
{
    vbiQuery = QSqlQuery(db);
    vbiQuery.prepare("SELECT field_id, vbi0, vbi1, vbi2 FROM vbi "
                    "WHERE capture_id = ? ORDER BY field_id");
    vbiQuery.addBindValue(captureId);
    return vbiQuery.exec();
}

bool SqliteReader::readAllFieldVitc(int captureId, QSqlQuery &vitcQuery)
{
    vitcQuery = QSqlQuery(db);
    vitcQuery.prepare("SELECT field_id, vitc0, vitc1, vitc2, vitc3, vitc4, vitc5, vitc6, vitc7 FROM vitc "
                     "WHERE capture_id = ? ORDER BY field_id");
    vitcQuery.addBindValue(captureId);
    return vitcQuery.exec();
}

bool SqliteReader::readAllFieldClosedCaptions(int captureId, QSqlQuery &ccQuery)
{
    ccQuery = QSqlQuery(db);
    ccQuery.prepare("SELECT field_id, data0, data1 FROM closed_caption "
                   "WHERE capture_id = ? ORDER BY field_id");
    ccQuery.addBindValue(captureId);
    return ccQuery.exec();
}

bool SqliteReader::readAllFieldDropouts(int captureId, QSqlQuery &dropoutsQuery)
{
    dropoutsQuery = QSqlQuery(db);
    dropoutsQuery.prepare("SELECT field_id, startx, endx, field_line FROM drop_outs "
                         "WHERE capture_id = ? ORDER BY field_id, startx");
    dropoutsQuery.addBindValue(captureId);
    return dropoutsQuery.exec();
}

SqliteWriter::SqliteWriter(const QString &fileName)
{
    // Create connection name based on filename and thread to avoid cross-thread issues
    QString threadId = QString::number(reinterpret_cast<qintptr>(QThread::currentThread()));
    connectionName = "sqlite_writer_" + QFileInfo(fileName).absoluteFilePath().replace('/', '_') + "_thread_" + threadId;
    
    // When creating a writer, we need to ensure any existing reader connections to the same file
    // are closed to avoid database locking issues when overwriting
    QString baseConnectionName = QFileInfo(fileName).absoluteFilePath().replace('/', '_');
    QStringList allConnections = QSqlDatabase::connectionNames();
    for (const QString &connName : allConnections) {
        if (connName.contains(baseConnectionName) && connName.contains("sqlite_reader")) {
            QSqlDatabase existingDb = QSqlDatabase::database(connName);
            if (existingDb.isValid() && existingDb.isOpen()) {
                existingDb.close();
            }
        }
    }
    
    // Check if connection already exists, if so reuse it
    if (QSqlDatabase::contains(connectionName)) {
        db = QSqlDatabase::database(connectionName);
    } else {
        // Create new database connection
        db = QSqlDatabase::addDatabase("QSQLITE", connectionName);
        db.setDatabaseName(fileName);
        
        if (!db.open()) {
            throwError("Failed to open database: " + db.lastError().text().toStdString());
        }
    }
}

SqliteWriter::~SqliteWriter()
{
    close();
}

void SqliteWriter::close()
{
    // Close the database connection
    if (db.isValid() && db.isOpen()) {
        db.close();
    }
    // Don't remove the connection - this causes the warning
    // Qt will clean up connections when the application exits
}

bool SqliteWriter::createSchema()
{
    tbcDebugStream() << "SqliteWriter::createSchema(): Starting schema creation";
    
    // Split schema into individual statements and execute them
    QStringList statements = SCHEMA_SQL.split(";", Qt::SkipEmptyParts);
    
    tbcDebugStream() << "Schema has" << statements.size() << "statements";
    
    for (int i = 0; i < statements.size(); ++i) {
        QString trimmed = statements[i].trimmed();
        if (trimmed.isEmpty()) continue;
        
        tbcDebugStream() << "Executing statement" << i+1 << ":" << trimmed.left(50) << "...";
        
        QSqlQuery query(db);
        if (!query.exec(trimmed)) {
            qCritical() << "Failed to execute statement" << i+1 << ":" << trimmed;
            qCritical() << "SQL Error:" << query.lastError().text();
            qCritical() << "Database connection valid:" << db.isValid() << "open:" << db.isOpen();
            return false;
        }
    }
    
    tbcDebugStream() << "Schema creation completed successfully";
    return true;
}

int SqliteWriter::writeCaptureMetadata(const QString &system, const QString &decoder,
                                     const QString &gitBranch, const QString &gitCommit,
                                     double videoSampleRate, int activeVideoStart, int activeVideoEnd,
                                     int fieldWidth, int fieldHeight, int numberOfSequentialFields,
                                     int colourBurstStart, int colourBurstEnd,
                                     bool isMapped, bool isSubcarrierLocked, bool isWidescreen,
                                     int white16bIre, int black16bIre, const QString &captureNotes)
{
    QSqlQuery query(db);
    query.prepare("INSERT INTO capture (system, decoder, git_branch, git_commit, "
                 "video_sample_rate, active_video_start, active_video_end, "
                 "field_width, field_height, number_of_sequential_fields, "
                 "colour_burst_start, colour_burst_end, is_mapped, is_subcarrier_locked, "
                 "is_widescreen, white_16b_ire, black_16b_ire, capture_notes) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");

    query.addBindValue(system);
    query.addBindValue(decoder);
    query.addBindValue(gitBranch.isEmpty() ? QVariant() : gitBranch);
    query.addBindValue(gitCommit.isEmpty() ? QVariant() : gitCommit);
    query.addBindValue(videoSampleRate);
    query.addBindValue(activeVideoStart);
    query.addBindValue(activeVideoEnd);
    query.addBindValue(fieldWidth);
    query.addBindValue(fieldHeight);
    query.addBindValue(numberOfSequentialFields);
    query.addBindValue(colourBurstStart);
    query.addBindValue(colourBurstEnd);
    query.addBindValue(isMapped ? 1 : 0);
    query.addBindValue(isSubcarrierLocked ? 1 : 0);
    query.addBindValue(isWidescreen ? 1 : 0);
    query.addBindValue(white16bIre);
    query.addBindValue(black16bIre);
    query.addBindValue(captureNotes.isEmpty() ? QVariant() : captureNotes);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert capture metadata:" << query.lastError().text();
        return -1;
    }

    return query.lastInsertId().toInt();
}

bool SqliteWriter::updateCaptureMetadata(int captureId, const QString &system, const QString &decoder,
                                       const QString &gitBranch, const QString &gitCommit,
                                       double videoSampleRate, int activeVideoStart, int activeVideoEnd,
                                       int fieldWidth, int fieldHeight, int numberOfSequentialFields,
                                       int colourBurstStart, int colourBurstEnd,
                                       bool isMapped, bool isSubcarrierLocked, bool isWidescreen,
                                       int white16bIre, int black16bIre, const QString &captureNotes)
{
    QSqlQuery query(db);
    query.prepare("UPDATE capture SET system=?, decoder=?, git_branch=?, git_commit=?, "
                 "video_sample_rate=?, active_video_start=?, active_video_end=?, "
                 "field_width=?, field_height=?, number_of_sequential_fields=?, "
                 "colour_burst_start=?, colour_burst_end=?, is_mapped=?, is_subcarrier_locked=?, "
                 "is_widescreen=?, white_16b_ire=?, black_16b_ire=?, capture_notes=? "
                 "WHERE capture_id=?");

    query.addBindValue(system);
    query.addBindValue(decoder);
    query.addBindValue(gitBranch.isEmpty() ? QVariant() : gitBranch);
    query.addBindValue(gitCommit.isEmpty() ? QVariant() : gitCommit);
    query.addBindValue(videoSampleRate);
    query.addBindValue(activeVideoStart);
    query.addBindValue(activeVideoEnd);
    query.addBindValue(fieldWidth);
    query.addBindValue(fieldHeight);
    query.addBindValue(numberOfSequentialFields);
    query.addBindValue(colourBurstStart);
    query.addBindValue(colourBurstEnd);
    query.addBindValue(isMapped ? 1 : 0);
    query.addBindValue(isSubcarrierLocked ? 1 : 0);
    query.addBindValue(isWidescreen ? 1 : 0);
    query.addBindValue(white16bIre);
    query.addBindValue(black16bIre);
    query.addBindValue(captureNotes.isEmpty() ? QVariant() : captureNotes);
    query.addBindValue(captureId);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to update capture metadata:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::writePcmAudioParameters(int captureId, int bits, bool isSigned,
                                         bool isLittleEndian, double sampleRate)
{
    QSqlQuery query(db);
    query.prepare("INSERT OR REPLACE INTO pcm_audio_parameters (capture_id, bits, is_signed, "
                 "is_little_endian, sample_rate) VALUES (?, ?, ?, ?, ?)");

    query.addBindValue(captureId);
    query.addBindValue(bits);
    query.addBindValue(isSigned ? 1 : 0);
    query.addBindValue(isLittleEndian ? 1 : 0);
    query.addBindValue(sampleRate);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert PCM audio parameters:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::writeField(int captureId, int fieldId, int audioSamples, int decodeFaults,
                            double diskLoc, int efmTValues, int fieldPhaseId, int fileLoc,
                            bool isFirstField, double medianBurstIre, bool pad, int syncConf,
                            bool ntscIsFmCodeDataValid, int ntscFmCodeData, bool ntscFieldFlag,
                            bool ntscIsVideoIdDataValid, int ntscVideoIdData, bool ntscWhiteFlag)
{
    QSqlQuery query(db);
    query.prepare("INSERT OR REPLACE INTO field_record (capture_id, field_id, audio_samples, decode_faults, "
                 "disk_loc, efm_t_values, field_phase_id, file_loc, is_first_field, "
                 "median_burst_ire, pad, sync_conf, ntsc_is_fm_code_data_valid, "
                 "ntsc_fm_code_data, ntsc_field_flag, ntsc_is_video_id_data_valid, "
                 "ntsc_video_id_data, ntsc_white_flag) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");

    query.addBindValue(captureId);
    query.addBindValue(fieldId);
    query.addBindValue(audioSamples);
    query.addBindValue(decodeFaults);
    query.addBindValue(diskLoc);
    query.addBindValue(efmTValues);
    query.addBindValue(fieldPhaseId);
    query.addBindValue(fileLoc);
    query.addBindValue(isFirstField ? 1 : 0);
    query.addBindValue(medianBurstIre);
    query.addBindValue(pad ? 1 : 0);
    query.addBindValue(syncConf);
    query.addBindValue(ntscIsFmCodeDataValid ? 1 : 0);
    query.addBindValue(ntscFmCodeData);
    query.addBindValue(ntscFieldFlag ? 1 : 0);
    query.addBindValue(ntscIsVideoIdDataValid ? 1 : 0);
    query.addBindValue(ntscVideoIdData);
    query.addBindValue(ntscWhiteFlag ? 1 : 0);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert field record:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::writeFieldVitsMetrics(int captureId, int fieldId, double wSnr, double bPsnr)
{
    QSqlQuery query(db);
    query.prepare("INSERT OR REPLACE INTO vits_metrics (capture_id, field_id, w_snr, b_psnr) VALUES (?, ?, ?, ?)");

    query.addBindValue(captureId);
    query.addBindValue(fieldId);
    query.addBindValue(wSnr);
    query.addBindValue(bPsnr);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert VITS metrics:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::writeFieldVbi(int captureId, int fieldId, int vbi0, int vbi1, int vbi2)
{
    QSqlQuery query(db);
    query.prepare("INSERT OR REPLACE INTO vbi (capture_id, field_id, vbi0, vbi1, vbi2) VALUES (?, ?, ?, ?, ?)");

    query.addBindValue(captureId);
    query.addBindValue(fieldId);
    query.addBindValue(vbi0);
    query.addBindValue(vbi1);
    query.addBindValue(vbi2);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert VBI:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::writeFieldVitc(int captureId, int fieldId, const int vitcData[8])
{
    QSqlQuery query(db);
    query.prepare("INSERT OR REPLACE INTO vitc (capture_id, field_id, vitc0, vitc1, vitc2, vitc3, "
                 "vitc4, vitc5, vitc6, vitc7) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");

    query.addBindValue(captureId);
    query.addBindValue(fieldId);
    for (int i = 0; i < 8; i++) {
        query.addBindValue(vitcData[i]);
    }

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert VITC:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::writeFieldClosedCaption(int captureId, int fieldId, int data0, int data1)
{
    QSqlQuery query(db);
    query.prepare("INSERT OR REPLACE INTO closed_caption (capture_id, field_id, data0, data1) VALUES (?, ?, ?, ?)");

    query.addBindValue(captureId);
    query.addBindValue(fieldId);
    query.addBindValue(data0);
    query.addBindValue(data1);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert closed caption:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::writeFieldDropouts(int captureId, int fieldId, int startx, int endx, int fieldLine)
{
    QSqlQuery query(db);
    query.prepare("INSERT OR REPLACE INTO drop_outs (capture_id, field_id, startx, endx, field_line) VALUES (?, ?, ?, ?, ?)");

    query.addBindValue(captureId);
    query.addBindValue(fieldId);
    query.addBindValue(startx);
    query.addBindValue(endx);
    query.addBindValue(fieldLine);

    if (!query.exec()) {
        tbcDebugStream() << "Failed to insert dropout:" << query.lastError().text();
        return false;
    }

    return true;
}

bool SqliteWriter::beginTransaction()
{
    return db.transaction();
}

bool SqliteWriter::commitTransaction()
{
    return db.commit();
}

bool SqliteWriter::rollbackTransaction()
{
    return db.rollback();
}
