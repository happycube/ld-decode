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

    while(!abort) {
        // Get the next field to process from the input file
        if (!processingPool.getInputField(fieldNumber, sourceFieldData, fieldMetadata, videoParameters)) {
            // No more input fields -- exit
            break;
        }

        // Show some debug
//        if (fieldMetadata.isFirstField) qDebug() << "Getting VITS for field" << fieldNumber << "(first)";
//        else  qDebug() << "Getting VITS for field" << fieldNumber << "(second)";

        // Get multiple possible black and white measurement points based on video format, etc.
        QVector<SourceVideo::Data> wlSlice;
        QVector<SourceVideo::Data> blSlice;

        if (videoParameters.isSourcePal) {
            // PAL (taken from ld-decode core.py)
            wlSlice.append(getFieldLineSlice(sourceFieldData, 19, 12, 8));
            blSlice.append(getFieldLineSlice(sourceFieldData, 22, 12, 50));
        } else {
            // NTSC (taken from ld-decode core.py)
            wlSlice.append(getFieldLineSlice(sourceFieldData, 20, 14, 12));
            wlSlice.append(getFieldLineSlice(sourceFieldData, 20, 52, 8));
            wlSlice.append(getFieldLineSlice(sourceFieldData, 13, 13, 15));
            blSlice.append(getFieldLineSlice(sourceFieldData, 1, 10, 20));
        }

        // Calculate the 90 IRE and 110 IRE points
        qint32 ire90 = (((videoParameters.white16bIre - videoParameters.black16bIre) / 100) * 90) + videoParameters.black16bIre;
        qint32 ire110 = (((videoParameters.white16bIre - videoParameters.black16bIre) / 100) * 110) + videoParameters.black16bIre;

        // Only pick the white slice if it has values between 90 and 110 IRE
        qint32 wlSliceToUse = -1;
        for (qint32 i = 0; i < wlSlice.size(); i++) {
            bool sliceGood = true;
            if (wlSlice[i].size() > 0) {
                for (qint32 dp = 0; dp < wlSlice[i].size(); dp++) {
                    if (wlSlice[i][dp] < ire90 || wlSlice[i][dp] > ire110) {
                        sliceGood = false;
                    }
                }
            } else sliceGood = false;

            if (sliceGood) {
                wlSliceToUse = i;
                break;
            }
        }

        // Always use the black slice (there is only ever one to choose from)
        qint32 blSliceToUse = 0;

        // Only calculate the wSNR if we have a valid slice
        double wSNR = 0;    // wSNR  - white SNR
        if (wlSliceToUse != -1) {
            wSNR = calculateSnr(wlSlice[wlSliceToUse], true);
        } else qDebug() << "Didn't get a valid wSNR slice for field" << fieldNumber;

        // Only calculate the bPSNT if we have a valid slice
        double bPSNR = 0;   // bPSNR - black PSNR
        if (blSliceToUse != -1) {
            bPSNR = calculateSnr(blSlice[blSliceToUse], true);
        } else qDebug() << "Didn't get a valid bPSNR slice for field" << fieldNumber;

        // Show the result as debug
        qDebug() << "Field #" << fieldNumber << "has wSNR of" << wSNR << "and bPSNR of" << bPSNR;

        // Update the metadata for the field
        fieldMetadata.vitsMetrics.wSNR = static_cast<qreal>(wSNR);
        fieldMetadata.vitsMetrics.bPSNR = static_cast<qreal>(bPSNR);

        // Write the result to the output metadata
        if (!processingPool.setOutputField(fieldNumber, fieldMetadata)) {
            abort = true;
            break;
        }
    }
}

// Get a specific slice of a field line and return all the values
SourceVideo::Data VitsAnalyser::getFieldLineSlice(const SourceVideo::Data &sourceField, qint32 fieldLine, qint32 startUs, qint32 lengthUs)
{
    fieldLine--; // Adjust for field offset

    // Range-check the field line
    if (fieldLine < 0 || fieldLine >= videoParameters.fieldHeight) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return SourceVideo::Data();
    }

    // Calculate the number of samples per uS for the field
    double samplesPerUs = 0;
    if (videoParameters.isSourcePal) samplesPerUs = static_cast<double>(videoParameters.fieldWidth) / 64.0;
    else samplesPerUs = static_cast<double>(videoParameters.fieldWidth) / 63.5;

    // Get the start and end sample positions
    double startSampleDouble = startUs * samplesPerUs;
    double lengthSampleDouble = lengthUs * samplesPerUs;

    qint32 startPointer = (fieldLine * videoParameters.fieldWidth) + static_cast<qint32>(startSampleDouble);
    qint32 length = static_cast<qint32>(lengthSampleDouble);

    return sourceField.mid(startPointer, length);
}

// Calculate the SNR or Percentage SNR
double VitsAnalyser::calculateSnr(const SourceVideo::Data &data, bool usePsnr)
{
    double signal = 0;
    if (usePsnr) signal = 100.0; else signal = calcMean(data); // Compute the arithmetic mean
    double noise = calcStd(data); // Compute the standard deviation

    return 20 * log10(signal / noise);
}

// The arithmetic mean is the sum of the elements divided by the number of elements.
double VitsAnalyser::calcMean(const SourceVideo::Data &data)
{
    double result = 0;

    for (qint32 i = 0; i < data.size(); i++) {
        result += static_cast<double>(data[i]);
    }

    return result / static_cast<double>(data.size());
}

// The standard deviation is the square root of the average of the squared deviations from the mean
double VitsAnalyser::calcStd(const SourceVideo::Data &data)
{
    double sum = 0.0, mean, standardDeviation = 0.0;

    for(qint32 i = 0; i < data.size(); ++i)
        sum += static_cast<double>(data[i]);

    mean = sum / static_cast<double>(data.size());

    for(qint32 i = 0; i < data.size(); ++i)
        standardDeviation += pow(static_cast<double>(data[i]) - mean, 2);

    return sqrt(standardDeviation / static_cast<double>(data.size()));
}


