/******************************************************************************
 * metadataconverter.h
 * ld-export-decode-metadata - metadata export tool for ld-decode
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef JSONCONVERTER_H
#define JSONCONVERTER_H

#include <QString>
#include "lddecodemetadata.h"
#include "exportmetadata.h"

class MetadataConverter
{
public:
    MetadataConverter(const QString &inputSqliteFilename, const QString &outputJsonFilename);
    ~MetadataConverter();

    bool process();

private:
    QString m_inputSqliteFilename;
    QString m_outputJsonFilename;

    void convertVideoParamters(const LdDecodeMetaData::VideoParameters &in_VideoParameters,
                               ExportMetaData::VideoParameters &out_VideoParameters);
    void convertPcmAudioParamters(const LdDecodeMetaData::PcmAudioParameters &in_PcmAudioParameters,
                                  ExportMetaData::PcmAudioParameters &out_PcmAudioParameters);
    void convertField(const LdDecodeMetaData::Field &in_field,
                      ExportMetaData::Field &out_field);
};

#endif // JSONCONVERTER_H