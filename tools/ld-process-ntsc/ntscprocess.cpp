/************************************************************************

    ntscprocess.cpp

    ld-process-ntsc - IEC NTSC specific processor for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-ntsc is free software: you can redistribute it and/or
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

#include "ntscprocess.h"

NtscProcess::NtscProcess(QObject *parent) : QObject(parent)
{

}

bool NtscProcess::process(QString inputFileName)
{
    LdDecodeMetaData ldDecodeMetaData;
    SourceVideo sourceVideo;

    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    qDebug() << "NtscProcess::process(): Input source is" << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight << "filename" << inputFileName;

    // Ensure that the source video is NTSC
    if (videoParameters.isSourcePal) {
        qWarning("Input source is PAL - The PAL IEC LaserDisc specifications do not support 40-bit FM codes");
        return false;
    }

    // Open the source video
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // Process the VBI data for the fields
    for (qint32 fieldNumber = 1; fieldNumber <= sourceVideo.getNumberOfAvailableFields(); fieldNumber++) {
        SourceField *sourceField;
        FmCode fmCode;
        FmCode::FmDecode fmDecode;
        bool isWhiteFlag = false;
        WhiteFlag whiteFlag;

        // Get the source field
        sourceField = sourceVideo.getVideoField(fieldNumber);

        // Get the existing field data from the metadata
        LdDecodeMetaData::Field field = ldDecodeMetaData.getField(fieldNumber);
        if (field.isEven) qInfo() << "Processing field" << fieldNumber << "(Even)";
        else  qInfo() << "Processing field" << fieldNumber << "(Odd)";

        // Get the 40-bit FM coded data from the field lines
        fmDecode = fmCode.fmDecoder(getActiveVideoLine(sourceField, 10, videoParameters), videoParameters);

        // Get the white flag from the field lines
        isWhiteFlag = whiteFlag.getWhiteFlag(getActiveVideoLine(sourceField, 11, videoParameters), videoParameters);

        // Update the metadata
        if (fmDecode.receiverClockSyncBits != 0) {
            field.ntsc.isFmCodeDataValid = true;
            field.ntsc.fmCodeData = static_cast<qint32>(fmDecode.data);
            if (fmDecode.videoFieldIndicator == 1) field.ntsc.fieldFlag = true;
            else field.ntsc.fieldFlag = false;
        } else {
            field.ntsc.isFmCodeDataValid = false;
            field.ntsc.fmCodeData = -1;
            field.ntsc.fieldFlag = false;
        }

        field.ntsc.whiteFlag = isWhiteFlag;

        // Update the metadata for the field
        field.ntsc.inUse = true;
        ldDecodeMetaData.updateField(field, fieldNumber);
        qDebug() << "NtscProcess::process(): Updating metadata for field" << fieldNumber;
    }

    // Write the metadata file
    QString outputFileName = inputFileName + ".json";
    ldDecodeMetaData.write(outputFileName);
    qInfo() << "Processing complete";

    // Close the source video
    sourceVideo.close();

    return true;
}

// Private method to get a single scanline of greyscale data
QByteArray NtscProcess::getActiveVideoLine(SourceField *sourceField, qint32 fieldLine,
                                        LdDecodeMetaData::VideoParameters videoParameters)
{
    // Range-check the scan line
    if (fieldLine > videoParameters.fieldHeight || fieldLine < 1) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return QByteArray();
    }

    qint32 startPointer = ((fieldLine - 1) * videoParameters.fieldWidth * 2) + (videoParameters.blackLevelEnd * 2);
    qint32 length = (videoParameters.activeVideoEnd - videoParameters.blackLevelEnd) * 2;

    return sourceField->getFieldData().mid(startPointer, length);
}
