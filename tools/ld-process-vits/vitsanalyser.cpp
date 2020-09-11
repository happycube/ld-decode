/************************************************************************

    vitsanalyser.cpp

    ld-process-vits - Vertical Interval Test Signal processing
    Copyright (C) 2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vits is free software: you can redistribute it and/or
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


#include "vitsanalyser.h"
#include "processingpool.h"

// Definitions of static constexpr data members, for compatibility with
// pre-C++17 compilers
constexpr qint32 VitsAnalyser::startFieldLine;
constexpr qint32 VitsAnalyser::endFieldLine;

VitsAnalyser::VitsAnalyser(QAtomicInt& _abort, ProcessingPool& _processingPool, QObject *parent)
    : QThread(parent), abort(_abort), processingPool(_processingPool)
{

}

// Thread main processing method
void VitsAnalyser::run()
{
    qint32 fieldNumber;

    // Input data buffers
    SourceVideo::Data sourceFieldData;
    LdDecodeMetaData::Field fieldMetadata;
    LdDecodeMetaData::VideoParameters videoParameters;

    while(!abort) {
        // Get the next field to process from the input file
        if (!processingPool.getInputField(fieldNumber, sourceFieldData, fieldMetadata, videoParameters)) {
            // No more input fields -- exit
            break;
        }

        if (fieldMetadata.isFirstField) qDebug() << "Getting VITS for field" << fieldNumber << "(first)";
        else  qDebug() << "Getting VITS for field" << fieldNumber << "(second)";


        // Code borrowed from VBI processing... to-do replace...

//        // Determine the 16-bit zero-crossing point
//        qint32 zcPoint = videoParameters.white16bIre - videoParameters.black16bIre;

//        // Get the VBI data from field lines 16-18
//        qDebug() << "Getting field-lines for field" << fieldNumber;
//        for (qint32 i = 0; i < 3; i++) {
//            fieldMetadata.vbi.vbiData[i] = manchesterDecoder(getActiveVideoLine(sourceFieldData, i + 16 - startFieldLine, videoParameters),
//                                                             zcPoint, videoParameters);
//            if (fieldMetadata.vbi.vbiData[i] == 0) qDebug() << "No VBI present on line" << i + 16;
//        }

//        // Show the VBI data as hexadecimal (for every 1000th field)
//        if (fieldNumber % 1000 == 0) {
//            qInfo() << "Processing field" << fieldNumber;
//        }

//        // Process NTSC specific data if source type is NTSC
//        if (!videoParameters.isSourcePal) {
//            // Get the 40-bit FM coded data from field line 10
//            fmDecode = fmCode.fmDecoder(getActiveVideoLine(sourceFieldData, 10 - startFieldLine, videoParameters), videoParameters);

//            // Get the white flag from field line 11
//            isWhiteFlag = whiteFlag.getWhiteFlag(getActiveVideoLine(sourceFieldData, 11 - startFieldLine, videoParameters), videoParameters);

//            // Get the closed captioning from field line 21
//            ccData = closedCaption.getData(getActiveVideoLine(sourceFieldData, 21 - startFieldLine, videoParameters), videoParameters);

//            // Update the metadata
//            if (fmDecode.receiverClockSyncBits != 0) {
//                fieldMetadata.ntsc.isFmCodeDataValid = true;
//                fieldMetadata.ntsc.fmCodeData = static_cast<qint32>(fmDecode.data);
//                if (fmDecode.videoFieldIndicator == 1) fieldMetadata.ntsc.fieldFlag = true;
//                else fieldMetadata.ntsc.fieldFlag = false;
//            } else {
//                fieldMetadata.ntsc.isFmCodeDataValid = false;
//                fieldMetadata.ntsc.fmCodeData = -1;
//                fieldMetadata.ntsc.fieldFlag = false;
//            }

//            fieldMetadata.ntsc.whiteFlag = isWhiteFlag;
//            fieldMetadata.ntsc.inUse = true;

//            if (ccData.isValid) {
//                fieldMetadata.ntsc.ccData0 = ccData.byte0;
//                fieldMetadata.ntsc.ccData1 = ccData.byte1;
//            } else {
//                fieldMetadata.ntsc.ccData0 = -1;
//                fieldMetadata.ntsc.ccData1 = -1;
//            }
//        }

//        // Update the metadata for the field
//        fieldMetadata.vbi.inUse = true;

        // Write the result to the output metadata
        if (!processingPool.setOutputField(fieldNumber, fieldMetadata)) {
            abort = true;
            break;
        }
    }
}

// Private method to get a single scanline of greyscale data
SourceVideo::Data VitsAnalyser::getActiveVideoLine(const SourceVideo::Data &sourceField, qint32 fieldLine,
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

