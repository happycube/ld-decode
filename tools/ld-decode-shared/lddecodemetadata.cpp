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
    if (!json.loadFile(fileName)) {
        qCritical() << "JSON wax library error:" << json.errorMsg();
        qCritical("Opening JSON file failed: JSON file cannot be opened/does not exist");

        return false;
    }

    // Default to the standard still-frame field order (of first field first)
    isFirstFieldFirst = true;

    return true;
}

// This method copies the metadata structure into a JSON metadata file
bool LdDecodeMetaData::write(QString fileName)
{
    // Write the JSON object
    qDebug() << "LdDecodeMetaData::write(): Writing JSON metadata to:" << fileName;
    if (!json.saveAs(fileName, JsonWax::Compact)) {
        qCritical("Writing JSON metadata file failed!");
        return false;
    }

    return true;
}

// This method copies the VITS metadata structure into a CSV metadata file
bool LdDecodeMetaData::writeVitsCsv(QString fileName)
{
    qWarning() << "Write VITS and CSV file function is not implemented - nothing will be saved!";
    // Open a file for the CSV output
    QFile csvFile(fileName);
    if (!csvFile.open(QFile::WriteOnly | QFile::Text)){
        qDebug("LdDecodeMetaData::writeVitsCsv(): Could not open CSV file for output!");
        return false;
    }

    // Create a text stream for the CSV output
    QTextStream outStream(&csvFile);
    outStream.setCodec("UTF-8");

    // Write the field and VITS data
    outStream << "seqNo,isFirstField,syncConf,";
    outStream << "medianBurstIRE,fieldPhaseID,audioSamples,";

    // VITS headers
    outStream << "wSNR,bPSNR";
    outStream << '\n';

    for (qint32 fieldNumber = 1; fieldNumber <= getNumberOfFields(); fieldNumber++) {
        Field field = getField(fieldNumber);
        outStream << escapedString(QString::number(field.seqNo)) << ",";
        outStream << escapedString(QString::number(field.isFirstField)) << ",";
        outStream << escapedString(QString::number(field.syncConf)) << ",";
        outStream << escapedString(QString::number(field.medianBurstIRE)) << ",";
        outStream << escapedString(QString::number(field.fieldPhaseID)) << ",";
        outStream << escapedString(QString::number(field.audioSamples)) << ",";

        outStream << escapedString(QString::number(field.vitsMetrics.wSNR)) << ",";
        outStream << escapedString(QString::number(field.vitsMetrics.bPSNR)) << ",";

        outStream << '\n';
    }

    // Close the CSV file
    csvFile.close();

    return true;
}

// This method creates an 'escaped string' for safe CSV output of QStrings
QString LdDecodeMetaData::escapedString(QString unescapedString)
{
    if (!unescapedString.contains(QLatin1Char(',')))
        return unescapedString;
    return '\"' + unescapedString.replace(QLatin1Char('\"'), QStringLiteral("\"\"")) + '\"';
}

// This method returns the videoParameters metadata
LdDecodeMetaData::VideoParameters LdDecodeMetaData::getVideoParameters()
{
    VideoParameters videoParameters;

    // Read the video paramters
    if (json.size({"videoParameters"}) > 0) {
        videoParameters.numberOfSequentialFields = json.value({"videoParameters", "numberOfSequentialFields"}).toInt();
        videoParameters.isSourcePal = json.value({"videoParameters", "isSourcePal"}).toBool();

        videoParameters.colourBurstStart = json.value({"videoParameters", "colourBurstStart"}).toInt();
        videoParameters.colourBurstEnd = json.value({"videoParameters", "colourBurstEnd"}).toInt();
        videoParameters.activeVideoStart = json.value({"videoParameters", "activeVideoStart"}).toInt();
        videoParameters.activeVideoEnd = json.value({"videoParameters", "activeVideoEnd"}).toInt();

        videoParameters.white16bIre = json.value({"videoParameters", "white16bIre"}).toInt();
        videoParameters.black16bIre = json.value({"videoParameters", "black16bIre"}).toInt();

        videoParameters.fieldWidth = json.value({"videoParameters", "fieldWidth"}).toInt();
        videoParameters.fieldHeight = json.value({"videoParameters", "fieldHeight"}).toInt();
        videoParameters.sampleRate = json.value({"videoParameters", "sampleRate"}).toInt();
        videoParameters.fsc = json.value({"videoParameters", "fsc"}).toInt();
    } else {
        qCritical("JSON file invalid: videoParameters object is not defined");
        return videoParameters;
    }

    return videoParameters;
}

// This method sets the videoParameters metadata
void LdDecodeMetaData::setVideoParameters (LdDecodeMetaData::VideoParameters _videoParameters)
{
    // Write the video parameters
    json.setValue({"videoParameters", "numberOfSequentialFields"}, _videoParameters.numberOfSequentialFields);
    json.setValue({"videoParameters", "isSourcePal"}, _videoParameters.isSourcePal);

    json.setValue({"videoParameters", "colourBurstStart"}, _videoParameters.colourBurstStart);
    json.setValue({"videoParameters", "colourBurstEnd"}, _videoParameters.colourBurstEnd);
    json.setValue({"videoParameters", "activeVideoStart"}, _videoParameters.activeVideoStart);
    json.setValue({"videoParameters", "activeVideoEnd"}, _videoParameters.activeVideoEnd);

    json.setValue({"videoParameters", "white16bIre"}, _videoParameters.white16bIre);
    json.setValue({"videoParameters", "black16bIre"}, _videoParameters.black16bIre);

    json.setValue({"videoParameters", "fieldWidth"}, _videoParameters.fieldWidth);
    json.setValue({"videoParameters", "fieldHeight"}, _videoParameters.fieldHeight);
    json.setValue({"videoParameters", "sampleRate"}, _videoParameters.sampleRate);
    json.setValue({"videoParameters", "fsc"}, _videoParameters.fsc);
}

// This method returns the pcmAudioParameters metadata
LdDecodeMetaData::PcmAudioParameters LdDecodeMetaData::getPcmAudioParameters()
{
    PcmAudioParameters pcmAudioParameters;

    if (json.size({"pcmAudioParameters"}) > 0) {
        // Read the PCM audio data
        pcmAudioParameters.sampleRate = json.value({"pcmAudioParameters", "sampleRate"}).toInt();
        pcmAudioParameters.isLittleEndian = json.value({"pcmAudioParameters", "isLittleEndian"}).toBool();
        pcmAudioParameters.isSigned = json.value({"pcmAudioParameters", "isSigned"}).toBool();
        pcmAudioParameters.bits = json.value({"pcmAudioParameters", "bits"}).toInt();
    } else {
        qCritical("JSON file invalid: pcmAudioParameters is not defined");
        return pcmAudioParameters;
    }

    return pcmAudioParameters;
}

// This method sets the pcmAudioParameters metadata
void LdDecodeMetaData::setPcmAudioParameters(LdDecodeMetaData::PcmAudioParameters _pcmAudioParam)
{
    json.setValue({"pcmAudioParameters", "sampleRate"}, _pcmAudioParam.sampleRate);
    json.setValue({"pcmAudioParameters", "isLittleEndian"}, _pcmAudioParam.isLittleEndian);
    json.setValue({"pcmAudioParameters", "isSigned"}, _pcmAudioParam.isSigned);
    json.setValue({"pcmAudioParameters", "bits"}, _pcmAudioParam.bits);
}

// This method gets the metadata for the specified sequential field number (indexed from 1 (not 0!))
LdDecodeMetaData::Field LdDecodeMetaData::getField(qint32 sequentialFieldNumber)
{
    Field field;
    qint32 fieldNumber = sequentialFieldNumber - 1;

    if (fieldNumber >= getNumberOfFields() || fieldNumber < 0) {
        qCritical() << "LdDecodeMetaData::getField(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    // Primary field values
    field.seqNo = json.value({"fields", fieldNumber, "seqNo"}).toInt();
    field.isFirstField = json.value({"fields", fieldNumber, "isFirstField"}).toBool();
    field.syncConf = json.value({"fields", fieldNumber, "syncConf"}).toInt();
    field.medianBurstIRE = json.value({"fields", fieldNumber, "medianBurstIRE"}).toDouble();
    field.fieldPhaseID = json.value({"fields", fieldNumber, "fieldPhaseID"}).toInt();
    field.audioSamples = json.value({"fields", fieldNumber, "audioSamples"}).toInt();

    // VITS metrics values
    if (json.size({"fields", fieldNumber, "vitsMetrics"}) > 0) {
        field.vitsMetrics.inUse = true;
        field.vitsMetrics.wSNR = json.value({"fields", fieldNumber, "vitsMetrics", "wSNR"}).toReal();
        field.vitsMetrics.bPSNR = json.value({"fields", fieldNumber, "vitsMetrics", "bPSNR"}).toReal();
    } else {
        // Mark VITS metrics as undefined
        field.vitsMetrics.inUse = false;
    }

    // VBI values
    if (json.size({"fields", fieldNumber, "vbi"}) > 0) {
        // Mark VBI as in use
        field.vbi.inUse = true;

        field.vbi.vbiData.append(json.value({"fields", fieldNumber, "vbi", "vbiData", 0}).toInt()); // Line 16
        field.vbi.vbiData.append(json.value({"fields", fieldNumber, "vbi", "vbiData", 1}).toInt()); // Line 17
        field.vbi.vbiData.append(json.value({"fields", fieldNumber, "vbi", "vbiData", 2}).toInt()); // Line 18

        switch(json.value({"fields", fieldNumber, "vbi", "vp", 0}).toInt()) {
        case 0:
            field.vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
            break;
        case 1 :
            field.vbi.type = LdDecodeMetaData::VbiDiscTypes::clv;
            break;
        case 2 :
            field.vbi.type = LdDecodeMetaData::VbiDiscTypes::cav;
            break;
        default:
            field.vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
        }

        field.vbi.userCode = json.value({"fields", fieldNumber, "vbi", "vp", 1}).toString();
        field.vbi.picNo = json.value({"fields", fieldNumber, "vbi", "vp", 2}).toInt();
        field.vbi.chNo = json.value({"fields", fieldNumber, "vbi", "vp", 3}).toInt();
        field.vbi.clvHr = json.value({"fields", fieldNumber, "vbi", "vp", 4}).toInt();
        field.vbi.clvMin = json.value({"fields", fieldNumber, "vbi", "vp", 5}).toInt();
        field.vbi.clvSec = json.value({"fields", fieldNumber, "vbi", "vp", 6}).toInt();
        field.vbi.clvPicNo = json.value({"fields", fieldNumber, "vbi", "vp", 7}).toInt();

        switch (json.value({"fields", fieldNumber, "vbi", "vp", 8}).toInt()) {
        case 0:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
            break;
        case 1:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
            break;
        case 2:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
            break;
        case 3:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
            break;
        case 4:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
            break;
        case 5:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
            break;
        case 6:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
            break;
        case 7:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
            break;
        case 8:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            break;
        case 9:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
            break;
        case 10:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
            break;
        case 11:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            break;
        default:
            field.vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            break;
        }

        switch (json.value({"fields", fieldNumber, "vbi", "vp", 9}).toInt()) {
        case 0:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo;
            break;
        case 1:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono;
            break;
        case 2:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff;
            break;
        case 3:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual;
            break;
        case 4:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
            break;
        case 5:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
            break;
        case 6:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
            break;
        case 7:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
            break;
        case 8:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono_dump;
            break;
        case 9:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo_dump;
            break;
        case 10:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
            break;
        case 11:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            break;
        default:
            field.vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            break;
        }

        // Get the boolean flags field (contains 13 boolean flags from the VBI)
        qint32 booleanFlags = json.value({"fields", fieldNumber, "vbi", "vp", 10}).toInt();

        // Interpret the flags
        field.vbi.leadIn =      ((booleanFlags & 0x0001) == 0x0001);
        field.vbi.leadOut =     ((booleanFlags & 0x0002) == 0x0002);
        field.vbi.picStop =     ((booleanFlags & 0x0004) == 0x0004);
        field.vbi.cx =          ((booleanFlags & 0x0008) == 0x0008);
        field.vbi.size =        ((booleanFlags & 0x0010) == 0x0010);
        field.vbi.side =        ((booleanFlags & 0x0020) == 0x0020);
        field.vbi.teletext =    ((booleanFlags & 0x0040) == 0x0040);
        field.vbi.dump =        ((booleanFlags & 0x0080) == 0x0080);
        field.vbi.fm =          ((booleanFlags & 0x0100) == 0x0100);
        field.vbi.digital =     ((booleanFlags & 0x0200) == 0x0200);
        field.vbi.parity =      ((booleanFlags & 0x0400) == 0x0400);
        field.vbi.copyAm2 =     ((booleanFlags & 0x0800) == 0x0800);
        field.vbi.standardAm2 = ((booleanFlags & 0x1000) == 0x1000);
    } else {
        // Mark VBI as undefined
        field.vbi.inUse = false;
    }

    // NTSC values
    if (json.size({"fields", fieldNumber, "ntsc"}) > 0) {
        // Mark as in use
        field.ntsc.inUse = true;

        field.ntsc.isFmCodeDataValid = json.value({"fields", fieldNumber, "ntsc", "isFmCodeDataValid"}).toBool();
        field.ntsc.fmCodeData = json.value({"fields", fieldNumber, "ntsc", "fmCodeData"}).toInt();
        field.ntsc.fieldFlag = json.value({"fields", fieldNumber, "ntsc", "fieldFlag"}).toBool();
        field.ntsc.whiteFlag = json.value({"fields", fieldNumber, "ntsc", "whiteFlag"}).toBool();
    } else {
        // Mark ntscSpecific as undefined
        field.ntsc.inUse = false;
    }

    // dropOuts values
    qint32 startxSize = json.size({"fields", fieldNumber, "dropOuts", "startx"});
    qint32 endxSize = json.size({"fields", fieldNumber, "dropOuts", "endx"});
    qint32 fieldLinesSize = json.size({"fields", fieldNumber, "dropOuts", "fieldLines"});

    // Ensure that all three objects are the same size
    if (startxSize != endxSize && startxSize != fieldLinesSize) {
        qCritical("JSON file is invalid: Dropouts object is illegal");
    }

    if (startxSize > 0) {
        field.dropOuts.startx.resize(startxSize);
        field.dropOuts.endx.resize(startxSize);
        field.dropOuts.fieldLine.resize(startxSize);

        for (qint32 doCounter = 0; doCounter < startxSize; doCounter++) {
            field.dropOuts.startx[doCounter] = json.value({"fields", fieldNumber, "dropOuts", "startx", doCounter}).toInt();
            field.dropOuts.endx[doCounter] = json.value({"fields", fieldNumber, "dropOuts", "endx", doCounter}).toInt();
            field.dropOuts.fieldLine[doCounter] = json.value({"fields", fieldNumber, "dropOuts", "fieldLine", doCounter}).toInt();
        }
    } else {
        field.dropOuts.startx.clear();
        field.dropOuts.endx.clear();
        field.dropOuts.fieldLine.clear();
    }

    // Resize the VBI data fields to prevent assert issues downstream
    if (field.vbi.vbiData.size() != 3) field.vbi.vbiData.resize(3);

    return field;
}

// This method sets the field metadata for a field
void LdDecodeMetaData::updateField(LdDecodeMetaData::Field _field, qint32 sequentialFieldNumber)
{
    qint32 fieldNumber = sequentialFieldNumber - 1;

    if (fieldNumber >= getNumberOfFields() + 1 || fieldNumber < 0) {
        qCritical() << "LdDecodeMetaData::updateField(): Requested field number" << sequentialFieldNumber << "out of bounds!";
    }

    // Write the field data
    json.setValue({"fields", fieldNumber, "seqNo"}, _field.seqNo);
    json.setValue({"fields", fieldNumber, "isFirstField"}, _field.isFirstField);
    json.setValue({"fields", fieldNumber, "syncConf"}, _field.syncConf);
    json.setValue({"fields", fieldNumber, "medianBurstIRE"}, _field.medianBurstIRE);
    json.setValue({"fields", fieldNumber, "fieldPhaseID"}, _field.fieldPhaseID);
    json.setValue({"fields", fieldNumber, "audioSamples"}, _field.audioSamples);

    // Write the VITS metrics data if in use
    if (_field.vitsMetrics.inUse) {
        json.setValue({"fields", fieldNumber, "vitsMetrics", "wSNR"}, _field.vitsMetrics.wSNR);
        json.setValue({"fields", fieldNumber, "vitsMetrics", "bPSNR"}, _field.vitsMetrics.bPSNR);
    }

    // Write the VBI data if in use
    if (_field.vbi.inUse) {
        // Validate the VBI data array
        if (_field.vbi.vbiData.size() != 3) {
            qDebug() << "LdDecodeMetaData::write(): Invalid vbiData array!  Setting to -1";
            _field.vbi.vbiData.resize(3);
            _field.vbi.vbiData[0] = -1;
            _field.vbi.vbiData[1] = -1;
            _field.vbi.vbiData[2] = -1;
        }

        json.setValue({"fields", fieldNumber, "vbi", "vbiData", 0}, _field.vbi.vbiData[0]);
        json.setValue({"fields", fieldNumber, "vbi", "vbiData", 1}, _field.vbi.vbiData[1]);
        json.setValue({"fields", fieldNumber, "vbi", "vbiData", 2}, _field.vbi.vbiData[2]);

        switch(_field.vbi.type) {
        case LdDecodeMetaData::VbiDiscTypes::unknownDiscType:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 0}, 0);
            break;
        case LdDecodeMetaData::VbiDiscTypes::clv:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 0}, 1);
            break;
        case LdDecodeMetaData::VbiDiscTypes::cav:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 0}, 2);
            break;
        }

        json.setValue({"fields", fieldNumber, "vbi", "vp", 1}, _field.vbi.userCode);
        json.setValue({"fields", fieldNumber, "vbi", "vp", 2}, _field.vbi.picNo);
        json.setValue({"fields", fieldNumber, "vbi", "vp", 3}, _field.vbi.chNo);
        json.setValue({"fields", fieldNumber, "vbi", "vp", 4}, _field.vbi.clvHr);
        json.setValue({"fields", fieldNumber, "vbi", "vp", 5}, _field.vbi.clvMin);
        json.setValue({"fields", fieldNumber, "vbi", "vp", 6}, _field.vbi.clvSec);
        json.setValue({"fields", fieldNumber, "vbi", "vp", 7}, _field.vbi.clvPicNo);

        switch (_field.vbi.soundMode) {
        case LdDecodeMetaData::VbiSoundModes::stereo:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 0);
            break;
        case LdDecodeMetaData::VbiSoundModes::mono:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 1);
            break;
        case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 2);
            break;
        case LdDecodeMetaData::VbiSoundModes::bilingual:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 3);
            break;
        case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 4);
            break;
        case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 5);
            break;
        case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 6);
            break;
        case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 7);
            break;
        case LdDecodeMetaData::VbiSoundModes::mono_dump:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 8);
            break;
        case LdDecodeMetaData::VbiSoundModes::stereo_dump:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 9);
            break;
        case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 10);
            break;
        case LdDecodeMetaData::VbiSoundModes::futureUse:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 8}, 11);
            break;
        }

        switch (_field.vbi.soundModeAm2) {
        case LdDecodeMetaData::VbiSoundModes::stereo:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 0);
            break;
        case LdDecodeMetaData::VbiSoundModes::mono:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 1);
            break;
        case LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 2);
            break;
        case LdDecodeMetaData::VbiSoundModes::bilingual:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 3);
            break;
        case LdDecodeMetaData::VbiSoundModes::stereo_stereo:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 4);
            break;
        case LdDecodeMetaData::VbiSoundModes::stereo_bilingual:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 5);
            break;
        case LdDecodeMetaData::VbiSoundModes::crossChannelStereo:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 6);
            break;
        case LdDecodeMetaData::VbiSoundModes::bilingual_bilingual:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 7);
            break;
        case LdDecodeMetaData::VbiSoundModes::mono_dump:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 8);
            break;
        case LdDecodeMetaData::VbiSoundModes::stereo_dump:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 9);
            break;
        case LdDecodeMetaData::VbiSoundModes::bilingual_dump:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 10);
            break;
        case LdDecodeMetaData::VbiSoundModes::futureUse:
            json.setValue({"fields", fieldNumber, "vbi", "vp", 9}, 11);
            break;
        }

        // Convert the vitual flag booleans to the flags integer
        qint32 flags = 0;
        if (_field.vbi.leadIn)        flags += 0x0001;
        if (_field.vbi.leadOut)       flags += 0x0002;
        if (_field.vbi.picStop)       flags += 0x0004;
        if (_field.vbi.cx)            flags += 0x0008;
        if (_field.vbi.size)          flags += 0x0010;
        if (_field.vbi.side)          flags += 0x0020;
        if (_field.vbi.teletext)      flags += 0x0040;
        if (_field.vbi.dump)          flags += 0x0080;
        if (_field.vbi.fm)            flags += 0x0100;
        if (_field.vbi.digital)       flags += 0x0200;
        if (_field.vbi.parity)        flags += 0x0400;
        if (_field.vbi.copyAm2)       flags += 0x0800;
        if (_field.vbi.standardAm2)   flags += 0x1000;

        // Insert the flags into the VBI JSON
        json.setValue({"fields", fieldNumber, "vbi", "vp", 10}, flags);
    }

    // Write the NTSC specific record if in use
    if (_field.ntsc.inUse) {
        json.setValue({"fields", fieldNumber, "ntsc", "isFmCodeDataValid"}, _field.ntsc.isFmCodeDataValid);
        if (_field.ntsc.isFmCodeDataValid)
            json.setValue({"fields", fieldNumber, "ntsc", "fmCodeData"}, _field.ntsc.fmCodeData);
        else json.setValue({"fields", fieldNumber, "ntsc", "fmCodeData"}, -1);
        json.setValue({"fields", fieldNumber, "ntsc", "fieldFlag"}, _field.ntsc.fieldFlag);
        json.setValue({"fields", fieldNumber, "ntsc", "whiteFlag"}, _field.ntsc.whiteFlag);
    }

    // Write the drop-out records
    if (_field.dropOuts.startx.size() != 0) {
        // Populate the arrays with the drop out metadata
        for (qint32 doCounter = 0; doCounter < _field.dropOuts.startx.size(); doCounter++) {
            json.setValue({"fields", fieldNumber, "dropOuts", "startx", doCounter}, _field.dropOuts.startx[doCounter]);
            json.setValue({"fields", fieldNumber, "dropOuts", "endx", doCounter}, _field.dropOuts.endx[doCounter]);
            json.setValue({"fields", fieldNumber, "dropOuts", "fieldLine", doCounter}, _field.dropOuts.fieldLine[doCounter]);
        }
    }
}


// This method appends a new field to the existing metadata
void LdDecodeMetaData::appendField(LdDecodeMetaData::Field _field)
{
    updateField(_field, getNumberOfFields() + 1);
}

// Method to get the available number of fields (according to the metadata)
qint32 LdDecodeMetaData::getNumberOfFields()
{
    return json.size({"fields"});
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
bool LdDecodeMetaData::getIsFirstFieldFirst()
{
    return isFirstFieldFirst;
}

// Method to get the current disc type (CAV/CLV/Unknown) based on the VBI data
LdDecodeMetaData::VbiDiscTypes LdDecodeMetaData::getDiscTypeFromVbi()
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
        Field field = getField(fieldNumber);
        if (!(field.vbi.leadIn || field.vbi.leadOut)) {
            if (field.vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) cavCount++;
            if (field.vbi.type == LdDecodeMetaData::VbiDiscTypes::clv) clvCount++;
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
    VideoParameters videoParameters = getVideoParameters();

    if (clvTimeCode.hours != -1) {
        if (videoParameters.isSourcePal) frameNumber += clvTimeCode.hours * 3600 * 25;
        else frameNumber += clvTimeCode.hours * 3600 * 30;
    }

    if (clvTimeCode.minutes != -1) {
        if (videoParameters.isSourcePal) frameNumber += clvTimeCode.minutes * 60 * 25;
        else frameNumber += clvTimeCode.minutes * 60 * 30;
    }

    if (clvTimeCode.seconds != -1) {
        if (videoParameters.isSourcePal) frameNumber += clvTimeCode.seconds * 25;
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

    if (getVideoParameters().isSourcePal) {
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

