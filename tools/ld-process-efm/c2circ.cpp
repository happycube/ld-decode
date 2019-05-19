/************************************************************************

    c2circ.cpp

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

#include "c2circ.h"

C2Circ::C2Circ()
{
    interleavedC2Data.resize(28);
    interleavedC2Errors.resize(28);

    outputC2Data.resize(28);
    outputC2Errors.resize(28);

    flush();

    c2Passed = 0;
    c2Corrected = 0;
    c2Failed = 0;
    c2flushed = 0;
}

// Method to write status information to qInfo
void C2Circ::reportStatus(void)
{
    qInfo() << "C2 Level error correction:";
    qInfo() << "  Total number of C2s processed =" << c2Passed + c2Corrected + c2Failed;
    qInfo() << "  of which" << c2Passed + c2Corrected << "passed and" << c2Failed << "failed";
    qInfo() << "  The C2 error correction recovered" << c2Corrected << "corrupt C2s";
    qInfo() << "  The delay buffer was flushed" << c2flushed << "times";
}

void C2Circ::pushC1(QByteArray dataSymbols, QByteArray errorSymbols)
{
    // Create a new C1 element and append it to the C1 delay buffer
    C1Element newC1Element;
    newC1Element.c1Data = dataSymbols;
    newC1Element.c1Error = errorSymbols;
    c1DelayBuffer.append(newC1Element);

    if (c1DelayBuffer.size() >= 109) {
        // Maintain the C1 delay buffer at 109 elements maximum
        if (c1DelayBuffer.size() > 109) c1DelayBuffer.removeFirst();

        // Interleave the C1 data and perform C2 error correction
        interleave();
        errorCorrect();
    }
}

// Return the C2 data symbols if available
QByteArray C2Circ::getDataSymbols(void)
{
    if (c1DelayBuffer.size() >= 109) return outputC2Data;
    return QByteArray();
}

// Return the C2 error symbols if available
QByteArray C2Circ::getErrorSymbols(void)
{
    if (c1DelayBuffer.size() >= 109) return outputC2Errors;
    return QByteArray();
}

// Method to flush the C2 buffers
void C2Circ::flush(void)
{
    c1DelayBuffer.clear();

    interleavedC2Data.fill(0);
    interleavedC2Errors.fill(0);

    outputC2Data.fill(0);
    outputC2Errors.fill(0);

    c2flushed++;
}

// Interleave the C1 data by applying delay lines of unequal length
// according to fig. 13 in IEC 60908 in order to produce the C2 data
void C2Circ::interleave(void)
{
    // Longest delay is 27 * 4 = 108
    for (qint32 byteC = 0; byteC < 28; byteC++) {

        qint32 delayC1Line = (108 - ((27 - byteC) * 4));
        interleavedC2Data[byteC] = c1DelayBuffer[delayC1Line].c1Data[byteC];
        interleavedC2Errors[byteC] = c1DelayBuffer[delayC1Line].c1Error[byteC];
    }
}

// Perform a C2 level error check and correction
void C2Circ::errorCorrect(void)
{
    // Convert the data and errors into the form expected by the ezpwd library
    std::vector<uint8_t> data;
    std::vector<int> erasures;
    data.resize(32);

    for (qint32 byteC = 0; byteC < 28; byteC++) {
        data[static_cast<size_t>(byteC)] = static_cast<uchar>(interleavedC2Data[byteC]);
        if (interleavedC2Errors[byteC] == static_cast<char>(1)) erasures.push_back(byteC);
    }

    // Perform error check and correction
    int fixed = -1;
    if (erasures.size() > 4 ) erasures.clear();

    // Initialise the error corrector
    C2RS<255,255-4> rs; // Up to 251 symbols data load with 4 symbols parity RS(32,28)

    // Perform decode
    std::vector<int> position;
    fixed = rs.decode(data, erasures, &position);

    // Copy the result back to the output byte array
    for (qint32 byteC = 0; byteC < 28; byteC++) {
        outputC2Data[byteC] = static_cast<char>(data[static_cast<size_t>(byteC)]);
        if (fixed < 0) outputC2Errors[byteC] = 1; else outputC2Errors[byteC] = 0;
    }

    // Update the statistics
    if (fixed == 0) c2Passed++;
    if (fixed > 0)  c2Corrected++;
    if (fixed < 0)  c2Failed++;
}
