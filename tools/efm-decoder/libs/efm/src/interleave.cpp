/************************************************************************

    interleave.cpp

    EFM-library - Data interleaving functions
    Copyright (C) 2025 Simon Inns

    This file is part of EFM-Tools.

    This is free software: you can redistribute it and/or
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

#include "interleave.h"

Interleave::Interleave() { }

void Interleave::deinterleave(QVector<quint8> &inputData, QVector<bool> &inputError, QVector<bool> &inputPadded)
{
    // Ensure input data is 24 bytes long
    if (inputData.size() != 24) {
        qFatal("Interleave::deinterleave - Input data must be 24 bytes long");
    }

    // De-Interleave the input data
    QVector<quint8> outputData(24);
    QVector<bool> outputError(24);
    QVector<bool> outputPadded(24);

    outputData[0] = inputData[0];
    outputData[1] = inputData[1];
    outputData[8] = inputData[2];
    outputData[9] = inputData[3];
    outputData[16] = inputData[4];
    outputData[17] = inputData[5];
    outputData[2] = inputData[6];
    outputData[3] = inputData[7];
    outputData[10] = inputData[8];
    outputData[11] = inputData[9];
    outputData[18] = inputData[10];
    outputData[19] = inputData[11];
    outputData[4] = inputData[12];
    outputData[5] = inputData[13];
    outputData[12] = inputData[14];
    outputData[13] = inputData[15];
    outputData[20] = inputData[16];
    outputData[21] = inputData[17];
    outputData[6] = inputData[18];
    outputData[7] = inputData[19];
    outputData[14] = inputData[20];
    outputData[15] = inputData[21];
    outputData[22] = inputData[22];
    outputData[23] = inputData[23];

    outputError[0] = inputError[0];
    outputError[1] = inputError[1];
    outputError[8] = inputError[2];
    outputError[9] = inputError[3];
    outputError[16] = inputError[4];
    outputError[17] = inputError[5];
    outputError[2] = inputError[6];
    outputError[3] = inputError[7];
    outputError[10] = inputError[8];
    outputError[11] = inputError[9];
    outputError[18] = inputError[10];
    outputError[19] = inputError[11];
    outputError[4] = inputError[12];
    outputError[5] = inputError[13];
    outputError[12] = inputError[14];
    outputError[13] = inputError[15];
    outputError[20] = inputError[16];
    outputError[21] = inputError[17];
    outputError[6] = inputError[18];
    outputError[7] = inputError[19];
    outputError[14] = inputError[20];
    outputError[15] = inputError[21];
    outputError[22] = inputError[22];
    outputError[23] = inputError[23];

    outputPadded[0] = inputPadded[0];
    outputPadded[1] = inputPadded[1];
    outputPadded[8] = inputPadded[2];
    outputPadded[9] = inputPadded[3];
    outputPadded[16] = inputPadded[4];
    outputPadded[17] = inputPadded[5];
    outputPadded[2] = inputPadded[6];
    outputPadded[3] = inputPadded[7];
    outputPadded[10] = inputPadded[8];
    outputPadded[11] = inputPadded[9];
    outputPadded[18] = inputPadded[10];
    outputPadded[19] = inputPadded[11];
    outputPadded[4] = inputPadded[12];
    outputPadded[5] = inputPadded[13];
    outputPadded[12] = inputPadded[14];
    outputPadded[13] = inputPadded[15];
    outputPadded[20] = inputPadded[16];
    outputPadded[21] = inputPadded[17];
    outputPadded[6] = inputPadded[18];
    outputPadded[7] = inputPadded[19];
    outputPadded[14] = inputPadded[20];
    outputPadded[15] = inputPadded[21];
    outputPadded[22] = inputPadded[22];
    outputPadded[23] = inputPadded[23];

    inputData = outputData;
    inputError = outputError;
    inputPadded = outputPadded;
}