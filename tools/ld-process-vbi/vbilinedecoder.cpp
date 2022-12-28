/************************************************************************

    vbilinedecoder.cpp

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vbi is free software: you can redistribute it and/or
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

#include "vbilinedecoder.h"
#include "decoderpool.h"

VbiLineDecoder::VbiLineDecoder(QAtomicInt& _abort, DecoderPool& _decoderPool, QObject *parent)
    : QThread(parent), abort(_abort), decoderPool(_decoderPool)
{

}

// Thread main processing method
void VbiLineDecoder::run()
{
    qint32 fieldNumber;

    // Input data buffers
    SourceVideo::Data sourceFieldData;
    LdDecodeMetaData::Field fieldMetadata;
    LdDecodeMetaData::VideoParameters videoParameters;

    while(!abort) {
        // Get the next field to process from the input file
        if (!decoderPool.getInputField(fieldNumber, sourceFieldData, fieldMetadata, videoParameters)) {
            // No more input fields -- exit
            break;
        }

        BiphaseCode biphaseCode;

        FmCode fmCode;
        FmCode::FmDecode fmDecode;

        bool isWhiteFlag = false;
        WhiteFlag whiteFlag;

        ClosedCaption closedCaption;
        ClosedCaption::CcData ccData;

        if (fieldMetadata.isFirstField) qDebug() << "VbiLineDecoder::process(): Getting metadata for field" << fieldNumber << "(first)";
        else qDebug() << "VbiLineDecoder::process(): Getting metadata for field" << fieldNumber << "(second)";

        // Get the 24-bit biphase-coded data from field lines 16-18
        BiphaseCode biphaseCode;
        biphaseCode.decodeLines(getActiveVideoLine(sourceFieldData, 16 - startFieldLine, videoParameters),
                                getActiveVideoLine(sourceFieldData, 17 - startFieldLine, videoParameters),
                                getActiveVideoLine(sourceFieldData, 18 - startFieldLine, videoParameters),
                                videoParameters, fieldMetadata);

        // Show the VBI data as hexadecimal (for every 1000th field)
        if (fieldNumber % 1000 == 0) {
            qInfo() << "Processing field" << fieldNumber;
        }

        // Process NTSC specific data if source type is NTSC
        if (videoParameters.system == NTSC) {
            // Get the 40-bit FM coded data from field line 10
            fmDecode = fmCode.fmDecoder(getActiveVideoLine(sourceFieldData, 10 - startFieldLine, videoParameters), videoParameters);

            // Get the white flag from field line 11
            isWhiteFlag = whiteFlag.getWhiteFlag(getActiveVideoLine(sourceFieldData, 11 - startFieldLine, videoParameters), videoParameters);

            // Get the closed captioning from field line 21
            ccData = closedCaption.getData(getActiveVideoLine(sourceFieldData, 21 - startFieldLine, videoParameters), videoParameters);

            // Update the metadata
            if (fmDecode.receiverClockSyncBits != 0) {
                fieldMetadata.ntsc.isFmCodeDataValid = true;
                fieldMetadata.ntsc.fmCodeData = static_cast<qint32>(fmDecode.data);
                if (fmDecode.videoFieldIndicator == 1) fieldMetadata.ntsc.fieldFlag = true;
                else fieldMetadata.ntsc.fieldFlag = false;
            } else {
                fieldMetadata.ntsc.isFmCodeDataValid = false;
                fieldMetadata.ntsc.fmCodeData = -1;
                fieldMetadata.ntsc.fieldFlag = false;
            }

            fieldMetadata.ntsc.whiteFlag = isWhiteFlag;
            fieldMetadata.ntsc.inUse = true;

            if (ccData.isValid) {
                fieldMetadata.ntsc.ccData0 = ccData.byte0;
                fieldMetadata.ntsc.ccData1 = ccData.byte1;
            } else {
                fieldMetadata.ntsc.ccData0 = -1;
                fieldMetadata.ntsc.ccData1 = -1;
            }
        }

        // Write the result to the output metadata
        if (!decoderPool.setOutputField(fieldNumber, fieldMetadata)) {
            abort = true;
            break;
        }
    }
}

// Private method to get a single scanline of greyscale data
SourceVideo::Data VbiLineDecoder::getActiveVideoLine(const SourceVideo::Data &sourceField, qint32 fieldLine,
                                                     LdDecodeMetaData::VideoParameters videoParameters)
{
    // Range-check the scan line
    if (fieldLine < 0 || fieldLine >= videoParameters.fieldHeight) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return SourceVideo::Data();
    }

    qint32 startPointer = (fieldLine * videoParameters.fieldWidth) + videoParameters.activeVideoStart;
    qint32 length = videoParameters.activeVideoEnd - videoParameters.activeVideoStart;

    return sourceField.mid(startPointer, length);
}
