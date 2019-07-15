/************************************************************************

    sourcevideo.cpp

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

#include "sourcevideo.h"

// Class constructor
SourceVideo::SourceVideo(QObject *parent) : QObject(parent)
{
    // Default object settings
    isSourceVideoOpen = false;
    availableFields = -1;
    fieldByteLength = -1;

    // Set up the cache
    fieldCache.setMaxCost(100);
}

SourceVideo::~SourceVideo()
{
    if (isSourceVideoOpen) inputFile.close();
}

// Source Video file manipulation methods -----------------------------------------------------------------------------

// Open an input video data file (returns true on success)
bool SourceVideo::open(QString filename, qint32 _fieldLength)
{
    fieldByteLength = _fieldLength * 2;
    qDebug() << "SourceVideo::open(): Called with field byte length =" << fieldByteLength;

    if (isSourceVideoOpen) {
        // Video file is already open, close it
        qInfo() << "A source video input file is already open, cannot open a new one";
        return false;
    }

    // Open the source video file
    inputFile.setFileName(filename);
    if (!inputFile.open(QIODevice::ReadOnly)) {
        // Failed to open input file
        qWarning() << "Could not open " << filename << "as source video input file";
        isSourceVideoOpen = false;
        return false;
    }

    // File open successful - configure source video parameters
    isSourceVideoOpen = true;
    qint64 tAvailableFields = (inputFile.size() / fieldByteLength);
    availableFields = static_cast<qint32>(tAvailableFields);
    qDebug() << "SourceVideo::open(): Successful -" << availableFields << "fields available";

    // Initialise cache
    fieldCache.clear();

    return true;
}

// Close an input video data file
void SourceVideo::close()
{
    if (!isSourceVideoOpen) {
        qDebug() << "SourceVideo::close(): Called but no source video input file is open";
        return;
    }

    qDebug() << "SourceVideo::close(): Called, closing the source video file and emptying the frame cache";
    inputFile.close();
    isSourceVideoOpen = false;

    qDebug() << "SourceVideo::close(): Source video input file closed";
}

// Get the validity of the source video file
bool SourceVideo::isSourceValid()
{
    return isSourceVideoOpen;
}

// Get the number of fields available from the source video file
qint32 SourceVideo::getNumberOfAvailableFields()
{
    return availableFields;
}

// Frame data retrieval methods ---------------------------------------------------------------------------------------

// Method to retrieve a single video frame (with pre-caching)
// When calling from interactive applications, setting noPreCache to true
// will speed up random-accesses (as opposed to sequential field reads)
QByteArray SourceVideo::getVideoField(qint32 fieldNumber)
{
    // Adjust the field number to index from zero
    fieldNumber--;

    // Ensure source video is open and field is in range
    if (!isSourceVideoOpen) qFatal("Application requested video field before opening TBC file - Fatal error");
    if (fieldNumber < 0 || fieldNumber >= availableFields) qFatal("Application request non-existant TBC field");

    // Check the cache
    if (fieldCache.contains(fieldNumber)) {
        return *fieldCache.object(fieldNumber);
    }

    // Seek to the correct file position for the requested field (if not already there)
    qint64 requiredPosition = static_cast<qint64>(fieldByteLength) * static_cast<qint64>(fieldNumber);
    if (inputFile.pos() != requiredPosition) {
        if (!inputFile.seek(requiredPosition)) qFatal("Could not seek to required field position in input TBC file");
    }

    // Read the frame from disk into the cache
    qint64 totalReceivedBytes = 0;
    qint64 receivedBytes = 0;
    QByteArray *fieldData = new QByteArray;
    fieldData->resize(fieldByteLength);

    do {
        receivedBytes = inputFile.read(fieldData->data(), fieldByteLength - receivedBytes);
        totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < fieldByteLength);

    // Verify read was ok
    if (receivedBytes != fieldByteLength) qFatal("Could not read input fields from file even though they were available");

    // Insert the field data into the cache
    fieldCache.insert(fieldNumber, fieldData, 1);

    // Return the originally request field
    return *fieldCache.object(fieldNumber);
}

