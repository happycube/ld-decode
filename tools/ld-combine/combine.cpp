/************************************************************************

    combine.cpp

    ld-combine - Combine TBC files
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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

#include "combine.h"

Combine::Combine(QObject *parent) : QObject(parent)
{

}

bool Combine::process(QString primaryFilename, QString secondaryFilename, QString outputFilename)
{

    SourceVideo primarySourceVideo;
    SourceVideo secondarySourceVideo;

    // Open the primary source video metadata
    if (!primaryLdDecodeMetaData.read(primaryFilename + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file for the primary input file";
        return false;
    }

    // Open the secondary source video metadata
    if (!secondaryLdDecodeMetaData.read(secondaryFilename + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file for the secondary input file";
        return false;
    }

    primaryVideoParameters = primaryLdDecodeMetaData.getVideoParameters();
    secondaryVideoParameters = secondaryLdDecodeMetaData.getVideoParameters();
    qDebug() << "DropOutDetector::process(): Primary input source is" << primaryVideoParameters.fieldWidth << "x"
             << primaryVideoParameters.fieldHeight << "filename" << primaryFilename;
    qDebug() << "DropOutDetector::process(): Secondary input source is" << secondaryVideoParameters.fieldWidth << "x"
             << secondaryVideoParameters.fieldHeight << "filename" << secondaryFilename;

    // Confirm both sources are the same video standard
    if (primaryVideoParameters.isSourcePal != secondaryVideoParameters.isSourcePal) {
        // Primary and secondard input video standards do not match
        qInfo() << "Primary and secondard input files must both be PAL or NTSC, not a combination";
        return false;
    }

    // Open the primary source video
    if (!primarySourceVideo.open(primaryFilename, primaryVideoParameters.fieldWidth * primaryVideoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open primary ld-decode video file";
        return false;
    }

    // Open the secondary source video
    if (!secondarySourceVideo.open(secondaryFilename, secondaryVideoParameters.fieldWidth * secondaryVideoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open secondary ld-decode video file";
        return false;
    }

    // Open the target video
    QFile targetVideo(outputFilename);
    if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Could not open target video file
            qInfo() << "Unable to open output video file";
            primarySourceVideo.close();
            secondarySourceVideo.close();
            return false;
    }

    // Check TBC and JSON field numbers match
    if (primarySourceVideo.getNumberOfAvailableFields() != primaryLdDecodeMetaData.getNumberOfFields()) {
        qInfo() << "Warning: Primary TBC file contains" << primarySourceVideo.getNumberOfAvailableFields() <<
                   "fields but the JSON indicates" << primaryLdDecodeMetaData.getNumberOfFields() <<
                   "fields - some fields will be ignored";
    }

    if (secondarySourceVideo.getNumberOfAvailableFields() != secondaryLdDecodeMetaData.getNumberOfFields()) {
        qInfo() << "Warning: Secondary TBC file contains" << secondarySourceVideo.getNumberOfAvailableFields() <<
                   "fields but the JSON indicates" << secondaryLdDecodeMetaData.getNumberOfFields() <<
                   "fields - some fields will be ignored";
    }

    // Process goes here

    // Close the source videos
    primarySourceVideo.close();
    secondarySourceVideo.close();

    // Close the target video
    targetVideo.close();

    return true;
}
