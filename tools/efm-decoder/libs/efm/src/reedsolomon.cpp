/************************************************************************

    reedsolomon.cpp

    EFM-library - Reed-Solomon CIRC functions
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

#include "ezpwd/rs_base"
#include "ezpwd/rs"
#include "reedsolomon.h"

// ezpwd C1 ECMA-130 CIRC configuration
template <size_t SYMBOLS, size_t PAYLOAD>
struct C1RS;
template <size_t PAYLOAD>
struct C1RS<255, PAYLOAD> : public __RS(C1RS, quint8, 255, PAYLOAD, 0x11D, 0, 1, false);

C1RS<255, 255 - 4> c1rs;

// ezpwd C2 ECMA-130 CIRC configuration
template <size_t SYMBOLS, size_t PAYLOAD>
struct C2RS;
template <size_t PAYLOAD>
struct C2RS<255, PAYLOAD> : public __RS(C2RS, quint8, 255, PAYLOAD, 0x11D, 0, 1, false);

C2RS<255, 255 - 4> c2rs;

ReedSolomon::ReedSolomon()
{
    // Initialise statistics
    m_validC1s = 0;
    m_fixedC1s = 0;
    m_errorC1s = 0;

    m_validC2s = 0;
    m_fixedC2s = 0;
    m_errorC2s = 0;
}

// Perform a C1 Reed-Solomon decoding operation on the input data
// This is a (32,28) Reed-Solomon encode - 32 bytes in, 28 bytes out
void ReedSolomon::c1Decode(QVector<quint8> &inputData, QVector<bool> &errorData,
    QVector<bool> &paddedData, bool m_showDebug)
{
    // Ensure input data is 32 bytes long
    if (inputData.size() != 32) {
        qFatal("ReedSolomon::c1Decode - Input data must be 32 bytes long");
    }

    // Just reformat the padded data
    paddedData = QVector<bool>(paddedData.begin(), paddedData.end() - 4);

    // Convert the QVector to a std::vector for the ezpwd library
    std::vector<quint8> tmpData(inputData.begin(), inputData.end());
    std::vector<int> erasures;
    std::vector<int> position;

    // Convert the errorData into a list of erasure positions
    for (int index = 0; index < errorData.size(); ++index) {
        if (errorData[index])
            erasures.push_back(index);
    }

    if (erasures.size() > 2) {
        // If there are more than 2 erasures, then we can't correct the data - copy the input data
        // to the output data and flag it with errors
        // if (m_showDebug)
        //     qDebug() << "ReedSolomon::c1Decode - Too many erasures to correct";
        inputData = QVector<quint8>(tmpData.begin(), tmpData.end() - 4);
        errorData.resize(inputData.size());
        errorData.fill(true);
        ++m_errorC1s;
        return;
    }

    // Decode the data
    int result = c1rs.decode(tmpData, erasures, &position);
    if (result > 2) result = -1;

    // Convert the std::vector back to a QVector and strip the parity bytes
    inputData = QVector<quint8>(tmpData.begin(), tmpData.end() - 4);
    errorData.resize(inputData.size());

    // If result >= 0, then the Reed-Solomon decode was successful
    if (result >= 0) {
        // Mark all the data as correct
        errorData.fill(false);

        if (result == 0)
            ++m_validC1s;
        else
            ++m_fixedC1s;
        return;
    }

    // If result < 0, the Reed-Solomon decode completely failed and the data is corrupt
    // if (m_showDebug) qDebug() << "ReedSolomon::c1Decode - C1 corrupt and could not be fixed";

    // Mark all the data as corrupt
    errorData.fill(true);
    ++m_errorC1s;

    return;
}

// Perform a C2 Reed-Solomon decoding operation on the input data
// This is a (28,24) Reed-Solomon encode - 28 bytes in, 24 bytes out
void ReedSolomon::c2Decode(QVector<quint8> &inputData, QVector<bool> &errorData,
    QVector<bool> &paddedData, bool m_showDebug)
{
    // Ensure input data is 28 bytes long
    if (inputData.size() != 28) {
        qFatal("ReedSolomon::c2Decode - Input data must be 28 bytes long");
    }

    if (errorData.size() != 28) {
        qFatal("ReedSolomon::c2Decode - Error data must be 28 bytes long");
    }

    // Just reformat the padded data
    paddedData = QVector<bool>(paddedData.begin(), paddedData.begin() + 12)
        + QVector<bool>(paddedData.begin() + 16, paddedData.end());

    // Convert the QVector to a std::vector for the ezpwd library
    std::vector<quint8> tmpData(inputData.begin(), inputData.end());
    std::vector<int> position;
    std::vector<int> erasures;

    // Convert the errorData into a list of erasure positions
    for (int index = 0; index < errorData.size(); ++index) {
        if (errorData[index] == true)
            erasures.push_back(index);
    }

    // Since we know the erasure positions, we can correct a maximum of 4 errors.  If the number
    // of know input erasures is greater than 4, then we can't correct the data.
    if (erasures.size() > 4) {
        // If there are more than 4 erasures, then we can't correct the data - copy the input data
        // to the output data and flag it with errors
        // if (m_showDebug)
        //     qDebug().noquote() << "ReedSolomon::c2Decode - Too many erasures to correct";
        inputData = QVector<quint8>(tmpData.begin(), tmpData.begin() + 12)
                + QVector<quint8>(tmpData.begin() + 16, tmpData.end());
        errorData.resize(inputData.size());
        
        // Set the error data
        errorData.fill(true);

        ++m_errorC2s;
        return;
    }

    // Decode the data
    int result = c2rs.decode(tmpData, erasures, &position);
    if (result > 2) result = -1;

    // Convert the std::vector back to a QVector and remove the parity bytes
    // by copying bytes 0-11 and 16-27 to the output data
    inputData = QVector<quint8>(tmpData.begin(), tmpData.begin() + 12)
            + QVector<quint8>(tmpData.begin() + 16, tmpData.end());
    errorData.resize(inputData.size());

    // If result >= 0, then the Reed-Solomon decode was successful
    if (result >= 0) {
        // Clear the error data
        errorData.fill(false);

        if (result == 0)
            ++m_validC2s;
        else
            ++m_fixedC2s;
        return;
    }

    // If result < 0, then the Reed-Solomon decode failed and the data should be flagged as corrupt
    // if (m_showDebug)
    //     qDebug().noquote() << "ReedSolomon::c2Decode - C2 corrupt and could not be fixed"
    //                        << result;
    
    // Set the error data
    errorData.fill(true);

    ++m_errorC2s;
    return;
}

// Getter functions for the statistics
qint32 ReedSolomon::validC1s()
{
    return m_validC1s;
}

qint32 ReedSolomon::fixedC1s()
{
    return m_fixedC1s;
}

qint32 ReedSolomon::errorC1s()
{
    return m_errorC1s;
}

qint32 ReedSolomon::validC2s()
{
    return m_validC2s;
}

qint32 ReedSolomon::fixedC2s()
{
    return m_fixedC2s;
}

qint32 ReedSolomon::errorC2s()
{
    return m_errorC2s;
}