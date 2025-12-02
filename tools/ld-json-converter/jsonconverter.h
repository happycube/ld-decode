/******************************************************************************
 * jsonconverter.h
 * ld-json-converter - JSON converter tool for ld-decode
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef JSONCONVERTER_H
#define JSONCONVERTER_H

#include <QString>
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QSqlError>
#include "lddecodemetadata.h"

class JsonConverter
{
public:
    JsonConverter(const QString &inputJsonFilename, const QString &outputSqliteFilename);
    ~JsonConverter();

    bool process();

private:
    QString m_inputJsonFilename;
    QString m_outputSqliteFilename;
    QSqlDatabase m_database;

    void reportJsonContents(LdDecodeMetaData &metaData);
    void countDropouts(const LdDecodeMetaData &metaData, qint32 &totalDropouts);
    bool createDatabase();
    bool createSchema();
    bool insertData(LdDecodeMetaData &metaData);
};

#endif // JSONCONVERTER_H