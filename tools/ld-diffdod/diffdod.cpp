/************************************************************************

    diffdod.cpp

    ld-diffdod - TBC Differential Drop-Out Detection tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-diffdod is free software: you can redistribute it and/or
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

#include "diffdod.h"

DiffDod::DiffDod(QObject *parent) : QObject(parent)
{

}

// Perform differential dropout detection to determine (for each source) which frame pixels are valid
// Note: This method processes a single frame
void DiffDod::performFrameDiffDod(QVector<SourceVideo::Data>& firstFields, QVector<SourceVideo::Data>& secondFields,
                                     qint32 dodThreshold, bool lumaClip, LdDecodeMetaData::VideoParameters videoParameters,
                                     QVector<qint32> availableSourcesForFrame)
{
    // Range check the diffDOD threshold percent
    if (dodThreshold < 1) dodThreshold = 1;
    if (dodThreshold > 100) dodThreshold = 100;

    // Create a differential map of the fields for the avaialble frames (based on the DOD threshold)
    QVector<QByteArray> firstFieldsDiff = getFieldErrorByMedian(firstFields, dodThreshold,
                                                                videoParameters, availableSourcesForFrame);
    QVector<QByteArray> secondFieldsDiff = getFieldErrorByMedian(secondFields, dodThreshold,
                                                                 videoParameters, availableSourcesForFrame);

    // Perform luma clip check?
    if (lumaClip) {
        performLumaClip(firstFields, firstFieldsDiff, videoParameters, availableSourcesForFrame);
        performLumaClip(secondFields, secondFieldsDiff, videoParameters, availableSourcesForFrame);
    }

    // Create the drop-out metadata based on the differential map of the fields
    m_firstFieldDropouts = getFieldDropouts(firstFieldsDiff, videoParameters, availableSourcesForFrame);
    m_secondFieldDropouts = getFieldDropouts(secondFieldsDiff, videoParameters, availableSourcesForFrame);

    // Concatenate dropouts on the same line that are close together (to cut down on the
    // amount of generated metadata with noisy/bad sources)
    concatenateFieldDropouts(m_firstFieldDropouts, availableSourcesForFrame);
    concatenateFieldDropouts(m_secondFieldDropouts, availableSourcesForFrame);
}

// Method to get the result of the diffDOD process
void DiffDod::getResults(QVector<LdDecodeMetaData::DropOuts>& firstFieldDropouts,
                            QVector<LdDecodeMetaData::DropOuts>& secondFieldDropouts)
{
    firstFieldDropouts = m_firstFieldDropouts;
    secondFieldDropouts = m_secondFieldDropouts;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Create an error map of the fields based on median value differential analysis
// Note: This only functions within the colour burst and visible areas of the frame
QVector<QByteArray> DiffDod::getFieldErrorByMedian(QVector<SourceVideo::Data> &fields, qint32 dodThreshold,
                                                      LdDecodeMetaData::VideoParameters videoParameters,
                                                      QVector<qint32> availableSourcesForFrame)
{
    // This method requires at least three source frames
    if (availableSourcesForFrame.size() < 3) {
        return QVector<QByteArray>();
    }

    // Normalize the % dodThreshold to 0.00-1.00
    float threshold = static_cast<float>(dodThreshold) / 100.0;

    // Calculate the linear threshold for the colourburst region
    qint32 cbThreshold = ((65535 / 100) * dodThreshold) / 8; // Note: The /8 is just a guess

    // Make a vector to store the result of the diff
    QVector<QByteArray> fieldDiff;
    fieldDiff.resize(fields.size());

    // Resize the fieldDiff sub-vectors and default the elements to zero
    for (qint32 sourcePointer = 0; sourcePointer < fields.size(); sourcePointer++) {
        fieldDiff[sourcePointer].fill(0, videoParameters.fieldHeight * videoParameters.fieldWidth);
    }

    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;
        for (qint32 x = videoParameters.colourBurstStart; x < videoParameters.activeVideoEnd; x++) {
            // Get the dot value from all of the sources
            QVector<qint32> dotValues(fields.size());
            for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
                qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source
                dotValues[sourceNo] = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);
            }

            // If we are in the visible area use Rec.709 logarithmic comparison
            if (x >= videoParameters.activeVideoStart && x < videoParameters.activeVideoEnd) {
                // Compute the median of the dot values
                float vMedian = static_cast<float>(convertLinearToBrightness(median(dotValues), videoParameters.black16bIre, videoParameters.white16bIre, videoParameters.isSourcePal));

                for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
                    qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source
                    float v = convertLinearToBrightness(dotValues[sourceNo], videoParameters.black16bIre, videoParameters.white16bIre, videoParameters.isSourcePal);
                    if ((v - vMedian) > threshold) fieldDiff[sourceNo][x + startOfLinePointer] = 1;
                }
            }

            // If we are in the colourburst use linear comparison
            if (x >= videoParameters.colourBurstStart && x < videoParameters.colourBurstEnd) {
                // We are in the colour burst, use linear comparison
                qint32 dotMedian = median(dotValues);
                for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
                    qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source
                    if ((dotValues[sourceNo] - dotMedian) > cbThreshold) fieldDiff[sourceNo][x + startOfLinePointer] = 1;
                }
            }
        }
    }

    return fieldDiff;
}

// Perform a luma clip check on the field
void DiffDod::performLumaClip(QVector<SourceVideo::Data> &fields, QVector<QByteArray> &fieldsDiff,
                                 LdDecodeMetaData::VideoParameters videoParameters,
                                 QVector<qint32> availableSourcesForFrame)
{
    // Process the fields one line at a time
    for (qint32 y = videoParameters.firstActiveFieldLine; y < videoParameters.lastActiveFieldLine; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
            qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

            // Set the clipping levels
            qint32 blackClipLevel = videoParameters.black16bIre - 4000;
            qint32 whiteClipLevel = videoParameters.white16bIre + 4000;

            for (qint32 x = videoParameters.activeVideoStart; x < videoParameters.activeVideoEnd; x++) {
                // Get the IRE value for the source field, cast to 32 bit signed
                qint32 sourceIre = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);

                // Check for a luma clip event
                if ((sourceIre < blackClipLevel) || (sourceIre > whiteClipLevel)) {
                    // Luma has clipped, scan back and forth looking for the start
                    // and end points of the event (i.e. the point where the event
                    // goes back into the expected IRE range)
                    qint32 range = 10; // maximum + and - scan range
                    qint32 minX = x - range;
                    if (minX < videoParameters.activeVideoStart) minX = videoParameters.activeVideoStart;
                    qint32 maxX = x + range;
                    if (maxX > videoParameters.activeVideoEnd) maxX = videoParameters.activeVideoEnd;

                    qint32 startX = x;
                    qint32 endX = x;

                    for (qint32 i = x; i > minX; i--) {
                        qint32 ire = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);
                        if (ire < videoParameters.black16bIre || ire > videoParameters.white16bIre) {
                            startX = i;
                        }
                    }

                    for (qint32 i = x+1; i < maxX; i++) {
                        qint32 ire = static_cast<qint32>(fields[sourceNo][x + startOfLinePointer]);
                        if (ire < videoParameters.black16bIre || ire > videoParameters.white16bIre) {
                            endX = i;
                        }
                    }

                    // Mark the dropout
                    for (qint32 i = startX; i < endX; i++) {
                        fieldsDiff[sourceNo][i + startOfLinePointer] = 1;
                    }

                    x = x + range;
                }
            }
        }
    }
}

// Method to create the field drop-out metadata based on the differential map of the fields
// This method compares each available source against all other available sources to determine where the source differs.
// If any of the frame's contents do not match that of the other sources, the frame's pixels are marked as dropouts.
QVector<LdDecodeMetaData::DropOuts> DiffDod::getFieldDropouts(QVector<QByteArray> &fieldsDiff,
                                                                 LdDecodeMetaData::VideoParameters videoParameters,
                                                                 QVector<qint32> availableSourcesForFrame)
{
    // Create and resize the return data vector
    QVector<LdDecodeMetaData::DropOuts> fieldDropouts;
    fieldDropouts.resize(fieldsDiff.size());

    // This method requires at least three source frames
    if (availableSourcesForFrame.size() < 3) {
        return QVector<LdDecodeMetaData::DropOuts>();
    }

    // Define the area in which DOD should be performed
    qint32 areaStart = videoParameters.colourBurstStart;
    qint32 areaEnd = videoParameters.activeVideoEnd;

    // Process the frame one line at a time (both fields)
    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        qint32 startOfLinePointer = y * videoParameters.fieldWidth;

        // Process each source line in turn
        for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
            qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

            // Mark the individual dropouts
            qint32 doCounter = 0;
            qint32 minimumDetectLength = 5;

            qint32 doStart = 0;
            qint32 doFieldLine = 0;

            // Only create dropouts between the start of the colour burst and the end of the
            // active video area
            for (qint32 x = areaStart; x < areaEnd; x++) {
                // Compare field dot to threshold
                if (static_cast<qint32>(fieldsDiff[sourceNo][x + startOfLinePointer]) == 0) {
                    // Current X is not a dropout
                    if (doCounter > 0) {
                        doCounter--;
                        if (doCounter == 0) {
                            // Mark the previous x as the end of the dropout
                            fieldDropouts[sourceNo].startx.append(doStart);
                            fieldDropouts[sourceNo].endx.append(x - 1);
                            fieldDropouts[sourceNo].fieldLine.append(doFieldLine);
                        }
                    }
                } else {
                    // Current X is a dropout
                    if (doCounter == 0) {
                        doCounter = minimumDetectLength;
                        doStart = x;
                        doFieldLine = y + 1;
                    }
                }
            }

            // Ensure metadata dropouts end at the end of the active video area
            if (doCounter > 0) {
                doCounter = 0;

                fieldDropouts[sourceNo].startx.append(doStart);
                fieldDropouts[sourceNo].endx.append(areaEnd);
                fieldDropouts[sourceNo].fieldLine.append(doFieldLine);
            }

        } // Next source
    } // Next line

    return fieldDropouts;
}

// Method to concatenate dropouts on the same line that are close together
// (to cut down on the amount of generated metadata with noisy/bad sources)
void DiffDod::concatenateFieldDropouts(QVector<LdDecodeMetaData::DropOuts> &dropouts,
                                          QVector<qint32> availableSourcesForFrame)
{
    // This variable controls the minimum allowed gap between dropouts
    // if the gap between the end of the last dropout and the start of
    // the next is less than minimumGap, the two dropouts will be
    // concatenated together
    qint32 minimumGap = 50;

    for (qint32 sourcePointer = 0; sourcePointer < availableSourcesForFrame.size(); sourcePointer++) {
        qint32 sourceNo = availableSourcesForFrame[sourcePointer]; // Get the actual source

        // Start from 1 as 0 has no previous dropout
        qint32 i = 1;
        while (i < dropouts[sourceNo].startx.size()) {
            // Is the current dropout on the same field line as the last?
            if (dropouts[sourceNo].fieldLine[i - 1] == dropouts[sourceNo].fieldLine[i]) {
                if ((dropouts[sourceNo].endx[i - 1] + minimumGap) > (dropouts[sourceNo].startx[i])) {
                    // Concatenate
                    dropouts[sourceNo].endx[i - 1] = dropouts[sourceNo].endx[i];

                    // Remove the current dropout
                    dropouts[sourceNo].startx.removeAt(i);
                    dropouts[sourceNo].endx.removeAt(i);
                    dropouts[sourceNo].fieldLine.removeAt(i);
                }
            }

            // Next dropout
            i++;
        }
    }
}

// Method to find the median of a vector of qint32s
qint32 DiffDod::median(QVector<qint32> v)
{
    size_t n = v.size() / 2;
    std::nth_element(v.begin(), v.begin()+n, v.end());
    return v[n];
}

// Method to convert a linear IRE to a logarithmic reflective brightness %
// Note: Follows the Rec. 709 OETF transfer function
float DiffDod::convertLinearToBrightness(quint16 value, quint16 black16bIre, quint16 white16bIre, bool isSourcePal)
{
    float v = 0;
    float l = static_cast<float>(value);

    // Factors to scale Y according to the black to white interval
    // (i.e. make the black level 0 and the white level 65535)
    float yScale = (1.0 / (black16bIre - white16bIre)) * -65535;

    if (!isSourcePal) {
        // NTSC uses a 75% white point; so here we scale the result by
        // 25% (making 100 IRE 25% over the maximum allowed white point)
        yScale *= 125.0 / 100.0;
    }

    // Scale the L to 0-65535 where 0 = blackIreLevel and 65535 = whiteIreLevel
    l = (l - black16bIre) * yScale;
    if (l > 65535) l = 65535;
    if (l < 0) l = 0;

    // Scale L to 0.00-1.00
    l = (1.0 / 65535.0) * l;

    // Rec. 709 - https://en.wikipedia.org/wiki/Rec._709#Transfer_characteristics
    if (l < 0.018) {
        v = 4.500 * l;
    } else {
        v = pow(1.099 * l, 0.45) - 0.099;
    }

    return v;
}

















