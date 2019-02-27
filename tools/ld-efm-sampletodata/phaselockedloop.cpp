/************************************************************************

    phaselockedloop.cpp

    ld-efm-sampletodata - EFM sample to data processor for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-sampletodata is free software: you can redistribute it and/or
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

// Note: This PLL implementation is based on original code provided to
// the ld-decode project by Olivier “Sarayan” Galibert.  Many thanks
// for the assistance!

#include "phaselockedloop.h"

Pll_t::Pll_t(QVector<qint8> &_result) : result(_result)
{
    // Configuration
    basePeriod = 40000000 / 4321800; // T1 clock period 40MSPS / bit-rate

    minimumPeriod  = basePeriod * 0.75; // -25% minimum
    maximumPeriod  = basePeriod * 1.25; // +25% maximum
    periodAdjustBase = basePeriod * 0.0001; // Clock adjustment step

    // Working parameter defaults
    currentPeriod = basePeriod;
    frequencyHysteresis = 0;
    phaseAdjust = 0;
    refClockTime = 0;
    tCounter = 1;
}

void Pll_t::pushTValue(qint8 bit)
{
    // If this is a 1, push the T delta
    if (bit) {
        result.push_back(tCounter);
        tCounter = 1;
    } else {
        tCounter++;
    }
}

// Called when a ZC happens on a sample number
void Pll_t::pushEdge(qreal sampleDelta)
{
    while(sampleDelta >= refClockTime) {
        qreal next = refClockTime + currentPeriod + phaseAdjust;
        refClockTime = next;

        // Note: the tCounter < 3 check causes an 'edge push' if T is 1 or 2 (which
        // are invalid timing lengths for the NRZI data).  We also 'edge pull' values
        // greater than T11
        if((sampleDelta > next || tCounter < 3) && !(tCounter > 10)) {
            phaseAdjust = 0;
            pushTValue(0);
        } else {
            qreal delta = sampleDelta - (next - currentPeriod / 2.0);
            phaseAdjust = delta * 0.05;

            // Adjust frequency based on error
            if(delta < 0) {
                if(frequencyHysteresis < 0) frequencyHysteresis--;
                else frequencyHysteresis = -1;
            } else if(delta > 0) {
                if(frequencyHysteresis > 0) frequencyHysteresis++;
                else frequencyHysteresis = 1;
            } else  {
                frequencyHysteresis = 0;
            }

            // Update the reference clock?
            if(frequencyHysteresis) {
                qint32 afh = frequencyHysteresis < 0 ? -frequencyHysteresis : frequencyHysteresis;
                if(afh > 1) {
                    qreal aper = periodAdjustBase * delta / currentPeriod;
                    currentPeriod += aper;

                    if (currentPeriod < minimumPeriod) {
                        currentPeriod = minimumPeriod;
                    } else if (currentPeriod > maximumPeriod) {
                        currentPeriod = maximumPeriod;
                    }
                }
            }
            pushTValue(1);
        }
    }

    // Reset refClockTime ready for the next delta but
    // keep any error to maintain accuracy
    refClockTime = (refClockTime - sampleDelta);
}
