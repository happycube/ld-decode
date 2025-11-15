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
#include "biphasecode.h"
#include "closedcaption.h"
#include "decoderpool.h"
#include "fmcode.h"
#include "videoid.h"
#include "vitccode.h"
#include "whiteflag.h"

#include <cmath>

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

    while (!abort) {
        // Get the next field to process from the input file
        if (!decoderPool.getInputField(fieldNumber, sourceFieldData, fieldMetadata, videoParameters)) {
            // No more input fields -- exit
            break;
        }

        // Show progress (for every 1000th field)
        if (fieldNumber % 1000 == 0) {
            qInfo() << "Processing field" << fieldNumber;
        }

        if (fieldMetadata.isFirstField) qDebug() << "VbiLineDecoder::process(): Getting metadata for field" << fieldNumber << "(first)";
        else qDebug() << "VbiLineDecoder::process(): Getting metadata for field" << fieldNumber << "(second)";

        // Get the 24-bit biphase-coded data from field lines 16-18
        BiphaseCode biphaseCode;
        biphaseCode.decodeLines(getFieldLine(sourceFieldData, 16, videoParameters),
                                getFieldLine(sourceFieldData, 17, videoParameters),
                                getFieldLine(sourceFieldData, 18, videoParameters),
                                videoParameters, fieldMetadata);

        // Process NTSC specific data if source type is NTSC
        if (videoParameters.system == NTSC) {
            // Get the 40-bit FM coded data from field line 10
            FmCode fmCode;
            fmCode.decodeLine(getFieldLine(sourceFieldData, 10, videoParameters), videoParameters, fieldMetadata);

            // Get the white flag from field line 11
            WhiteFlag whiteFlag;
            whiteFlag.decodeLine(getFieldLine(sourceFieldData, 11, videoParameters), videoParameters, fieldMetadata);

            // Get IEC 61880 data from field line 20
            VideoID videoID;
            videoID.decodeLine(getFieldLine(sourceFieldData, 20, videoParameters), videoParameters, fieldMetadata);

            fieldMetadata.ntsc.inUse = true;
        }

        // Get VITC data, trying each possible line and stopping when we find a valid one
        VitcCode vitcCode;
        for (qint32 lineNumber: vitcCode.getLineNumbers(videoParameters)) {
            if (vitcCode.decodeLine(getFieldLine(sourceFieldData, lineNumber, videoParameters),
                                    videoParameters, fieldMetadata)) {
                break;
            }
        }

        // Get Closed Caption data from line 21 (525-line) or 22 (625-line)
        ClosedCaption closedCaption;
        closedCaption.decodeLine(getFieldLine(sourceFieldData, (videoParameters.system == PAL) ? 22 : 21, videoParameters),
                                 videoParameters, fieldMetadata);

        // Process VITS metrics for signal quality measurement
        processVitsMetrics(sourceFieldData, videoParameters, fieldMetadata);

        // Write the result to the output metadata
        if (!decoderPool.setOutputField(fieldNumber, fieldMetadata)) {
            abort = true;
            break;
        }
    }
}

// Private method to get a single scanline of greyscale data
SourceVideo::Data VbiLineDecoder::getFieldLine(const SourceVideo::Data &sourceField, qint32 fieldLine,
                                               const LdDecodeMetaData::VideoParameters& videoParameters)
{
    // Range-check the field line
    if (fieldLine < startFieldLine || fieldLine > endFieldLine) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return SourceVideo::Data();
    }

    // Calculate position: lines are 1-indexed, sourceField starts at startFieldLine
    qint32 startPointer = (fieldLine - startFieldLine) * videoParameters.fieldWidth;
    return sourceField.mid(startPointer, videoParameters.fieldWidth);
}

// VITS metrics processing - measures signal quality
void VbiLineDecoder::processVitsMetrics(const SourceVideo::Data &sourceField,
                                       const LdDecodeMetaData::VideoParameters &videoParameters,
                                       LdDecodeMetaData::Field &fieldMetadata)
{
    // Get multiple possible black and white measurement points based on video format
    QVector<QVector<double>> wlSlice;
    QVector<QVector<double>> blSlice;

    if (videoParameters.system == PAL) {
        // 625 lines (taken from ld-decode core.py)
        wlSlice.append(getFieldLineSlice(sourceField, 19, 12, 8, videoParameters));
        blSlice.append(getFieldLineSlice(sourceField, 22, 12, 50, videoParameters));
    } else {
        // 525 lines (taken from ld-decode core.py)
        wlSlice.append(getFieldLineSlice(sourceField, 20, 14, 12, videoParameters));
        wlSlice.append(getFieldLineSlice(sourceField, 20, 52, 8, videoParameters));
        wlSlice.append(getFieldLineSlice(sourceField, 13, 13, 15, videoParameters));
        blSlice.append(getFieldLineSlice(sourceField, 1, 10, 20, videoParameters));
    }

    // Only pick the white slice if it has a mean value between 90 and 110 IRE
    qint32 wlSliceToUse = -1;
    for (qint32 i = 0; i < wlSlice.size(); i++) {
        double wlMean = calcMean(wlSlice[i]);
        if (wlMean >= 90 && wlMean <= 110) {
            wlSliceToUse = i;
            break;
        }
    }

    // Always use the first black slice (there is only ever one to choose from)
    qint32 blSliceToUse = 0;

    // Only calculate the wSNR if we have a valid slice
    double wSNR = 0;
    if (wlSliceToUse != -1) wSNR = calculateSnr(wlSlice[wlSliceToUse], true);

    // Only calculate the bPSNR if we have a valid slice
    double bPSNR = 0;
    if (blSliceToUse != -1) bPSNR = calculateSnr(blSlice[blSliceToUse], true);

    // Update the metadata for the field
    fieldMetadata.vitsMetrics.inUse = true;
    fieldMetadata.vitsMetrics.wSNR = roundDouble(wSNR, 1);
    fieldMetadata.vitsMetrics.bPSNR = roundDouble(bPSNR, 1);

    qDebug().nospace() << "VITS: wSNR=" << fieldMetadata.vitsMetrics.wSNR
             << " bPSNR=" << fieldMetadata.vitsMetrics.bPSNR;
}

// Get a specific slice of a field line and return all the values
QVector<double> VbiLineDecoder::getFieldLineSlice(const SourceVideo::Data &sourceField, qint32 fieldLine,
                                                  qint32 startUs, qint32 lengthUs,
                                                  const LdDecodeMetaData::VideoParameters &videoParameters)
{
    QVector<double> returnData;

    // Range-check the field line
    if (fieldLine < startFieldLine || fieldLine > endFieldLine) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return returnData;
    }

    // Calculate the number of samples per uS for the field
    double samplesPerUs = 0;
    if (videoParameters.system == PAL) samplesPerUs = static_cast<double>(videoParameters.fieldWidth) / 64.0;
    else samplesPerUs = static_cast<double>(videoParameters.fieldWidth) / 63.5;

    // Get the start and end sample positions
    double startSampleDouble = startUs * samplesPerUs;
    double lengthSampleDouble = lengthUs * samplesPerUs;

    // Calculate position relative to startFieldLine
    qint32 startPointer = ((fieldLine - startFieldLine) * videoParameters.fieldWidth) + static_cast<qint32>(startSampleDouble);
    qint32 length = static_cast<qint32>(lengthSampleDouble);

    // Convert data points to floating-point IRE values
    returnData.resize(length);
    for (qint32 i = startPointer; i < startPointer + length; i++) {
        returnData[i - startPointer] = (static_cast<double>(sourceField[i]) - static_cast<double>(videoParameters.black16bIre)) /
                ((static_cast<double>(videoParameters.white16bIre) - static_cast<double>(videoParameters.black16bIre)) / 100.0);
    }

    return returnData;
}

// Calculate the SNR or Percentage SNR
double VbiLineDecoder::calculateSnr(QVector<double> &data, bool usePsnr)
{
    double signal = 0;
    if (usePsnr) signal = 100.0; else signal = calcMean(data);
    double noise = calcStd(data);

    return 20.0 * log10(signal / noise);
}

// The arithmetic mean is the sum of the elements divided by the number of elements
double VbiLineDecoder::calcMean(QVector<double> &data)
{
    double result = 0;

    for (qint32 i = 0; i < data.size(); i++) {
        result += data[i];
    }

    return result / static_cast<double>(data.size());
}

// The standard deviation is the square root of the average of the squared deviations from the mean
double VbiLineDecoder::calcStd(QVector<double> &data)
{
    double sum = 0.0;
    double mean = 0.0;
    double standardDeviation = 0.0;

    for(qint32 i = 0; i < data.size(); ++i)
        sum += data[i];

    mean = sum / static_cast<double>(data.size());

    for(qint32 i = 0; i < data.size(); ++i)
        standardDeviation += pow(data[i] - mean, 2.0);

    return sqrt(standardDeviation / static_cast<double>(data.size()));
}

// Round a double to x decimal places
double VbiLineDecoder::roundDouble(double in, qint32 decimalPlaces)
{
    const double multiplier = pow(10.0, decimalPlaces);
    return ceil(in * multiplier) / multiplier;
}
