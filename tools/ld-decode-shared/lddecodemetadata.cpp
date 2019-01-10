/************************************************************************

    lddecodemetadata.cpp

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

#include "lddecodemetadata.h"

LdDecodeMetaData::LdDecodeMetaData(QObject *parent) : QObject(parent)
{
    // Set defaults
    isFirstFieldFirst = false;
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
            fieldData.audioSamples = field["audioSamples"].toInt();

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

                QJsonArray jsonVbiData = vbi["vbiData"].toArray();
                fieldData.vbi.vbiData.append(jsonVbiData[0].toInt()); // Line 16
                fieldData.vbi.vbiData.append(jsonVbiData[1].toInt()); // Line 17
                fieldData.vbi.vbiData.append(jsonVbiData[2].toInt()); // Line 18

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

                fieldData.vbi.userCode = vbi["userCode"].toString();
                fieldData.vbi.picNo = vbi["picNo"].toInt();
                fieldData.vbi.chNo = vbi["chNo"].toInt();
                fieldData.vbi.clvHr = vbi["clvHr"].toInt();
                fieldData.vbi.clvMin = vbi["clvMin"].toInt();
                fieldData.vbi.clvSec = vbi["clvSec"].toInt();
                fieldData.vbi.clvPicNo = vbi["clvPicNo"].toInt();

                switch (vbi["soundMode"].toInt()) {
                case 0:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
                    break;
                case 1:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
                    break;
                case 2:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
                    break;
                case 3:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
                    break;
                case 4:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
                    break;
                case 5:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
                    break;
                case 6:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
                    break;
                case 7:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
                    break;
                case 8:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
                    break;
                case 9:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
                    break;
                case 10:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
                    break;
                case 11:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                default:
                    fieldData.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                }

                switch (vbi["soundModeAm2"].toInt()) {
                case 0:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo;
                    break;
                case 1:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono;
                    break;
                case 2:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
                    break;
                case 3:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual;
                    break;
                case 4:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
                    break;
                case 5:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
                    break;
                case 6:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
                    break;
                case 7:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
                    break;
                case 8:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono_dump;
                    break;
                case 9:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_dump;
                    break;
                case 10:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
                    break;
                case 11:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                default:
                    fieldData.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                }

                // Get the boolean flags field (contains 13 boolean flags from the VBI)
                qint32 booleanFlags = vbi["flags"].toInt();

                // Interpret the flags
                fieldData.vbi.leadIn =      ((booleanFlags & 0x0001) == 0x0001);
                fieldData.vbi.leadOut =     ((booleanFlags & 0x0002) == 0x0002);
                fieldData.vbi.picStop =     ((booleanFlags & 0x0004) == 0x0004);
                fieldData.vbi.cx =          ((booleanFlags & 0x0008) == 0x0008);
                fieldData.vbi.size =        ((booleanFlags & 0x0010) == 0x0010);
                fieldData.vbi.side =        ((booleanFlags & 0x0020) == 0x0020);
                fieldData.vbi.teletext =    ((booleanFlags & 0x0040) == 0x0040);
                fieldData.vbi.dump =        ((booleanFlags & 0x0080) == 0x0080);
                fieldData.vbi.fm =          ((booleanFlags & 0x0100) == 0x0100);
                fieldData.vbi.digital =     ((booleanFlags & 0x0200) == 0x0200);
                fieldData.vbi.parity =      ((booleanFlags & 0x0400) == 0x0400);
                fieldData.vbi.copyAm2 =     ((booleanFlags & 0x0800) == 0x0800);
                fieldData.vbi.standardAm2 = ((booleanFlags & 0x1000) == 0x1000);
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

    // Determine the available number of field pairs (which should be the same as the
    // available number of frames) - This is just for debug really
    bool isFirstField = false;
    qint32 errorCounter = 0;
    qint32 firstFieldCounter = 0;
    qint32 secondFieldCounter = 0;
    for (qint32 fieldNumber = 1; fieldNumber <= getNumberOfFields(); fieldNumber++) {
        if (fieldNumber == 1) {
            isFirstField = getField(fieldNumber).isFirstField;
            qDebug() << "LdDecodeMetaData::read(): Initial field has isFirstField =" << isFirstField;
        } else {
            if (getField(fieldNumber).isFirstField == isFirstField) {
                qDebug() << "LdDecodeMetaData::read(): Field #" << fieldNumber << "has isFirstField out of sequence - TBC input file is broken";
                errorCounter++;
            } else {
                isFirstField = !isFirstField;
            }
        }

        if (getField(fieldNumber).isFirstField) firstFieldCounter++; else secondFieldCounter++;
    }
    qDebug() << "LdDecodeMetaData::read(): TBC file has" << firstFieldCounter << "first fields and" << secondFieldCounter << "second fields with" << errorCounter << "sequence errors";

    // Default to the standard still-frame field order (of first field first)
    isFirstFieldFirst = true;

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
            field.insert("audioSamples", metaData.fields[fieldNumber].audioSamples);

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

                QJsonArray vbiData;
                vbiData.append(metaData.fields[fieldNumber].vbi.vbiData[0]);
                vbiData.append(metaData.fields[fieldNumber].vbi.vbiData[1]);
                vbiData.append(metaData.fields[fieldNumber].vbi.vbiData[2]);
                vbi.insert("vbiData", vbiData);

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

                vbi.insert("userCode", metaData.fields[fieldNumber].vbi.userCode);
                vbi.insert("picNo", metaData.fields[fieldNumber].vbi.picNo);
                vbi.insert("chNo", metaData.fields[fieldNumber].vbi.chNo);
                vbi.insert("clvHr", metaData.fields[fieldNumber].vbi.clvHr);
                vbi.insert("clvMin", metaData.fields[fieldNumber].vbi.clvMin);
                vbi.insert("clvSec", metaData.fields[fieldNumber].vbi.clvSec);
                vbi.insert("clvPicNo", metaData.fields[fieldNumber].vbi.clvPicNo);

                switch (metaData.fields[fieldNumber].vbi.soundMode) {
                case LdDecodeMetaData::VbiSoundModes::stereo:
                    vbi.insert("soundMode", 0);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono:
                    vbi.insert("soundMode", 1);
                    break;
                case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
                    vbi.insert("soundMode", 2);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual:
                    vbi.insert("soundMode", 3);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
                    vbi.insert("soundMode", 4);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
                    vbi.insert("soundMode", 5);
                    break;
                case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
                    vbi.insert("soundMode", 6);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
                    vbi.insert("soundMode", 7);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono_dump:
                    vbi.insert("soundMode", 8);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_dump:
                    vbi.insert("soundMode", 9);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
                    vbi.insert("soundMode", 10);
                    break;
                case LdDecodeMetaData::VbiSoundModes::futureUse:
                    vbi.insert("soundMode", 11);
                    break;
                }

                switch (metaData.fields[fieldNumber].vbi.soundModeAm2) {
                case LdDecodeMetaData::VbiSoundModes::stereo:
                    vbi.insert("soundModeAm2", 0);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono:
                    vbi.insert("soundModeAm2", 1);
                    break;
                case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
                    vbi.insert("soundModeAm2", 2);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual:
                    vbi.insert("soundModeAm2", 3);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
                    vbi.insert("soundModeAm2", 4);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
                    vbi.insert("soundModeAm2", 5);
                    break;
                case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
                    vbi.insert("soundModeAm2", 6);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
                    vbi.insert("soundModeAm2", 7);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono_dump:
                    vbi.insert("soundModeAm2", 8);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_dump:
                    vbi.insert("soundModeAm2", 9);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
                    vbi.insert("soundModeAm2", 10);
                    break;
                case LdDecodeMetaData::VbiSoundModes::futureUse:
                    vbi.insert("soundModeAm2", 11);
                    break;
                }

                // Convert the vitual flag booleans to the flags integer
                qint32 flags = 0;
                if (metaData.fields[fieldNumber].vbi.leadIn)        flags += 0x0001;
                if (metaData.fields[fieldNumber].vbi.leadOut)       flags += 0x0002;
                if (metaData.fields[fieldNumber].vbi.picStop)       flags += 0x0004;
                if (metaData.fields[fieldNumber].vbi.cx)            flags += 0x0008;
                if (metaData.fields[fieldNumber].vbi.size)          flags += 0x0010;
                if (metaData.fields[fieldNumber].vbi.side)          flags += 0x0020;
                if (metaData.fields[fieldNumber].vbi.teletext)      flags += 0x0040;
                if (metaData.fields[fieldNumber].vbi.dump)          flags += 0x0080;
                if (metaData.fields[fieldNumber].vbi.fm)            flags += 0x0100;
                if (metaData.fields[fieldNumber].vbi.digital)       flags += 0x0200;
                if (metaData.fields[fieldNumber].vbi.parity)        flags += 0x0400;
                if (metaData.fields[fieldNumber].vbi.copyAm2)       flags += 0x0800;
                if (metaData.fields[fieldNumber].vbi.standardAm2)   flags += 0x1000;

                // Insert the flags into the VBI JSON
                vbi.insert("flags", flags);

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

    jsonFileHandle.write(document.toJson(QJsonDocument::Compact));
    jsonFileHandle.close();

    return true;
}

// This method returns the videoParameters metadata
LdDecodeMetaData::VideoParameters LdDecodeMetaData::getVideoParameters(void)
{
    return metaData.videoParameters;
}

// This method sets the videoParameters metadata
void LdDecodeMetaData::setVideoParameters (LdDecodeMetaData::VideoParameters videoParametersParam)
{
    metaData.videoParameters = videoParametersParam;
}

// This method returns the pcmAudioParameters metadata
LdDecodeMetaData::PcmAudioParameters LdDecodeMetaData::getPcmAudioParameters(void)
{
    return metaData.pcmAudioParameters;
}

// This method sets the pcmAudioParameters metadata
void LdDecodeMetaData::setPcmAudioParameters(LdDecodeMetaData::PcmAudioParameters pcmAudioParam)
{
    metaData.pcmAudioParameters = pcmAudioParam;
}

// This method gets the metadata for the specified sequential field number
LdDecodeMetaData::Field LdDecodeMetaData::getField(qint32 sequentialFieldNumber)
{
    if ((sequentialFieldNumber - 1) >= metaData.fields.size() || sequentialFieldNumber < 1) {
        qCritical() << "LdDecodeMetaData::getField(): Requested field number" << sequentialFieldNumber << "out of bounds!";

        // We have to construct a dummy result to prevent segfaults on return

        // Field
        LdDecodeMetaData::Field field;
        field.seqNo = -1;
        field.isFirstField = false;
        field.syncConf = -1;
        field.medianBurstIRE = -1;
        field.fieldPhaseID = -1;
        field.audioSamples = -1;

        // VITS
        field.vits.inUse = false;

        // VBI
        field.vbi.inUse = false;
        field.vbi.vbiData.append(-1);
        field.vbi.vbiData.append(-1);
        field.vbi.vbiData.append(-1);
        field.vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
        field.vbi.userCode = "";
        field.vbi.picNo = -1;
        field.vbi.chNo = -1;
        field.vbi.clvHr = -1;
        field.vbi.clvMin = -1;
        field.vbi.clvSec = -1;
        field.vbi.clvPicNo = -1;
        field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
        field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;

        // VBI Flags
        field.vbi.leadIn = false;
        field.vbi.leadOut = false;
        field.vbi.picStop = false;
        field.vbi.cx = false;
        field.vbi.size = false;
        field.vbi.side = false;
        field.vbi.teletext = false;
        field.vbi.dump = false;
        field.vbi.fm = false;
        field.vbi.digital = false;
        field.vbi.parity = false;
        field.vbi.copyAm2 = false;
        field.vbi.standardAm2 = false;

        // NTSC
        field.ntsc.inUse = false;
        field.ntsc.fieldFlag = false;
        field.ntsc.whiteFlag = false;
        field.ntsc.fmCodeData = -1;
        field.ntsc.isFmCodeDataValid = false;

        return field;
    }

    // Resize the VBI data fields to prevent assert issues downstream
    if (metaData.fields[sequentialFieldNumber - 1].vbi.vbiData.size() != 3)
        metaData.fields[sequentialFieldNumber - 1].vbi.vbiData.resize(3);

    return metaData.fields[sequentialFieldNumber - 1];
}

// This method appends a new field to the existing metadata
void LdDecodeMetaData::appendField(LdDecodeMetaData::Field fieldParam)
{
    metaData.videoParameters.numberOfSequentialFields++;
    metaData.fields.append(fieldParam);
}

// This method updates an existing field with new metadata
void LdDecodeMetaData::updateField(LdDecodeMetaData::Field fieldParam, qint32 sequentialFieldNumber)
{
    if ((sequentialFieldNumber - 1) >= metaData.fields.size() || sequentialFieldNumber < 1) {
        qCritical() << "LdDecodeMetaData::updateField(): Requested field number" << sequentialFieldNumber << "out of bounds!";
        return;
    }
    metaData.fields[sequentialFieldNumber - 1] = fieldParam;
}

// Method to get the available number of fields (according to the metadata)
qint32 LdDecodeMetaData::getNumberOfFields(void)
{
    return metaData.fields.size();
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
qint32 LdDecodeMetaData::getNumberOfFrames(void)
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
            qCritical() << "Attempting to get field number failed - no isFirstField in JSON before end of file";
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
bool LdDecodeMetaData::getIsFirstFieldFirst(void)
{
    return isFirstFieldFirst;
}

// Method to get the current disc type (CAV/CLV/Unknown) based on the VBI data
LdDecodeMetaData::VbiDiscTypes LdDecodeMetaData::getDiscTypeFromVbi(void)
{
    // Note: Due to factors like lead-in frames having invalid disc types, it's a good
    // idea to look at more than 1 field when determining the disc type

    // Check 20 fields (or the maximum available if less than 20)
    qint32 fieldsToCheck = 20;
    if (getNumberOfFields() < fieldsToCheck) fieldsToCheck = getNumberOfFields();

    qint32 cavCount = 0;
    qint32 clvCount = 0;
    for (qint32 fieldNumber = 1; fieldNumber <= fieldsToCheck; fieldNumber++) {
        // Ignore lead-in and lead-out fields
        if (!(metaData.fields[fieldNumber].vbi.leadIn || metaData.fields[fieldNumber].vbi.leadOut)) {
            if (metaData.fields[fieldNumber].vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) cavCount++;
            if (metaData.fields[fieldNumber].vbi.type == LdDecodeMetaData::VbiDiscTypes::clv) clvCount++;
        }
    }

    if (cavCount == 0 && clvCount == 0) {
        // There is no way to know the disc type
        return LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
    }

    if (cavCount == clvCount) {
        // There is no way to know the disc type
        return LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
    }

    if (cavCount > clvCount) return LdDecodeMetaData::VbiDiscTypes::cav;

    return LdDecodeMetaData::VbiDiscTypes::clv;
}





