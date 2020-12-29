/************************************************************************

    stacker.cpp

    ld-disc-stacker - Disc stacking for ld-decode
    Copyright (C) 2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-disc-stacker is free software: you can redistribute it and/or
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

#include "stacker.h"
#include "stackingpool.h"

Stacker::Stacker(QAtomicInt& _abort, StackingPool& _stackingPool, QObject *parent)
    : QThread(parent), abort(_abort), stackingPool(_stackingPool)
{
}

void Stacker::run()
{
    // Variables for getInputFrame
    qint32 frameNumber;
    QVector<qint32> firstFieldSeqNo;
    QVector<qint32> secondFieldSeqNo;
    QVector<SourceVideo::Data> firstSourceField;
    QVector<SourceVideo::Data> secondSourceField;
    QVector<LdDecodeMetaData::Field> firstFieldMetadata;
    QVector<LdDecodeMetaData::Field> secondFieldMetadata;
    bool reverse;
    bool noDiffDod;
    QVector<qint32> availableSourcesForFrame;

    while(!abort) {
        // Get the next field to process from the input file
        if (!stackingPool.getInputFrame(frameNumber, firstFieldSeqNo, firstSourceField, firstFieldMetadata,
                                       secondFieldSeqNo, secondSourceField, secondFieldMetadata,
                                       videoParameters, reverse, noDiffDod,
                                       availableSourcesForFrame)) {
            // No more input fields -- exit
            break;
        }

        // Initialise the output fields and process sources to output
        SourceVideo::Data outputFirstField(firstSourceField[0].size());
        SourceVideo::Data outputSecondField(secondSourceField[0].size());
        DropOuts outputFirstFieldDropOuts;
        DropOuts outputSecondFieldDropOuts;

        stackField(firstSourceField, videoParameters[0], firstFieldMetadata, availableSourcesForFrame, noDiffDod, outputFirstField, outputFirstFieldDropOuts);
        stackField(secondSourceField, videoParameters[0], secondFieldMetadata, availableSourcesForFrame, noDiffDod, outputSecondField, outputSecondFieldDropOuts);

        // Return the processed fields
        stackingPool.setOutputFrame(frameNumber, outputFirstField, outputSecondField,
                                    firstFieldSeqNo[0], secondFieldSeqNo[0],
                                    outputFirstFieldDropOuts, outputSecondFieldDropOuts);
    }
}

// Method to stack fields
void Stacker::stackField(QVector<SourceVideo::Data> inputFields,
                                      LdDecodeMetaData::VideoParameters videoParameters,
                                      QVector<LdDecodeMetaData::Field> fieldMetadata,
                                      QVector<qint32> availableSourcesForFrame,
                                      bool noDiffDod,
                                      SourceVideo::Data &outputField,
                                      DropOuts &dropOuts)
{
    quint16 prevGoodValue = 0;

    for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
        for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
            // Get the input values from the input sources
            QVector<quint16> inputValues;
            for (qint32 i = 0; i < availableSourcesForFrame.size(); i++) {
                // Include the source's pixel data if it's not marked as a dropout
                if (!isDropout(fieldMetadata[availableSourcesForFrame[i]].dropOuts, x, y)) {
                    // Pixel is valid
                    inputValues.append(inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * y) + x]);
                }
            }

            // If there are 3 or less available values from 3 or more available sources, use
            // differential dropout detection to check for ld-decode false-positive dropout detection.
            if ((inputValues.size() <= 3) && (availableSourcesForFrame.size() > 3) && (noDiffDod == false)) {
                // Only 3 or less input values; perform differential dropout detection to verify
                // that all available input pixels are really dropouts

                // Clear the current input values and recreate the list including marked dropouts
                inputValues.clear();
                for (qint32 i = 0; i < availableSourcesForFrame.size(); i++) {
                    inputValues.append(inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * y) + x]);
                }

                // DiffDod the list
                DiffDod diffDod;
                inputValues = diffDod.process(inputValues);
            }

            // Stack with intelligence:
            // If there are 3 or more sources - median (with central average for non-odd source sets)
            // If there are 2 sources - average
            // If there is 1 source - output as is
            // If there are zero sources - mark as a dropout in the output file
            if (inputValues.size() > 2) {
                // Store the median in the output field
                outputField[(videoParameters.fieldWidth * y) + x] = median(inputValues);
                prevGoodValue = outputField[(videoParameters.fieldWidth * y) + x];
            } else {
                if (inputValues.size() == 0) {
                    // No values available - use the previous good value
                    outputField[(videoParameters.fieldWidth * y) + x] = prevGoodValue;

                    // Mark as a dropout (unless the error is in the sync region)
                    if (x > videoParameters.colourBurstStart) dropOuts.append(x, x, y + 1);
                } else if (inputValues.size() == 1) {
                    // 1 value available - just copy it to the output
                    outputField[(videoParameters.fieldWidth * y) + x] = inputValues[0];
                    prevGoodValue = outputField[(videoParameters.fieldWidth * y) + x];
                } else {
                    // 2 values available - average and copy to output
                    // Use floating point for accuracy
                    double avg = (static_cast<double>(inputValues[0]) + static_cast<double>(inputValues[1])) / 2.0;
                    outputField[(videoParameters.fieldWidth * y) + x] = static_cast<quint16>(avg);
                    prevGoodValue = outputField[(videoParameters.fieldWidth * y) + x];
                }
            }
        }
    }

    // Cat the dropouts
    if (dropOuts.size() != 0) dropOuts.concatenate();
}

// Method to find the median of a vector of quint16s
quint16 Stacker::median(QVector<quint16> v)
{
    size_t n = v.size() / 2;
    std::nth_element(v.begin(), v.begin()+n, v.end());

    // If set of input numbers is odd return the
    // centre value
    if (v.size() % 2 != 0) return v[n];

    // If set of input number is even, average the
    // two centre values and return
    quint16 val1 = v[(v.size() - 1) / 2];
    quint16 val2 = v[n];

    double avg = (static_cast<double>(val1) + static_cast<double>(val2)) / 2.0;

    return static_cast<quint16>(avg);
    //return (v[(v.size() - 1) / 2] + v[n]) / 2;
}

// Method returns true if specified pixel is a dropout
bool Stacker::isDropout(DropOuts dropOuts, qint32 fieldX, qint32 fieldY)
{
    for (qint32 i = 0; i < dropOuts.size(); i++) {
        if ((dropOuts.fieldLine(i) - 1) == fieldY) {
            if ((fieldX >= dropOuts.startx(i)) && (fieldX <= dropOuts.endx(i)))
                return true;
        }
    }

    return false;
}
