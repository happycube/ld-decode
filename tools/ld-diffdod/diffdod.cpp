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

Diffdod::Diffdod(QObject *parent) : QObject(parent)
{

}

bool Diffdod::process(QVector<QString> inputFilenames, bool reverse,
                      qint32 dodThreshold)
{
    // Show input filenames
    qInfo() << "Processing" << inputFilenames.size() << "input TBC files:";
    for (qint32 i = 0; i < inputFilenames.size(); i++) qInfo().nospace() << "  Source #" << i << ": " << inputFilenames[i];

    // And then show the rest...
    if (reverse) qInfo() << "Using reverse field order"; else qInfo() << "Using normal field order";
    qInfo() << "Dropout detection threshold is" << dodThreshold;
    qInfo() << "";

    // Load the input TBC files
    if (!loadInputTbcFiles(inputFilenames, reverse)) {
        qCritical() << "Error: Unable to load input TBC files - cannot continue!";
        return false;
    }

    // Show disc and video information
    qInfo() << "";
    qInfo() << "Sources have VBI frame number range of" << tbcSources.getMinimumVbiFrameNumber() << "to" << tbcSources.getMaximumVbiFrameNumber();

    // Check start and length
    qint32 vbiStartFrame = tbcSources.getMinimumVbiFrameNumber();
    qint32 length = tbcSources.getMaximumVbiFrameNumber() - tbcSources.getMinimumVbiFrameNumber();

    qInfo() << "Processing" << length << "frames starting from VBI frame" << vbiStartFrame;
    if (!tbcSources.saveSources(vbiStartFrame, length, dodThreshold)) {
        qCritical() << "Saving source failed!";
        return false;
    }

    return true;
}

bool Diffdod::loadInputTbcFiles(QVector<QString> inputFilenames, bool reverse)
{
    for (qint32 i = 0; i < inputFilenames.size(); i++) {
        qInfo().nospace() << "Loading TBC input source #" << i << " - Filename: " << inputFilenames[i];
        if (!tbcSources.loadSource(inputFilenames[i], reverse)) {
            return false;
        }
    }

    return true;
}
