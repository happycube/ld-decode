/************************************************************************

    filters.cpp

    ld-decode-tools TBC library
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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

#include "filters.h"

// Apply a FIR filter to remove PAL chroma leaving just luma
// Accepts quint16 greyscale data and returns the filtered data into
// the same array
void Filters::palLumaFirFilter(quint16 *data, qint32 dataPoints)
{
    // Convert the quint16 data to double
    QVector<double> floatData(dataPoints);
    for (qint32 i = 0; i < dataPoints; i++) {
        floatData[i] = static_cast<double>(data[i]);
    }

    palLumaFirFilterDouble(floatData);

    // Convert the double data back to quint16
    for (qint32 i = 0; i < dataPoints; i++) {
        data[i] = static_cast<quint16>(floatData[i]);
    }
}

// Apply a FIR filter to remove PAL chroma leaving just luma
// Accepts qint32 greyscale data and returns the filtered data into
// the same array
void Filters::palLumaFirFilter(QVector<qint32> &data)
{
    // Convert the qint32 data to double
    QVector<double> floatData(data.size());
    for (qint32 i = 0; i < data.size(); i++) {
        floatData[i] = static_cast<double>(data[i]);
    }

    palLumaFirFilterDouble(floatData);

    // Convert the double data back to qint32
    for (qint32 i = 0; i < data.size(); i++) {
        data[i] = static_cast<qint32>(floatData[i]);
    }
}

// Apply a FIR filter to remove NTSC chroma leaving just luma
// Accepts quint16 greyscale data and returns the filtered data into
// the same array
void Filters::ntscLumaFirFilter(quint16 *data, qint32 dataPoints)
{
    // Convert the quint16 data to double
    QVector<double> floatData(dataPoints);
    for (qint32 i = 0; i < dataPoints; i++) {
        floatData[i] = static_cast<double>(data[i]);
    }

    ntscLumaFirFilterDouble(floatData);

    // Convert the double data back to quint16
    for (qint32 i = 0; i < dataPoints; i++) {
        data[i] = static_cast<quint16>(floatData[i]);
    }
}

// Apply a FIR filter to remove NTSC chroma leaving just luma
// Accepts qint32 greyscale data and returns the filtered data into
// the same array
void Filters::ntscLumaFirFilter(QVector<qint32> &data)
{
    // Convert the qint32 data to double
    QVector<double> floatData(data.size());
    for (qint32 i = 0; i < data.size(); i++) {
        floatData[i] = static_cast<double>(data[i]);
    }

    ntscLumaFirFilterDouble(floatData);

    // Convert the double data back to qint32
    for (qint32 i = 0; i < data.size(); i++) {
        data[i] = static_cast<qint32>(floatData[i]);
    }
}

// Private methods ----------------------------------------------------------------------------------------------------
void Filters::palLumaFirFilterDouble(QVector<double> &floatData)
{
    // PAL - Filter at Fsc/2 (Fsc = 4433618 (/2 = 2,216,809), sample rate = 17,734,472)
    // 2.2 MHz LPF - 9 Taps
    // scipy.signal.firwin(9, [2.2e6/17734472], window='hamming')
    double filter[9] = {
        0.01251067,  0.04121379,  0.11872117,  0.20565387,  0.24380102,
        0.20565387,  0.11872117,  0.04121379,  0.01251067
    };
    qint32 filterSize = 9;

    const qint32 dataSize = floatData.size();
    QVector<double> tmp(dataSize);

    for (qint32 i = 0; i < dataSize; i++) {
        double v = 0.0;
        for (qint32 j = 0, k = i - (filterSize / 2); j < filterSize; j++, k++) {
            // Assume data is 0 outside the vector bounds
            if (k >= 0 && k < dataSize) {
                v += filter[j] * floatData[k];
            }
        }
        tmp[i] = v;
    }

    floatData = tmp;
}

// Apply a FIR filter to remove NTSC chroma leaving just luma
// Accepts quint16 greyscale data and returns the filtered data into
// the same array
void Filters::ntscLumaFirFilterDouble(QVector<double> &floatData)
{
    // NTSC - Filter at Fsc/2 (Fsc = 3579545 (/2 = 1,789,772.5), sample rate = 14,318,180)
    // 1.8 MHz LPF - 9 Taps
    // signal.firwin(9, [1.8e6/14318180], window='hamming')
    double filter[9] = {
        0.0123685 ,  0.04101026,  0.11860244,  0.20589257,  0.24425247,
        0.20589257,  0.11860244,  0.04101026,  0.0123685
    };
    qint32 filterSize = 9;

    const qint32 dataSize = floatData.size();
    QVector<double> tmp(dataSize);

    for (qint32 i = 0; i < dataSize; i++) {
        double v = 0.0;
        for (qint32 j = 0, k = i - (filterSize / 2); j < filterSize; j++, k++) {
            // Assume data is 0 outside the vector bounds
            if (k >= 0 && k < dataSize) {
                v += filter[j] * floatData[k];
            }
        }
        tmp[i] = v;
    }

    floatData = tmp;
}
