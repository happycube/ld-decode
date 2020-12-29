/************************************************************************

    diffdod.cpp

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

#include "diffdod.h"

DiffDod::DiffDod()
{

}

// Use differential dropout detection to remove suspected dropout error
// values from inputValues to produce the set of output values
QVector<quint16> DiffDod::process(QVector<quint16> inputValues)
{
    QVector<quint16> outputValues;

    // Get the median value of the input values
    double medianValue = static_cast<double>(median(inputValues));

    // Set the matching threshold to +-10% of the median value
    double threshold = 10; // %

    // Set the maximum and minimum values for valid inputs
    double maxValueD = medianValue + ((medianValue / 100.0) * threshold);
    double minValueD = medianValue - ((medianValue / 100.0) * threshold);
    if (minValueD < 0) minValueD = 0;
    if (maxValueD > 65535) maxValueD = 65535;
    quint16 minValue = minValueD;
    quint16 maxValue = maxValueD;

    // Copy valid input values to the output set
    for (qint32 i = 0; i < inputValues.size(); i++) {
        if ((inputValues[i] > minValue) && (inputValues[i] < maxValue)) {
            outputValues.append(inputValues[i]);
        }
    }

    qDebug() << "DIFFDOD:  Input" << inputValues;
    qDebug() << "DIFFDOD: Output" << outputValues;

    return outputValues;
}

// Method to find the median of a vector of quint16s
quint16 DiffDod::median(QVector<quint16> v)
{
    size_t n = v.size() / 2;
    std::nth_element(v.begin(), v.begin()+n, v.end());

    // If set of input numbers is odd return the
    // centre value
    if (v.size() % 2 != 0) return v[n];

    // If set of input number is even, average the
    // two centre values and return
    return (v[(v.size() - 1) / 2] + v[n]) / 2;
}
