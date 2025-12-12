/******************************************************************************
 * sqliteio.h
 * ld-decode-tools TBC library
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef SQLITEIO_H
#define SQLITEIO_H

#include <QString>
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QSqlError>
#include <QVariant>
#include <stdexcept>

namespace SqliteValue
{
    int toIntOrDefault(const QSqlQuery &query, const char *column, int defaultValue = -1);
    qint64 toLongLongOrDefault(const QSqlQuery &query, const char *column, qint64 defaultValue = -1);
    double toDoubleOrDefault(const QSqlQuery &query, const char *column, double defaultValue = -1.0);
    bool toBoolOrDefault(const QSqlQuery &query, const char *column, bool defaultValue = false);
}

class SqliteReader
{
public:
    SqliteReader(const QString &fileName);
    ~SqliteReader();
    
    // Explicitly close the database connection
    void close();

    // Exception class to be thrown when parsing fails
    class Error : public std::runtime_error
    {
    public:
        Error(std::string message) : std::runtime_error(message) {}
    };

    // Throw an Error exception with the given message
    [[noreturn]] void throwError(std::string message) {
        throw Error(message);
    }

    // Read capture-level metadata
    bool readCaptureMetadata(int &captureId, QString &system, QString &decoder,
                           QString &gitBranch, QString &gitCommit,
                           double &videoSampleRate, int &activeVideoStart, int &activeVideoEnd,
                           int &fieldWidth, int &fieldHeight, int &numberOfSequentialFields,
                           int &colourBurstStart, int &colourBurstEnd,
                           bool &isMapped, bool &isSubcarrierLocked, bool &isWidescreen,
                           int &white16bIre, int &black16bIre, QString &captureNotes);

    // Read PCM audio parameters
    bool readPcmAudioParameters(int captureId, int &bits, bool &isSigned,
                              bool &isLittleEndian, double &sampleRate);

    // Read field metadata
    bool readFields(int captureId, QSqlQuery &fieldsQuery);

    // Read field-specific data (individual queries - slower)
    bool readFieldVitsMetrics(int captureId, int fieldId, double &wSnr, double &bPsnr);
    bool readFieldVbi(int captureId, int fieldId, int &vbi0, int &vbi1, int &vbi2);
    bool readFieldVitc(int captureId, int fieldId, int vitcData[8]);
    bool readFieldClosedCaption(int captureId, int fieldId, int &data0, int &data1);
    bool readFieldDropouts(int captureId, int fieldId, QSqlQuery &dropoutsQuery);

    // Optimized bulk read methods for all fields (much faster)
    bool readAllFieldVitsMetrics(int captureId, QSqlQuery &vitsQuery);
    bool readAllFieldVbi(int captureId, QSqlQuery &vbiQuery);
    bool readAllFieldVitc(int captureId, QSqlQuery &vitcQuery);
    bool readAllFieldClosedCaptions(int captureId, QSqlQuery &ccQuery);
    bool readAllFieldDropouts(int captureId, QSqlQuery &dropoutsQuery);

private:
    QSqlDatabase db;
    QString connectionName;
};

class SqliteWriter
{
public:
    SqliteWriter(const QString &fileName);
    ~SqliteWriter();
    
    // Explicitly close the database connection
    void close();

    // Exception class to be thrown when writing fails
    class Error : public std::runtime_error
    {
    public:
        Error(std::string message) : std::runtime_error(message) {}
    };

    // Throw an Error exception with the given message
    [[noreturn]] void throwError(std::string message) {
        throw Error(message);
    }

    // Initialize database with schema
    bool createSchema();

    // Write capture-level metadata
    int writeCaptureMetadata(const QString &system, const QString &decoder,
                           const QString &gitBranch, const QString &gitCommit,
                           double videoSampleRate, int activeVideoStart, int activeVideoEnd,
                           int fieldWidth, int fieldHeight, int numberOfSequentialFields,
                           int colourBurstStart, int colourBurstEnd,
                           bool isMapped, bool isSubcarrierLocked, bool isWidescreen,
                           int white16bIre, int black16bIre, const QString &captureNotes);

    // Update existing capture metadata  
    bool updateCaptureMetadata(int captureId, const QString &system, const QString &decoder,
                             const QString &gitBranch, const QString &gitCommit,
                             double videoSampleRate, int activeVideoStart, int activeVideoEnd,
                             int fieldWidth, int fieldHeight, int numberOfSequentialFields,
                             int colourBurstStart, int colourBurstEnd,
                             bool isMapped, bool isSubcarrierLocked, bool isWidescreen,
                             int white16bIre, int black16bIre, const QString &captureNotes);

    // Write PCM audio parameters
    bool writePcmAudioParameters(int captureId, int bits, bool isSigned,
                               bool isLittleEndian, double sampleRate);

    // Write field metadata
    bool writeField(int captureId, int fieldId, int audioSamples, int decodeFaults,
                   double diskLoc, int efmTValues, int fieldPhaseId, int fileLoc,
                   bool isFirstField, double medianBurstIre, bool pad, int syncConf,
                   bool ntscIsFmCodeDataValid, int ntscFmCodeData, bool ntscFieldFlag,
                   bool ntscIsVideoIdDataValid, int ntscVideoIdData, bool ntscWhiteFlag);

    // Write field-specific data
    bool writeFieldVitsMetrics(int captureId, int fieldId, double wSnr, double bPsnr);
    bool writeFieldVbi(int captureId, int fieldId, int vbi0, int vbi1, int vbi2);
    bool writeFieldVitc(int captureId, int fieldId, const int vitcData[8]);
    bool writeFieldClosedCaption(int captureId, int fieldId, int data0, int data1);
    bool writeFieldDropouts(int captureId, int fieldId, int startx, int endx, int fieldLine);

    // Transaction support
    bool beginTransaction();
    bool commitTransaction();
    bool rollbackTransaction();

private:
    QSqlDatabase db;
    QString connectionName;
};

#endif // SQLITEIO_H