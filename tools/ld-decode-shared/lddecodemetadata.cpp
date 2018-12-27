/************************************************************************

    lddecodemetadata.cpp

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

#include "lddecodemetadata.h"

LdDecodeMetaData::LdDecodeMetaData(QObject *parent) : QObject(parent)
{

}

// This method opens the JSON metadata file and reads the content into the
// metadata structure read for use
bool LdDecodeMetaData::read(QString fileName)
{
    // Open the JSON file
    qDebug() << "LdDecodeMetaData::read(): Loading JSON file" << fileName;
    QFile jsonFileHandle(fileName);

    // Open the JSON file
    if (!jsonFileHandle.open(QIODevice::ReadOnly)) {
        qWarning("Could not open JSON file!");
        return false;
    }

    // Read the file into our JSON document
    QJsonDocument jsonDocument;
    QString inputData;
    inputData = jsonFileHandle.readAll();
    jsonDocument = QJsonDocument::fromJson(inputData.toUtf8());
    QJsonObject document = jsonDocument.object(); // Note: fix for Qt 5.9 compatibility

    // Close the file
    jsonFileHandle.close();

    // Check input file is value
    if (jsonDocument.isNull()) {
        qWarning("Input JSON file could not be parsed!");
        return false;
    }

    // Read the video paramters
    if (!document["videoParameters"].isUndefined()) {
        // Read the video parameters
        QJsonObject jsonVideoParameters;
        jsonVideoParameters = document["videoParameters"].toObject();

        metaData.videoParameters.numberOfSequentialFields = jsonVideoParameters["numberOfSequentialFields"].toInt();
        metaData.videoParameters.isSourcePal = jsonVideoParameters["isSourcePal"].toBool();

        metaData.videoParameters.colourBurstStart = jsonVideoParameters["colourBurstStart"].toInt();
        metaData.videoParameters.colourBurstEnd = jsonVideoParameters["colourBurstEnd"].toInt();
        metaData.videoParameters.blackLevelStart = jsonVideoParameters["blackLevelStart"].toInt();
        metaData.videoParameters.blackLevelEnd = jsonVideoParameters["blackLevelEnd"].toInt();
        metaData.videoParameters.activeVideoStart = jsonVideoParameters["activeVideoStart"].toInt();
        metaData.videoParameters.activeVideoEnd = jsonVideoParameters["activeVideoEnd"].toInt();

        metaData.videoParameters.white16bIre = jsonVideoParameters["white16bIre"].toInt();
        metaData.videoParameters.black16bIre = jsonVideoParameters["black16bIre"].toInt();

        metaData.videoParameters.fieldWidth = jsonVideoParameters["fieldWidth"].toInt();
        metaData.videoParameters.fieldHeight = jsonVideoParameters["fieldHeight"].toInt();
        metaData.videoParameters.sampleRate = jsonVideoParameters["sampleRate"].toInt();
        metaData.videoParameters.fsc = jsonVideoParameters["fsc"].toInt();
    } else {
        qDebug() << "LdDecodeMetaData::read(): videoParameters is not defined";
    }

    if (!document["pcmAudioParameters"].isUndefined()) {
        // Read the PCM audio data
        QJsonObject pcmAudioParameters = document["pcmAudioParameters"].toObject();

        metaData.pcmAudioParameters.sampleRate = pcmAudioParameters["sampleRate"].toInt();
        metaData.pcmAudioParameters.isLittleEndian = pcmAudioParameters["isLittleEndian"].toBool();
        metaData.pcmAudioParameters.isSigned = pcmAudioParameters["isSigned"].toBool();
        metaData.pcmAudioParameters.bits = pcmAudioParameters["bits"].toInt();
    } else {
        qDebug() << "LdDecodeMetaData::read(): pcmAudioParameters is not defined";
    }

    QJsonArray jsonFields = document["fields"].toArray();
    if (!jsonFields.isEmpty()) {
        // Read the fields

        metaData.fields.resize(jsonFields.size());

        for (qint32 fieldNumber = 0; fieldNumber < jsonFields.size(); fieldNumber++) {
            Field fieldData;

            QJsonObject field;
            field = jsonFields[fieldNumber].toObject();

            fieldData.seqNo = field["seqNo"].toInt();

            fieldData.isFirstField = field["isFirstField"].toBool();
            fieldData.syncConf = field["syncConf"].toInt();
            fieldData.medianBurstIRE = field["medianBurstIRE"].toDouble();
            fieldData.fieldPhaseID = field["fieldPhaseID"].toInt();

            QJsonObject vits = field["vits"].toObject();
            if (!vits.isEmpty()) {
                fieldData.vits.inUse = true;
                fieldData.vits.snr = field["snr"].toDouble();
            } else {
                // Mark VITS as undefined
                fieldData.vits.inUse = false;
            }

            QJsonObject vbi = field["vbi"].toObject();
            if (!vbi.isEmpty()) {
                // Mark VBI as in use
                fieldData.vbi.inUse = true;

                fieldData.vbi.vbi16 = vbi["vbi16"].toInt();
                fieldData.vbi.vbi17 = vbi["vbi17"].toInt();
                fieldData.vbi.vbi18 = vbi["vbi18"].toInt();

                switch(vbi["type"].toInt()) {
                case 0:
                    fieldData.vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
                    break;
                case 1 :
                    fieldData.vbi.type = LdDecodeMetaData::VbiDiscTypes::clv;
                    break;
                case 2 :
                    fieldData.vbi.type = LdDecodeMetaData::VbiDiscTypes::cav;
                    break;
                default:
                    fieldData.vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
                }

                fieldData.vbi.leadIn = vbi["leadIn"].toBool();
                fieldData.vbi.leadOut = vbi["leadOut"].toBool();
                fieldData.vbi.userCode = vbi["userCode"].toString();
                fieldData.vbi.picNo = vbi["picNo"].toInt();
                fieldData.vbi.picStop = vbi["picStop"].toBool();
                fieldData.vbi.chNo = vbi["chNo"].toInt();

                QJsonObject timeCode = vbi["timeCode"].toObject();
                fieldData.vbi.timeCode.hr = timeCode["hr"].toInt();
                fieldData.vbi.timeCode.min = timeCode["min"].toInt();

                // Original programme status code
                QJsonObject statusCode = vbi["statusCode"].toObject();
                fieldData.vbi.statusCode.valid = statusCode["valid"].toBool();
                fieldData.vbi.statusCode.cx = statusCode["cx"].toBool();
                fieldData.vbi.statusCode.size = statusCode["size"].toBool();
                fieldData.vbi.statusCode.side = statusCode["side"].toBool();
                fieldData.vbi.statusCode.teletext = statusCode["teletext"].toBool();
                fieldData.vbi.statusCode.dump = statusCode["dump"].toBool();
                fieldData.vbi.statusCode.fm = statusCode["fm"].toBool();
                fieldData.vbi.statusCode.digital = statusCode["digital"].toBool();

                switch (statusCode["soundMode"].toInt()) {
                case 0:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
                    break;
                case 1:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
                    break;
                case 2:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
                    break;
                case 3:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
                    break;
                case 4:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
                    break;
                case 5:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
                    break;
                case 6:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
                    break;
                case 7:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
                    break;
                case 8:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
                    break;
                case 9:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
                    break;
                case 10:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
                    break;
                case 11:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                default:
                    fieldData.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                }
                fieldData.vbi.statusCode.parity = statusCode["parity"].toBool();

                // Amendment 2 programme status code
                QJsonObject statusCodeAm2 = vbi["statusCodeAm2"].toObject();
                fieldData.vbi.statusCodeAm2.valid = statusCodeAm2["valid"].toBool();
                fieldData.vbi.statusCodeAm2.cx = statusCodeAm2["cx"].toBool();
                fieldData.vbi.statusCodeAm2.size = statusCodeAm2["size"].toBool();
                fieldData.vbi.statusCodeAm2.side = statusCodeAm2["side"].toBool();
                fieldData.vbi.statusCodeAm2.teletext = statusCodeAm2["teletext"].toBool();
                fieldData.vbi.statusCodeAm2.copy = statusCodeAm2["copy"].toBool();
                fieldData.vbi.statusCodeAm2.standard = statusCodeAm2["standard"].toBool();

                switch (statusCodeAm2["soundMode"].toInt()) {
                case 0:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
                    break;
                case 1:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
                    break;
                case 2:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
                    break;
                case 3:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
                    break;
                case 4:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
                    break;
                case 5:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
                    break;
                case 6:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
                    break;
                case 7:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
                    break;
                case 8:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
                    break;
                case 9:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
                    break;
                case 10:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
                    break;
                case 11:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                default:
                    fieldData.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                }

                QJsonObject clvPicNo = vbi["clvPicNo"].toObject();
                fieldData.vbi.clvPicNo.sec = clvPicNo["sec"].toInt();
                fieldData.vbi.clvPicNo.picNo = clvPicNo["picNo"].toInt();
            } else {
                // Mark VBI as undefined
                fieldData.vbi.inUse = false;
            }

            // Read the NTSC specific record
            QJsonObject ntsc = field["ntsc"].toObject();
            if (!ntsc.isEmpty()) {
                // Mark as in use
                fieldData.ntsc.inUse = true;

                fieldData.ntsc.isFmCodeDataValid = ntsc["isFmCodeDataValid"].toBool();
                fieldData.ntsc.fmCodeData = ntsc["fmCodeData"].toInt();
                fieldData.ntsc.fieldFlag = ntsc["fieldFlag"].toBool();
                fieldData.ntsc.whiteFlag = ntsc["whiteFlag"].toBool();
            } else {
                // Mark ntscSpecific as undefined
                fieldData.ntsc.inUse = false;
            }

            // Read the drop-outs object
            QJsonObject dropOuts = field["dropOuts"].toObject();

            QJsonArray startx = dropOuts["startx"].toArray();
            QJsonArray endx = dropOuts["endx"].toArray();
            QJsonArray fieldLine = dropOuts["fieldLine"].toArray();

            for (qint32 doCounter = 0; doCounter < startx.size(); doCounter++) {
                fieldData.dropOuts.startx.append(startx[doCounter].toInt());
                fieldData.dropOuts.endx.append(endx[doCounter].toInt());
                fieldData.dropOuts.fieldLine.append(fieldLine[doCounter].toInt());
            }

            // Insert field data into the vector
            metaData.fields[fieldNumber] = fieldData;
        }
    }  else {
        qDebug() << "LdDecodeMetaData::read(): fields object is not defined";
    }

    return true;
}

// This method copies the metadata structure into a JSON metadata file
bool LdDecodeMetaData::write(QString fileName)
{
    QJsonObject lddecodeJson;

    // Write the video parameters and fields
    QJsonObject jsonVideoParameters;
    QJsonArray jsonFields;

    // Write the video paramters
    jsonVideoParameters.insert("numberOfSequentialFields", metaData.videoParameters.numberOfSequentialFields);
    jsonVideoParameters.insert("isSourcePal", metaData.videoParameters.isSourcePal);

    jsonVideoParameters.insert("colourBurstStart", metaData.videoParameters.colourBurstStart);
    jsonVideoParameters.insert("colourBurstEnd", metaData.videoParameters.colourBurstEnd);
    jsonVideoParameters.insert("blackLevelStart", metaData.videoParameters.blackLevelStart);
    jsonVideoParameters.insert("blackLevelEnd", metaData.videoParameters.blackLevelEnd);
    jsonVideoParameters.insert("activeVideoStart", metaData.videoParameters.activeVideoStart);
    jsonVideoParameters.insert("activeVideoEnd", metaData.videoParameters.activeVideoEnd);

    jsonVideoParameters.insert("white16bIre", metaData.videoParameters.white16bIre);
    jsonVideoParameters.insert("black16bIre", metaData.videoParameters.black16bIre);

    jsonVideoParameters.insert("fieldWidth", metaData.videoParameters.fieldWidth);
    jsonVideoParameters.insert("fieldHeight", metaData.videoParameters.fieldHeight);
    jsonVideoParameters.insert("sampleRate", metaData.videoParameters.sampleRate);
    jsonVideoParameters.insert("fsc", metaData.videoParameters.fsc);

    // Add the video parameters to the parent object
    lddecodeJson.insert("videoParameters", jsonVideoParameters);

    // Write the PCM audio parameters
    QJsonObject pcmAudioParameters;
    pcmAudioParameters.insert("sampleRate", metaData.pcmAudioParameters.sampleRate);
    pcmAudioParameters.insert("isLittleEndian", metaData.pcmAudioParameters.isLittleEndian);
    pcmAudioParameters.insert("isSigned", metaData.pcmAudioParameters.isSigned);
    pcmAudioParameters.insert("bits", metaData.pcmAudioParameters.bits);

    // Add the audio parameters to the parent object
    lddecodeJson.insert("pcmAudioParameters", pcmAudioParameters);

    // Write the field data
    if (!metaData.fields.isEmpty()) {
        QJsonArray fields;

        qDebug() << "LdDecodeMetaData::write(): metadata struct contains" << metaData.fields.size() << "fields";

        for (qint32 fieldNumber = 0; fieldNumber < metaData.fields.size(); fieldNumber++) {
            QJsonObject field;

            field.insert("seqNo", metaData.fields[fieldNumber].seqNo);

            field.insert("isFirstField", metaData.fields[fieldNumber].isFirstField);
            field.insert("syncConf", metaData.fields[fieldNumber].syncConf);
            field.insert("medianBurstIRE", metaData.fields[fieldNumber].medianBurstIRE);
            field.insert("fieldPhaseID", metaData.fields[fieldNumber].fieldPhaseID);

            // Write the VITS data if in use
            if (metaData.fields[fieldNumber].vits.inUse) {
                QJsonObject vits;
                vits.insert("snr", metaData.fields[fieldNumber].vits.snr);

                // Add the vits to the field
                field.insert("vits", vits);
            }

            // Write the VBI data if in use
            if (metaData.fields[fieldNumber].vbi.inUse) {
                QJsonObject vbi;

                vbi.insert("vbi16", metaData.fields[fieldNumber].vbi.vbi16);
                vbi.insert("vbi17", metaData.fields[fieldNumber].vbi.vbi17);
                vbi.insert("vbi18", metaData.fields[fieldNumber].vbi.vbi18);

                switch(metaData.fields[fieldNumber].vbi.type) {
                case LdDecodeMetaData::VbiDiscTypes::unknownDiscType:
                    vbi.insert("type", 0);
                    break;
                case LdDecodeMetaData::VbiDiscTypes::clv:
                    vbi.insert("type", 1);
                    break;
                case LdDecodeMetaData::VbiDiscTypes::cav:
                    vbi.insert("type", 2);
                    break;
                }

                vbi.insert("leadIn", metaData.fields[fieldNumber].vbi.leadIn);
                vbi.insert("leadOut", metaData.fields[fieldNumber].vbi.leadOut);
                vbi.insert("userCode", metaData.fields[fieldNumber].vbi.userCode);
                vbi.insert("picNo", metaData.fields[fieldNumber].vbi.picNo);
                vbi.insert("picStop", metaData.fields[fieldNumber].vbi.picStop);
                vbi.insert("chNo", metaData.fields[fieldNumber].vbi.chNo);

                QJsonObject timeCode;
                timeCode.insert("hr", metaData.fields[fieldNumber].vbi.timeCode.hr);
                timeCode.insert("min", metaData.fields[fieldNumber].vbi.timeCode.min);
                vbi.insert("timeCode", timeCode);

                // Original programme status code
                QJsonObject statusCode;
                statusCode.insert("valid", metaData.fields[fieldNumber].vbi.statusCode.valid);
                statusCode.insert("cx", metaData.fields[fieldNumber].vbi.statusCode.cx);
                statusCode.insert("size", metaData.fields[fieldNumber].vbi.statusCode.size);
                statusCode.insert("side", metaData.fields[fieldNumber].vbi.statusCode.side);
                statusCode.insert("teletext", metaData.fields[fieldNumber].vbi.statusCode.teletext);
                statusCode.insert("dump", metaData.fields[fieldNumber].vbi.statusCode.dump);
                statusCode.insert("fm", metaData.fields[fieldNumber].vbi.statusCode.fm);
                statusCode.insert("digital", metaData.fields[fieldNumber].vbi.statusCode.digital);

                switch (metaData.fields[fieldNumber].vbi.statusCode.soundMode) {
                case LdDecodeMetaData::VbiSoundModes::stereo:
                    statusCode.insert("soundMode", 0);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono:
                    statusCode.insert("soundMode", 1);
                    break;
                case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
                    statusCode.insert("soundMode", 2);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual:
                    statusCode.insert("soundMode", 3);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
                    statusCode.insert("soundMode", 4);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
                    statusCode.insert("soundMode", 5);
                    break;
                case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
                    statusCode.insert("soundMode", 6);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
                    statusCode.insert("soundMode", 7);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono_dump:
                    statusCode.insert("soundMode", 8);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_dump:
                    statusCode.insert("soundMode", 9);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
                    statusCode.insert("soundMode", 10);
                    break;
                case LdDecodeMetaData::VbiSoundModes::futureUse:
                    statusCode.insert("soundMode", 11);
                    break;
                }
                statusCode["parity"] = metaData.fields[fieldNumber].vbi.statusCode.parity;
                vbi.insert("statusCode", statusCode);

                // Amendment 2 programme status code
                QJsonObject statusCodeAm2;
                statusCodeAm2.insert("valid", metaData.fields[fieldNumber].vbi.statusCodeAm2.valid);
                statusCodeAm2.insert("cx", metaData.fields[fieldNumber].vbi.statusCodeAm2.cx);
                statusCodeAm2.insert("size", metaData.fields[fieldNumber].vbi.statusCodeAm2.size);
                statusCodeAm2.insert("side", metaData.fields[fieldNumber].vbi.statusCodeAm2.side);
                statusCodeAm2.insert("teletext", metaData.fields[fieldNumber].vbi.statusCodeAm2.teletext);
                statusCodeAm2.insert("copy", metaData.fields[fieldNumber].vbi.statusCodeAm2.copy);
                statusCodeAm2.insert("standard", metaData.fields[fieldNumber].vbi.statusCodeAm2.standard);

                switch (metaData.fields[fieldNumber].vbi.statusCodeAm2.soundMode) {
                case LdDecodeMetaData::VbiSoundModes::stereo:
                    statusCodeAm2.insert("soundMode", 0);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono:
                    statusCodeAm2.insert("soundMode", 1);
                    break;
                case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
                    statusCodeAm2.insert("soundMode", 2);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual:
                    statusCodeAm2.insert("soundMode", 3);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
                    statusCodeAm2.insert("soundMode", 4);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
                    statusCodeAm2.insert("soundMode", 5);
                    break;
                case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
                    statusCodeAm2.insert("soundMode", 6);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
                    statusCodeAm2.insert("soundMode", 7);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono_dump:
                    statusCodeAm2.insert("soundMode", 8);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_dump:
                    statusCodeAm2.insert("soundMode", 9);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
                    statusCodeAm2.insert("soundMode", 10);
                    break;
                case LdDecodeMetaData::VbiSoundModes::futureUse:
                    statusCodeAm2.insert("soundMode", 11);
                    break;
                }
                vbi.insert("statusCodeAm2", statusCodeAm2);

                QJsonObject clvPicNo;
                clvPicNo.insert("sec", metaData.fields[fieldNumber].vbi.clvPicNo.sec);
                clvPicNo.insert("picNo", metaData.fields[fieldNumber].vbi.clvPicNo.picNo);
                vbi.insert("clvPicNo", clvPicNo);

                // Add the vbi to the field
                field.insert("vbi", vbi);
            }

            // Write the NTSC specific record if in use
            if (metaData.fields[fieldNumber].ntsc.inUse) {
                QJsonObject ntsc;
                ntsc.insert("isFmCodeDataValid", metaData.fields[fieldNumber].ntsc.isFmCodeDataValid);
                if (metaData.fields[fieldNumber].ntsc.isFmCodeDataValid)
                    ntsc.insert("fmCodeData", metaData.fields[fieldNumber].ntsc.fmCodeData);
                else ntsc.insert("fmCodeData", -1);
                ntsc.insert("fieldFlag", metaData.fields[fieldNumber].ntsc.fieldFlag);
                ntsc.insert("whiteFlag", metaData.fields[fieldNumber].ntsc.whiteFlag);

                // Add the NTSC specific data to the field
                field.insert("ntsc", ntsc);
            }

            // Write the drop-out records
            if (metaData.fields[fieldNumber].dropOuts.startx.size() != 0) {
                QJsonObject dropOuts;
                QJsonArray startx;
                QJsonArray endx;
                QJsonArray fieldLine;

                // Populate the arrays with the drop out metadata
                for (qint32 doCounter = 0; doCounter < metaData.fields[fieldNumber].dropOuts.startx.size(); doCounter++) {
                    startx.append(metaData.fields[fieldNumber].dropOuts.startx[doCounter]);
                    endx.append(metaData.fields[fieldNumber].dropOuts.endx[doCounter]);
                    fieldLine.append(metaData.fields[fieldNumber].dropOuts.fieldLine[doCounter]);
                }

                // Add the drop out arrays to the dropOuts object
                dropOuts.insert("startx", startx);
                dropOuts.insert("endx", endx);
                dropOuts.insert("fieldLine", fieldLine);

                // Add the drop-outs object to the field object
                field.insert("dropOuts", dropOuts);
            }

            // Insert field data into the field array
            fields.insert(fieldNumber, field);
        }

        // Add the fields to the parent object
        lddecodeJson.insert("fields", fields);
    }

    // Add the JSON data to the document
    qDebug() << "Creating the JSON document";
    QJsonDocument document(lddecodeJson);

    // Write the json document to a file
    qDebug() << "LdDecodeMetaData::write(): Saving JSON file" << fileName;
    QFile jsonFileHandle(fileName);

    if (!jsonFileHandle.open(QIODevice::WriteOnly)) {
        qWarning("Could not save JSON file!");
        return false;
    }

    jsonFileHandle.write(document.toJson(QJsonDocument::Indented));
    jsonFileHandle.close();

    return true;
}

LdDecodeMetaData::VideoParameters LdDecodeMetaData::getVideoParameters(void)
{
    return metaData.videoParameters;
}

void LdDecodeMetaData::setVideoParameters (LdDecodeMetaData::VideoParameters videoParametersParam)
{
    metaData.videoParameters = videoParametersParam;
}

LdDecodeMetaData::PcmAudioParameters LdDecodeMetaData::getPcmAudioParameters(void)
{
    return metaData.pcmAudioParameters;
}

void LdDecodeMetaData::setPcmAudioParameters(LdDecodeMetaData::PcmAudioParameters pcmAudioParam)
{
    metaData.pcmAudioParameters = pcmAudioParam;
}

LdDecodeMetaData::Field LdDecodeMetaData::getField(qint32 sequentialFieldNumber)
{
    if ((sequentialFieldNumber - 1) >= metaData.fields.size()) {
        qCritical() << "LdDecodeMetaData::getField(): Requested field number" << sequentialFieldNumber << "out of bounds!";

        // We have to construct a dummy result to prevent segfaults on return
        LdDecodeMetaData::Field field;
        field.seqNo = -1;
        field.isFirstField = false;
        field.syncConf = -1;
        field.medianBurstIRE = -1;
        field.fieldPhaseID = -1;
        field.vits.inUse = false;
        field.vbi.inUse = false;
        field.vbi.vbi16 = -1;
        field.vbi.vbi17 = -1;
        field.vbi.vbi18 = -1;
        field.vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
        field.vbi.leadIn = false;
        field.vbi.leadOut = false;
        field.vbi.picNo = -1;
        field.vbi.picStop = false;
        field.vbi.chNo = -1;
        field.vbi.timeCode.hr = -1;
        field.vbi.timeCode.min = -1;
        field.vbi.clvPicNo.sec = -1;
        field.vbi.clvPicNo.picNo = -1;
        field.vbi.statusCode.cx = false;
        field.vbi.statusCode.fm = false;
        field.vbi.statusCode.dump = false;
        field.vbi.statusCode.side = false;
        field.vbi.statusCode.size = false;
        field.vbi.statusCode.valid = false;
        field.vbi.statusCode.parity = false;
        field.vbi.statusCode.digital = false;
        field.vbi.statusCode.teletext = false;
        field.vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
        field.vbi.statusCodeAm2.cx = false;
        field.vbi.statusCodeAm2.copy = false;
        field.vbi.statusCodeAm2.side = false;
        field.vbi.statusCodeAm2.size = false;
        field.vbi.statusCodeAm2.valid = false;
        field.vbi.statusCodeAm2.standard = false;
        field.vbi.statusCodeAm2.teletext = false;
        field.vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
        field.ntsc.inUse = false;
        field.ntsc.fieldFlag = false;
        field.ntsc.whiteFlag = false;
        field.ntsc.fmCodeData = -1;
        field.ntsc.isFmCodeDataValid = false;

        return field;
    }
    return metaData.fields[sequentialFieldNumber - 1];
}

void LdDecodeMetaData::appendField(LdDecodeMetaData::Field fieldParam)
{
    metaData.fields.append(fieldParam);
}

void LdDecodeMetaData::updateField(LdDecodeMetaData::Field fieldParam, qint32 sequentialFieldNumber)
{
    if ((sequentialFieldNumber - 1) >= metaData.fields.size()) {
        qCritical() << "LdDecodeMetaData::updateField(): Requested field number" << sequentialFieldNumber << "out of bounds!";
        return;
    }
    metaData.fields[sequentialFieldNumber - 1] = fieldParam;
}

// Method to get the available number of fields
qint32 LdDecodeMetaData::getNumberOfFields(void)
{
    return metaData.fields.size();
}

// Method to get the available number of frames
qint32 LdDecodeMetaData::getNumberOfFrames(void)
{
    qint32 frameOffset = 0;

    // It's possible that the TBC file will start on the wrong field, so we have to allow for
    // that here by skipping a field if the order isn't right
    if (!getField(1).isFirstField) frameOffset++;

    return (getNumberOfFields() / 2) - frameOffset;
}

// Method to get the first and second field numbers based on the frame number
qint32 LdDecodeMetaData::getFieldNumber(qint32 frameNumber, qint32 field)
{
    // Point at the first field in the TBC file (according to the current frame number)
    qint32 firstFieldNumber = (frameNumber * 2) - 1;
    qint32 secondFieldNumber = firstFieldNumber + 1;
    LdDecodeMetaData::Vbi firstFieldVbi = getField(firstFieldNumber).vbi;

    // Ensure that the first sequential field in the TBC file has 'isFirstField' set
    if (!getField(1).isFirstField) {
        if (firstFieldVbi.inUse && (firstFieldVbi.picNo == -1 && firstFieldVbi.timeCode.min == -1)) {
            // If the first sequential field isFirstField = false AND the current first field doesn't have a time-code or
            // CAV picture number set; advance one field (TBC file is out of field order)
            firstFieldNumber++;
            secondFieldNumber++;
        } else {
            // If the first sequential field isFirstField = false AND the current first field does have a time-code or
            // CAV picture number set; filp the frame order (source has reversed field order)
            qint32 temp = firstFieldNumber;
            firstFieldNumber = secondFieldNumber;
            secondFieldNumber = temp;
        }
    }

    // Range check the first field number
    if (firstFieldNumber > getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldNumber(): First field number exceed the available number of fields!";
        return -1;
    }

    // Range check the second field number
    if (secondFieldNumber > getNumberOfFields()) {
        qCritical() << "LdDecodeMetaData::getFieldNumber(): Second field number exceed the available number of fields!";
        return -1;
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
