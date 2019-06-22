/************************************************************************

    c2deinterleave.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "c2deinterleave.h"

C2Deinterleave::C2Deinterleave()
{
    outputC2Data.resize(24);
    outputC2Errors.resize(24);
    outputC2Valid = false;

    reset();
}

// Method to reset and flush all buffers
void C2Deinterleave::reset(void)
{
    flush();
    resetStatistics();
}

// Methods to handle statistics
void C2Deinterleave::resetStatistics(void)
{
    statistics.validDeinterleavedC2s = 0;
    statistics.invalidDeinterleavedC2s = 0;
    statistics.c2flushed = 0;
}

C2Deinterleave::Statistics C2Deinterleave::getStatistics(void)
{
    return statistics;
}

// Method to write status information to qInfo
void C2Deinterleave::reportStatus(void)
{
    qInfo() << "C2 Deinterleave:";
    qInfo() << "  Total number of C2s processed =" << statistics.validDeinterleavedC2s + statistics.invalidDeinterleavedC2s;
    qInfo() << "  of which" << statistics.validDeinterleavedC2s << "were valid and" << statistics.invalidDeinterleavedC2s << "were invalid";
    qInfo() << "  The delay buffer was flushed" << statistics.c2flushed << "times";
}

void C2Deinterleave::pushC2(QByteArray dataSymbols, QByteArray errorSymbols, bool dataValid)
{
    // Create a new C2 element and append it to the C2 delay buffer
    C2Element newC2Element;
    newC2Element.c2Data = dataSymbols;
    newC2Element.c2Error = errorSymbols;
    newC2Element.c2DataValid = dataValid;
    c2DelayBuffer.append(newC2Element);

    if (c2DelayBuffer.size() >= 3) {
        // Maintain the C2 delay buffer at 3 elements maximum
        if (c2DelayBuffer.size() > 3) c2DelayBuffer.removeFirst();

        // Deinterleave the C2 data
        deinterleave();
    }
}

// Return the deinterleaved C2 data symbols if available
QByteArray C2Deinterleave::getDataSymbols(void)
{
    if (c2DelayBuffer.size() >= 3) return outputC2Data;
    return QByteArray();
}

// Return the deinterleaved C2 error symbols if available
QByteArray C2Deinterleave::getErrorSymbols(void)
{
    if (c2DelayBuffer.size() >= 3) return outputC2Errors;
    return QByteArray();
}

// Return the deinterleaved C2 data valid flag if available
bool C2Deinterleave::getDataValid(void)
{
    if (c2DelayBuffer.size() >= 3) return outputC2Valid;
    return false;
}

// Method to flush the C1 buffers
void C2Deinterleave::flush(void)
{
    c2DelayBuffer.clear();

    outputC2Data.fill(0);
    outputC2Errors.fill(0);
    outputC2Valid = false;

    statistics.c2flushed++;
}

// Deinterleave C2 data as per IEC60908 Figure 13 - CIRC decoder (de-interleaving sequence)
void C2Deinterleave::deinterleave(void)
{
    // Element 2 is the current C2, element 0 is 2 line delays behind
    qint32 curr = 2; // C2 0-frame delay
    qint32 prev = 0; // C2 2=frame delay

    // Check that both required C2 symbols contain valid data
    if (c2DelayBuffer[curr].c2DataValid && c2DelayBuffer[prev].c2DataValid) {
        statistics.validDeinterleavedC2s++;
        outputC2Valid = true;
    } else {
        statistics.invalidDeinterleavedC2s++;
        outputC2Valid = false;
    }

    // Deinterleave data
    outputC2Data[ 0] = c2DelayBuffer[curr].c2Data[ 0];
    outputC2Data[ 1] = c2DelayBuffer[curr].c2Data[ 1];
    outputC2Data[ 2] = c2DelayBuffer[curr].c2Data[ 6];
    outputC2Data[ 3] = c2DelayBuffer[curr].c2Data[ 7];

    outputC2Data[ 8] = c2DelayBuffer[curr].c2Data[ 2];
    outputC2Data[ 9] = c2DelayBuffer[curr].c2Data[ 3];
    outputC2Data[10] = c2DelayBuffer[curr].c2Data[ 8];
    outputC2Data[11] = c2DelayBuffer[curr].c2Data[ 9];

    outputC2Data[16] = c2DelayBuffer[curr].c2Data[ 4];
    outputC2Data[17] = c2DelayBuffer[curr].c2Data[ 5];
    outputC2Data[18] = c2DelayBuffer[curr].c2Data[10];
    outputC2Data[19] = c2DelayBuffer[curr].c2Data[11];

    outputC2Data[ 4] = c2DelayBuffer[prev].c2Data[16];
    outputC2Data[ 5] = c2DelayBuffer[prev].c2Data[17];
    outputC2Data[ 6] = c2DelayBuffer[prev].c2Data[22];
    outputC2Data[ 7] = c2DelayBuffer[prev].c2Data[23];

    outputC2Data[12] = c2DelayBuffer[prev].c2Data[18];
    outputC2Data[13] = c2DelayBuffer[prev].c2Data[19];
    outputC2Data[14] = c2DelayBuffer[prev].c2Data[24];
    outputC2Data[15] = c2DelayBuffer[prev].c2Data[25];

    outputC2Data[20] = c2DelayBuffer[prev].c2Data[20];
    outputC2Data[21] = c2DelayBuffer[prev].c2Data[21];
    outputC2Data[22] = c2DelayBuffer[prev].c2Data[26];
    outputC2Data[23] = c2DelayBuffer[prev].c2Data[27];

    // Deinterleave errors
    outputC2Errors[ 0] = c2DelayBuffer[curr].c2Error[ 0];
    outputC2Errors[ 1] = c2DelayBuffer[curr].c2Error[ 1];
    outputC2Errors[ 2] = c2DelayBuffer[curr].c2Error[ 6];
    outputC2Errors[ 3] = c2DelayBuffer[curr].c2Error[ 7];

    outputC2Errors[ 8] = c2DelayBuffer[curr].c2Error[ 2];
    outputC2Errors[ 9] = c2DelayBuffer[curr].c2Error[ 3];
    outputC2Errors[10] = c2DelayBuffer[curr].c2Error[ 8];
    outputC2Errors[11] = c2DelayBuffer[curr].c2Error[ 9];

    outputC2Errors[16] = c2DelayBuffer[curr].c2Error[ 4];
    outputC2Errors[17] = c2DelayBuffer[curr].c2Error[ 5];
    outputC2Errors[18] = c2DelayBuffer[curr].c2Error[10];
    outputC2Errors[19] = c2DelayBuffer[curr].c2Error[11];

    outputC2Errors[ 4] = c2DelayBuffer[prev].c2Error[16];
    outputC2Errors[ 5] = c2DelayBuffer[prev].c2Error[17];
    outputC2Errors[ 6] = c2DelayBuffer[prev].c2Error[22];
    outputC2Errors[ 7] = c2DelayBuffer[prev].c2Error[23];

    outputC2Errors[12] = c2DelayBuffer[prev].c2Error[18];
    outputC2Errors[13] = c2DelayBuffer[prev].c2Error[19];
    outputC2Errors[14] = c2DelayBuffer[prev].c2Error[24];
    outputC2Errors[15] = c2DelayBuffer[prev].c2Error[25];

    outputC2Errors[20] = c2DelayBuffer[prev].c2Error[20];
    outputC2Errors[21] = c2DelayBuffer[prev].c2Error[21];
    outputC2Errors[22] = c2DelayBuffer[prev].c2Error[26];
    outputC2Errors[23] = c2DelayBuffer[prev].c2Error[27];
}

