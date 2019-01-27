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

#include "JsonWax/JsonWax.h"
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
    JsonWax json;
    if (!json.loadFile(fileName)) {
        qCritical("Opening JSON file failed: JSON file cannot be opened/does not exist");
        return false;
    }

    // Read the video paramters
    if (json.size({"videoParameters"}) > 0) {
        // Read the video parameters
        metaData.videoParameters.numberOfSequentialFields = json.value({"videoParameters", "numberOfSequentialFields"}).toInt();
        metaData.videoParameters.isSourcePal = json.value({"videoParameters", "isSourcePal"}).toBool();

        metaData.videoParameters.colourBurstStart = json.value({"videoParameters", "colourBurstStart"}).toInt();
        metaData.videoParameters.colourBurstEnd = json.value({"videoParameters", "colourBurstEnd"}).toInt();
        metaData.videoParameters.activeVideoStart = json.value({"videoParameters", "activeVideoStart"}).toInt();
        metaData.videoParameters.activeVideoEnd = json.value({"videoParameters", "activeVideoEnd"}).toInt();

        metaData.videoParameters.white16bIre = json.value({"videoParameters", "white16bIre"}).toInt();
        metaData.videoParameters.black16bIre = json.value({"videoParameters", "black16bIre"}).toInt();

        metaData.videoParameters.fieldWidth = json.value({"videoParameters", "fieldWidth"}).toInt();
        metaData.videoParameters.fieldHeight = json.value({"videoParameters", "fieldHeight"}).toInt();
        metaData.videoParameters.sampleRate = json.value({"videoParameters", "sampleRate"}).toInt();
        metaData.videoParameters.fsc = json.value({"videoParameters", "fsc"}).toInt();
        qDebug() << "LdDecodeMetaData::read(): videoParameters is defined";
    } else {
        qCritical("Opening JSON file failed: videoParameters object is not defined");
        return false;
    }

    if (json.size({"pcmAudioParameters"}) > 0) {
        // Read the PCM audio data
        metaData.pcmAudioParameters.sampleRate = json.value({"pcmAudioParameters", "sampleRate"}).toInt();
        metaData.pcmAudioParameters.isLittleEndian = json.value({"pcmAudioParameters", "isLittleEndian"}).toBool();
        metaData.pcmAudioParameters.isSigned = json.value({"pcmAudioParameters", "isSigned"}).toBool();
        metaData.pcmAudioParameters.bits = json.value({"pcmAudioParameters", "bits"}).toInt();
        qDebug() << "LdDecodeMetaData::read(): pcmAudioParameters is defined";
    } else {
        qCritical("Opening JSON file failed: pcmAudioParameters is not defined");
        return false;
    }

    qint32 numberOfFields = json.size({"fields"});
    qDebug() << "LdDecodeMetaData::read(): Found" << numberOfFields << "fields in the JSON document";
    metaData.fields.resize(numberOfFields);
    if (numberOfFields > 0) {
        // Read the fields
        for (qint32 fieldNumber = 0; fieldNumber < numberOfFields; fieldNumber++) {
            // Primary field values
            metaData.fields[fieldNumber].seqNo = json.value({"fields", fieldNumber, "seqNo"}).toInt();
            metaData.fields[fieldNumber].isFirstField = json.value({"fields", fieldNumber, "isFirstField"}).toBool();
            metaData.fields[fieldNumber].syncConf = json.value({"fields", fieldNumber, "syncConf"}).toInt();
            metaData.fields[fieldNumber].medianBurstIRE = json.value({"fields", fieldNumber, "medianBurstIRE"}).toDouble();
            metaData.fields[fieldNumber].fieldPhaseID = json.value({"fields", fieldNumber, "fieldPhaseID"}).toInt();
            metaData.fields[fieldNumber].audioSamples = json.value({"fields", fieldNumber, "audioSamples"}).toInt();

            // VITS values
            if (json.size({"fields", fieldNumber, "vits"}) > 0) {
                metaData.fields[fieldNumber].vits.inUse = true;
                metaData.fields[fieldNumber].vits.snr = json.value({"fields", fieldNumber, "vits", "snr"}).toDouble();
            } else {
                // Mark VITS as undefined
                metaData.fields[fieldNumber].vits.inUse = false;
            }

            // VBI values
            if (json.size({"fields", fieldNumber, "vbi"}) > 0) {
                // Mark VBI as in use
                metaData.fields[fieldNumber].vbi.inUse = true;

                metaData.fields[fieldNumber].vbi.vbiData.append(json.value({"fields", fieldNumber, "vbi", "vbiData", 0}).toInt()); // Line 16
                metaData.fields[fieldNumber].vbi.vbiData.append(json.value({"fields", fieldNumber, "vbi", "vbiData", 1}).toInt()); // Line 17
                metaData.fields[fieldNumber].vbi.vbiData.append(json.value({"fields", fieldNumber, "vbi", "vbiData", 2}).toInt()); // Line 18

                switch(json.value({"fields", fieldNumber, "vbi", "type"}).toInt()) {
                case 0:
                    metaData.fields[fieldNumber].vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
                    break;
                case 1 :
                    metaData.fields[fieldNumber].vbi.type = LdDecodeMetaData::VbiDiscTypes::clv;
                    break;
                case 2 :
                    metaData.fields[fieldNumber].vbi.type = LdDecodeMetaData::VbiDiscTypes::cav;
                    break;
                default:
                    metaData.fields[fieldNumber].vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
                }

                metaData.fields[fieldNumber].vbi.userCode = json.value({"fields", fieldNumber, "vbi", "userCode"}).toString();
                metaData.fields[fieldNumber].vbi.picNo = json.value({"fields", fieldNumber, "vbi", "picNo"}).toInt();
                metaData.fields[fieldNumber].vbi.chNo = json.value({"fields", fieldNumber, "vbi", "chNo"}).toInt();
                metaData.fields[fieldNumber].vbi.clvHr = json.value({"fields", fieldNumber, "vbi", "clvHr"}).toInt();
                metaData.fields[fieldNumber].vbi.clvMin = json.value({"fields", fieldNumber, "vbi", "clvMin"}).toInt();
                metaData.fields[fieldNumber].vbi.clvSec = json.value({"fields", fieldNumber, "vbi", "clvSec"}).toInt();
                metaData.fields[fieldNumber].vbi.clvPicNo = json.value({"fields", fieldNumber, "vbi", "clvPicNo"}).toInt();

                switch (json.value({"fields", fieldNumber, "vbi", "soundMode"}).toInt()) {
                case 0:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
                    break;
                case 1:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
                    break;
                case 2:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
                    break;
                case 3:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
                    break;
                case 4:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
                    break;
                case 5:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
                    break;
                case 6:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
                    break;
                case 7:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
                    break;
                case 8:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
                    break;
                case 9:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
                    break;
                case 10:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
                    break;
                case 11:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                default:
                    metaData.fields[fieldNumber].vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                }

                switch (json.value({"fields", fieldNumber, "vbi", "soundModeAm2"}).toInt()) {
                case 0:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo;
                    break;
                case 1:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono;
                    break;
                case 2:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
                    break;
                case 3:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual;
                    break;
                case 4:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
                    break;
                case 5:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
                    break;
                case 6:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
                    break;
                case 7:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
                    break;
                case 8:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono_dump;
                    break;
                case 9:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_dump;
                    break;
                case 10:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
                    break;
                case 11:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                default:
                    metaData.fields[fieldNumber].vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
                    break;
                }

                // Get the boolean flags field (contains 13 boolean flags from the VBI)
                qint32 booleanFlags = json.value({"fields", fieldNumber, "vbi", "flags"}).toInt();

                // Interpret the flags
                metaData.fields[fieldNumber].vbi.leadIn =      ((booleanFlags & 0x0001) == 0x0001);
                metaData.fields[fieldNumber].vbi.leadOut =     ((booleanFlags & 0x0002) == 0x0002);
                metaData.fields[fieldNumber].vbi.picStop =     ((booleanFlags & 0x0004) == 0x0004);
                metaData.fields[fieldNumber].vbi.cx =          ((booleanFlags & 0x0008) == 0x0008);
                metaData.fields[fieldNumber].vbi.size =        ((booleanFlags & 0x0010) == 0x0010);
                metaData.fields[fieldNumber].vbi.side =        ((booleanFlags & 0x0020) == 0x0020);
                metaData.fields[fieldNumber].vbi.teletext =    ((booleanFlags & 0x0040) == 0x0040);
                metaData.fields[fieldNumber].vbi.dump =        ((booleanFlags & 0x0080) == 0x0080);
                metaData.fields[fieldNumber].vbi.fm =          ((booleanFlags & 0x0100) == 0x0100);
                metaData.fields[fieldNumber].vbi.digital =     ((booleanFlags & 0x0200) == 0x0200);
                metaData.fields[fieldNumber].vbi.parity =      ((booleanFlags & 0x0400) == 0x0400);
                metaData.fields[fieldNumber].vbi.copyAm2 =     ((booleanFlags & 0x0800) == 0x0800);
                metaData.fields[fieldNumber].vbi.standardAm2 = ((booleanFlags & 0x1000) == 0x1000);
            } else {
                // Mark VBI as undefined
                metaData.fields[fieldNumber].vbi.inUse = false;
            }

            // NTSC values
            if (json.size({"fields", fieldNumber, "ntsc"}) > 0) {
                // Mark as in use
                metaData.fields[fieldNumber].ntsc.inUse = true;

                metaData.fields[fieldNumber].ntsc.isFmCodeDataValid = json.value({"fields", fieldNumber, "ntsc", "isFmCodeDataValid"}).toBool();
                metaData.fields[fieldNumber].ntsc.fmCodeData = json.value({"fields", fieldNumber, "ntsc", "fmCodeData"}).toInt();
                metaData.fields[fieldNumber].ntsc.fieldFlag = json.value({"fields", fieldNumber, "ntsc", "fieldFlag"}).toBool();
                metaData.fields[fieldNumber].ntsc.whiteFlag = json.value({"fields", fieldNumber, "ntsc", "whiteFlag"}).toBool();
            } else {
                // Mark ntscSpecific as undefined
                metaData.fields[fieldNumber].ntsc.inUse = false;
            }

            // dropOuts values
            qint32 startxSize = json.size({"fields", fieldNumber, "dropOuts", "startx"});
            qint32 endxSize = json.size({"fields", fieldNumber, "dropOuts", "endx"});
            qint32 fieldLinesSize = json.size({"fields", fieldNumber, "dropOuts", "fieldLines"});

            // Ensure that all three objects are the same size
            if (startxSize != endxSize && startxSize != fieldLinesSize) {
                qCritical("Opening JSON file failed: Dropouts object is illegal");
                return false;
            }

            if (startxSize > 0) {
                metaData.fields[fieldNumber].dropOuts.startx.resize(startxSize);
                metaData.fields[fieldNumber].dropOuts.endx.resize(startxSize);
                metaData.fields[fieldNumber].dropOuts.fieldLine.resize(startxSize);

                for (qint32 doCounter = 0; doCounter < startxSize; doCounter++) {
                    metaData.fields[fieldNumber].dropOuts.startx[doCounter] = json.value({"fields", fieldNumber, "dropOuts", "startx", doCounter}).toInt();
                    metaData.fields[fieldNumber].dropOuts.endx[doCounter] = json.value({"fields", fieldNumber, "dropOuts", "endx", doCounter}).toInt();
                    metaData.fields[fieldNumber].dropOuts.fieldLine[doCounter] = json.value({"fields", fieldNumber, "dropOuts", "fieldLine", doCounter}).toInt();
                }
            }
        }
    }  else {
        qCritical("Opening JSON file failed: No fields objects are defined");
        return false;
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
    // Define the JSON object
    JsonWax json;

    // Write the video paramters
    json.setValue({"videoParameters", "numberOfSequentialFields"}, metaData.videoParameters.numberOfSequentialFields);

    json.setValue({"videoParameters", "numberOfSequentialFields"}, metaData.videoParameters.numberOfSequentialFields);
    json.setValue({"videoParameters", "isSourcePal"}, metaData.videoParameters.isSourcePal);

    json.setValue({"videoParameters", "colourBurstStart"}, metaData.videoParameters.colourBurstStart);
    json.setValue({"videoParameters", "colourBurstEnd"}, metaData.videoParameters.colourBurstEnd);
    json.setValue({"videoParameters", "activeVideoStart"}, metaData.videoParameters.activeVideoStart);
    json.setValue({"videoParameters", "activeVideoEnd"}, metaData.videoParameters.activeVideoEnd);

    json.setValue({"videoParameters", "white16bIre"}, metaData.videoParameters.white16bIre);
    json.setValue({"videoParameters", "black16bIre"}, metaData.videoParameters.black16bIre);

    json.setValue({"videoParameters", "fieldWidth"}, metaData.videoParameters.fieldWidth);
    json.setValue({"videoParameters", "fieldHeight"}, metaData.videoParameters.fieldHeight);
    json.setValue({"videoParameters", "sampleRate"}, metaData.videoParameters.sampleRate);
    json.setValue({"videoParameters", "fsc"}, metaData.videoParameters.fsc);

    // Write the PCM audio parameters
    json.setValue({"pcmAudioParameters", "sampleRate"}, metaData.pcmAudioParameters.sampleRate);
    json.setValue({"pcmAudioParameters", "isLittleEndian"}, metaData.pcmAudioParameters.isLittleEndian);
    json.setValue({"pcmAudioParameters", "isSigned"}, metaData.pcmAudioParameters.isSigned);
    json.setValue({"pcmAudioParameters", "bits"}, metaData.pcmAudioParameters.bits);

    // Write the field data
    if (!metaData.fields.isEmpty()) {
        qDebug() << "LdDecodeMetaData::write(): metadata struct contains" << metaData.fields.size() << "fields";

        for (qint32 fieldNumber = 0; fieldNumber < metaData.fields.size(); fieldNumber++) {
            json.setValue({"fields", fieldNumber, "seqNo"}, metaData.fields[fieldNumber].seqNo);
            json.setValue({"fields", fieldNumber, "isFirstField"}, metaData.fields[fieldNumber].isFirstField);
            json.setValue({"fields", fieldNumber, "syncConf"}, metaData.fields[fieldNumber].syncConf);
            json.setValue({"fields", fieldNumber, "medianBurstIRE"}, metaData.fields[fieldNumber].medianBurstIRE);
            json.setValue({"fields", fieldNumber, "fieldPhaseID"}, metaData.fields[fieldNumber].fieldPhaseID);
            json.setValue({"fields", fieldNumber, "audioSamples"}, metaData.fields[fieldNumber].audioSamples);

            // Write the VITS data if in use
            if (metaData.fields[fieldNumber].vits.inUse) {
                json.setValue({"fields", fieldNumber, "vits", "snr"}, metaData.fields[fieldNumber].vits.snr);
            }

            // Write the VBI data if in use
            if (metaData.fields[fieldNumber].vbi.inUse) {
                // Validate the VBI data array
                if (metaData.fields[fieldNumber].vbi.vbiData.size() != 3) {
                    qDebug() << "LdDecodeMetaData::write(): Invalid vbiData array!  Setting to -1";
                    metaData.fields[fieldNumber].vbi.vbiData.resize(3);
                    metaData.fields[fieldNumber].vbi.vbiData[0] = -1;
                    metaData.fields[fieldNumber].vbi.vbiData[1] = -1;
                    metaData.fields[fieldNumber].vbi.vbiData[2] = -1;
                }

                json.setValue({"fields", fieldNumber, "vbi", "vbiData", 0}, metaData.fields[fieldNumber].vbi.vbiData[0]);
                json.setValue({"fields", fieldNumber, "vbi", "vbiData", 1}, metaData.fields[fieldNumber].vbi.vbiData[1]);
                json.setValue({"fields", fieldNumber, "vbi", "vbiData", 2}, metaData.fields[fieldNumber].vbi.vbiData[2]);

                switch(metaData.fields[fieldNumber].vbi.type) {
                case LdDecodeMetaData::VbiDiscTypes::unknownDiscType:
                    json.setValue({"fields", fieldNumber, "vbi", "type"}, 0);
                    break;
                case LdDecodeMetaData::VbiDiscTypes::clv:
                    json.setValue({"fields", fieldNumber, "vbi", "type"}, 1);
                    break;
                case LdDecodeMetaData::VbiDiscTypes::cav:
                    json.setValue({"fields", fieldNumber, "vbi", "type"}, 2);
                    break;
                }

                json.setValue({"fields", fieldNumber, "vbi", "userCode"}, metaData.fields[fieldNumber].vbi.userCode);
                json.setValue({"fields", fieldNumber, "vbi", "picNo"}, metaData.fields[fieldNumber].vbi.picNo);
                json.setValue({"fields", fieldNumber, "vbi", "chNo"}, metaData.fields[fieldNumber].vbi.chNo);
                json.setValue({"fields", fieldNumber, "vbi", "clvHr"}, metaData.fields[fieldNumber].vbi.clvHr);
                json.setValue({"fields", fieldNumber, "vbi", "clvMin"}, metaData.fields[fieldNumber].vbi.clvMin);
                json.setValue({"fields", fieldNumber, "vbi", "clvSec"}, metaData.fields[fieldNumber].vbi.clvSec);
                json.setValue({"fields", fieldNumber, "vbi", "clvPicNo"}, metaData.fields[fieldNumber].vbi.clvPicNo);

                switch (metaData.fields[fieldNumber].vbi.soundMode) {
                case LdDecodeMetaData::VbiSoundModes::stereo:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 0);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 1);
                    break;
                case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 2);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 3);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 4);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 5);
                    break;
                case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 6);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 7);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono_dump:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 8);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_dump:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 9);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 10);
                    break;
                case LdDecodeMetaData::VbiSoundModes::futureUse:
                    json.setValue({"fields", fieldNumber, "vbi", "soundMode"}, 11);
                    break;
                }

                switch (metaData.fields[fieldNumber].vbi.soundModeAm2) {
                case LdDecodeMetaData::VbiSoundModes::stereo:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 0);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 1);
                    break;
                case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 2);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 3);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 4);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 5);
                    break;
                case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 6);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 7);
                    break;
                case LdDecodeMetaData::VbiSoundModes::mono_dump:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 8);
                    break;
                case LdDecodeMetaData::VbiSoundModes::stereo_dump:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 9);
                    break;
                case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 10);
                    break;
                case LdDecodeMetaData::VbiSoundModes::futureUse:
                    json.setValue({"fields", fieldNumber, "vbi", "soundModeAm2"}, 11);
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
                json.setValue({"fields", fieldNumber, "vbi", "flags"}, flags);
            }

            // Write the NTSC specific record if in use
            if (metaData.fields[fieldNumber].ntsc.inUse) {
                json.setValue({"fields", fieldNumber, "ntsc", "isFmCodeDataValid"}, metaData.fields[fieldNumber].ntsc.isFmCodeDataValid);
                if (metaData.fields[fieldNumber].ntsc.isFmCodeDataValid)
                    json.setValue({"fields", fieldNumber, "ntsc", "fmCodeData"}, metaData.fields[fieldNumber].ntsc.fmCodeData);
                else json.setValue({"fields", fieldNumber, "ntsc", "fmCodeData"}, -1);
                json.setValue({"fields", fieldNumber, "ntsc", "fieldFlag"}, metaData.fields[fieldNumber].ntsc.fieldFlag);
                json.setValue({"fields", fieldNumber, "ntsc", "whiteFlag"}, metaData.fields[fieldNumber].ntsc.whiteFlag);
            }

            // Write the drop-out records
            if (metaData.fields[fieldNumber].dropOuts.startx.size() != 0) {
                // Populate the arrays with the drop out metadata
                for (qint32 doCounter = 0; doCounter < metaData.fields[fieldNumber].dropOuts.startx.size(); doCounter++) {
                    json.setValue({"fields", fieldNumber, "dropOuts", "startx", doCounter}, metaData.fields[fieldNumber].dropOuts.startx[doCounter]);
                    json.setValue({"fields", fieldNumber, "dropOuts", "endx", doCounter}, metaData.fields[fieldNumber].dropOuts.endx[doCounter]);
                    json.setValue({"fields", fieldNumber, "dropOuts", "fieldLine", doCounter}, metaData.fields[fieldNumber].dropOuts.fieldLine[doCounter]);
                }
            }
        }
    }

    // Write the JSON object to file
    qDebug() << "LdDecodeMetaData::write(): Writing JSON metadata file";
    if (!json.saveAs(fileName, JsonWax::Readable)) {
        qCritical("Writing JSON file failed!");
        return false;
    }

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

// Method to convert a CLV time code into an equivalent frame number (to make
// processing the timecodes easier)
qint32 LdDecodeMetaData::convertClvTimecodeToFrameNumber(LdDecodeMetaData::ClvTimecode clvTimeCode)
{
    // Calculate the frame number
    qint32 frameNumber = -1;

    if (clvTimeCode.hours != -1) {
        if (metaData.videoParameters.isSourcePal) frameNumber += clvTimeCode.hours * 3600 * 25;
        else frameNumber += clvTimeCode.hours * 3600 * 30;
    }

    if (clvTimeCode.minutes != -1) {
        if (metaData.videoParameters.isSourcePal) frameNumber += clvTimeCode.minutes * 60 * 25;
        else frameNumber += clvTimeCode.minutes * 60 * 30;
    }

    if (clvTimeCode.seconds != -1) {
        if (metaData.videoParameters.isSourcePal) frameNumber += clvTimeCode.seconds * 25;
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

    if (metaData.videoParameters.isSourcePal) {
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

