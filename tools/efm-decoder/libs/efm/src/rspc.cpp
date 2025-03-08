/************************************************************************

    rspc.cpp

    EFM-library - Reed-Solomon Product-like Code (RSPC) functions
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
#include "rspc.h"

// ECMA-130 Q and P specific CIRC configuration for Reed-Solomon forward error correction
template < size_t SYMBOLS, size_t PAYLOAD > struct QRS;
template < size_t PAYLOAD > struct QRS<255, PAYLOAD>
    : public __RS(QRS, uint8_t, 255, PAYLOAD, 0x11d, 0, 1, false);

template < size_t SYMBOLS, size_t PAYLOAD > struct PRS;
template < size_t PAYLOAD > struct PRS<255, PAYLOAD>
    : public __RS(PRS, uint8_t, 255, PAYLOAD, 0x11d, 0, 1, false);

Rspc::Rspc()
{}

void Rspc::qParityEcc(QByteArray &inputData, QByteArray &errorData, bool m_showDebug)
{
    // Initialise the RS error corrector
    QRS<255,255-2> qrs; // Up to 251 symbols data load with 2 symbols parity RS(45,43)

    // Keep track of the number of successful corrections
    qint32 successfulCorrections = 0;

    // RS code is Q(45,43)
    // There are 104 bytes of Q-Parity (52 code words)
    // Each Q field covers 12 to 2248 = 2236 bytes (2 * 1118)
    // 2236 / 43 = 52 Q-parity words (= 104 Q-parity bytes)
    //
    // Calculations are based on ECMA-130 Annex A

    uchar* uF1Data = reinterpret_cast<uchar*>(inputData.data());
    uchar* uF1Erasures = reinterpret_cast<uchar*>(errorData.data());

    // Ignore the 12 sync bytes
    uF1Data += 12;
    uF1Erasures += 12;

    // Store the data and erasures in the form expected by the ezpwd library
    std::vector<uchar> qField;
    std::vector<int> qFieldErasures;
    qField.resize(45); // 43 + 2 parity bytes = 45

    // evenOdd = 0 = LSBs / evenOdd = 1 = MSBs
    for (qint32 evenOdd = 0; evenOdd < 2; evenOdd++) {
        for (qint32 Nq = 0; Nq < 26; Nq++) {
            qFieldErasures.clear();
            for (qint32 Mq = 0; Mq < 43; Mq++) {
                // Get 43 byte codeword location
                qint32 Vq = 2 * ((44 * Mq + 43 * Nq) % 1118) + evenOdd;
                qField[static_cast<size_t>(Mq)] = uF1Data[Vq];

                // Get codeword erasures if present
                if (uF1Erasures[Vq] == 1) qFieldErasures.push_back(Mq);
            }
            // Get 2 byte parity location
            qint32 qParityByte0 = 2 * ((43 * 26 + Nq) % 1118) + evenOdd;
            qint32 qParityByte1 = 2 * ((44 * 26 + Nq) % 1118) + evenOdd;

            // Note: Q-Parity data starts at 12 + 2236
            qField[43] = uF1Data[qParityByte0 + 2236];
            qField[44] = uF1Data[qParityByte1 + 2236];

            // Perform RS decode/correction
            if (qFieldErasures.size() > 2) qFieldErasures.clear();
            std::vector<int> position;
            int fixed = -1;
            fixed = qrs.decode(qField, qFieldErasures, &position);

            // If correction was successful add to success counter
            // and copy back the corrected data
            if (fixed >= 0) {
                successfulCorrections++;

                // Here we use the calculation in reverse to put the corrected
                // data back into it's original position
                for (qint32 Mq = 0; Mq < 43; Mq++) {
                    qint32 Vq = 2 * ((44 * Mq + 43 * Nq) % 1118) + evenOdd;
                    uF1Data[Vq] = qField[static_cast<size_t>(Mq)];
                }
            }
        }
    }

    // Reset the pointers
    uF1Data -= 12;
    uF1Erasures -= 12;

    // Show Q-Parity correction result to debug
    if (successfulCorrections >= 52) {
        //if (m_showDebug) qDebug() << "Rspc::qParityEcc(): Q-Parity correction successful with" << successfulCorrections << "corrected codewords";
    } else {
        if (m_showDebug) qDebug() << "Rspc::qParityEcc(): Q-Parity correction failed! Got" << successfulCorrections << "correct out of 52 possible codewords";
    }
}

void Rspc::pParityEcc(QByteArray &inputData, QByteArray &errorData, bool m_showDebug)
{
    // Initialise the RS error corrector
    PRS<255,255-2> prs; // Up to 251 symbols data load with 2 symbols parity RS(26,24)

    // Keep track of the number of successful corrections
    qint32 successfulCorrections = 0;

    uchar* uF1Data = reinterpret_cast<uchar*>(inputData.data());
    uchar* uF1Erasures = reinterpret_cast<uchar*>(errorData.data());

    // RS code is P(26,24)
    // There are 172 bytes of P-Parity (86 code words)
    // Each P field covers 12 to 2076 = 2064 bytes (2 * 1032)
    // 2064 / 24 = 86 P-parity words (= 172 P-parity bytes)
    //
    // Calculations are based on ECMA-130 Annex A

    // Ignore the 12 sync bytes
    uF1Data += 12;
    uF1Erasures += 12;

    // Store the data and erasures in the form expected by the ezpwd library
    std::vector<uchar> pField;
    std::vector<int> pFieldErasures;
    pField.resize(26); // 24 + 2 parity bytes = 26

    // evenOdd = 0 = LSBs / evenOdd = 1 = MSBs
    for (qint32 evenOdd = 0; evenOdd < 2; evenOdd++) {
        for (qint32 Np = 0; Np < 43; Np++) {
            pFieldErasures.clear();
            for (qint32 Mp = 0; Mp < 26; Mp++) {
                // Get 24 byte codeword location + 2 P-parity bytes
                qint32 Vp = 2 * (43 * Mp + Np) + evenOdd;
                pField[static_cast<size_t>(Mp)] = uF1Data[Vp];

                // Get codeword erasures if present
                if (uF1Erasures[Vp] == 1) pFieldErasures.push_back(Mp);
            }

            // Perform RS decode/correction
            if (pFieldErasures.size() > 2) pFieldErasures.clear();
            std::vector<int> position;
            int fixed = -1;

            fixed = prs.decode(pField, pFieldErasures, &position);

            // If correction was successful add to success counter
            // and copy back the corrected data
            if (fixed >= 0) {
                successfulCorrections++;

                // Here we use the calculation in reverse to put the corrected
                // data back into it's original position
                for (qint32 Mp = 0; Mp < 24; Mp++) {
                    qint32 Vp = 2 * (43 * Mp + Np) + evenOdd;
                    uF1Data[Vp] = pField[static_cast<size_t>(Mp)];
                }
            }
        }
    }

    // Reset the pointers
    uF1Data -= 12;
    uF1Erasures -= 12;

    // Show P-Parity correction result to debug
    if (successfulCorrections >= 86) {
        //if (m_showDebug) qDebug() << "Rspc::pParityEcc(): P-Parity correction successful with" << successfulCorrections << "corrected codewords";
    } else {
        if (m_showDebug) qDebug() << "Rspc::pParityEcc(): P-Parity correction failed! Got" << successfulCorrections << "correct out of 86 possible codewords";
    }
}