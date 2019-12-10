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
    fieldLineLength = -1;

    // Set up the cache
    fieldCache.setMaxCost(100);
}

SourceVideo::~SourceVideo()
{
    if (isSourceVideoOpen) inputFile.close();
}

// Source Video file manipulation methods -----------------------------------------------------------------------------

// Open an input video data file (returns true on success)
bool SourceVideo::open(QString filename, qint32 _fieldLength, qint32 _fieldLineLength)
{
    fieldByteLength = _fieldLength * 2;
    if (_fieldLineLength != -1) {
        fieldLineLength = _fieldLineLength * 2;
    } else fieldLineLength = -1;
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

// Get the byte length of the fields
qint32 SourceVideo::getFieldByteLength()
{
    return fieldByteLength;
}

// Frame data retrieval methods ---------------------------------------------------------------------------------------

// Method to retrieve a single video frame (with caching to prevent multiple
// file reads if application requests the same line multiple times)
QByteArray SourceVideo::getVideoField(qint32 fieldNumber)
{
    // Adjust the field number to index from zero
    fieldNumber--;

    // Ensure source video is open and field is in range
    if (!isSourceVideoOpen) qFatal("Application requested TBC field before opening TBC file - Fatal error");
    if (fieldNumber < 0 || fieldNumber >= availableFields) qFatal("Application requested non-existant TBC field");

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
        receivedBytes = inputFile.read(fieldData->data() + totalReceivedBytes, fieldByteLength - totalReceivedBytes);
        totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < fieldByteLength);

    // Verify read was ok
    if (totalReceivedBytes != fieldByteLength) qFatal("Could not read input fields from file even though they were available");

    // Insert the field data into the cache
    fieldCache.insert(fieldNumber, fieldData, 1);

    // Return the originally request field
    return *fieldCache.object(fieldNumber);
}

// Method to retrieve a range of field lines from a single video frame
QByteArray SourceVideo::getVideoField(qint32 fieldNumber, qint32 startFieldLine, qint32 endFieldLine)
{
    // Adjust the field number to index from zero
    fieldNumber--;

    // Adjust the field line range to index from zero
    startFieldLine--;
    endFieldLine--;

    // Ensure source video is open and field is in range
    if (!isSourceVideoOpen) qFatal("Application requested TBC field before opening TBC file - Fatal error");
    if (fieldNumber < 0 || fieldNumber >= availableFields) qFatal("Application requested non-existant TBC field");
    if (fieldLineLength == -1) qFatal("Application did not set field line length when opening TBC file");

    // Verify the required range
    if (startFieldLine < 0) qFatal("Application requested out-of-bounds field line");

    // Calculate the position of the require field line data
    qint64 requiredStartPosition = static_cast<qint64>(fieldByteLength) * static_cast<qint64>(fieldNumber);
    requiredStartPosition += static_cast<qint64>(fieldLineLength) * static_cast<qint64>(startFieldLine);
    qint64 requiredReadLength = static_cast<qint64>(endFieldLine - startFieldLine + 1) * static_cast<qint64>(fieldLineLength);

    if (requiredStartPosition + requiredReadLength > (static_cast<qint64>(fieldByteLength) * availableFields))
        qFatal("Application request field line range that exceeds the boundaries of the input TBC file");

    // Resize the output buffer
    outputFieldLineData.resize(static_cast<qint32>(requiredReadLength));

    // Seek to the correct file position for the requested field (if not already there)
    if (inputFile.pos() != requiredStartPosition) {
        if (!inputFile.seek(requiredStartPosition)) qFatal("Could not seek to required field position in input TBC file");
    }

    // Read the frame from disk into the cache
    qint64 totalReceivedBytes = 0;
    qint64 receivedBytes = 0;
    do {
        receivedBytes = inputFile.read(outputFieldLineData.data() + totalReceivedBytes, requiredReadLength - totalReceivedBytes);
        totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < requiredReadLength);

    // Verify read was ok
    if (totalReceivedBytes != requiredReadLength) qFatal("Could not read input fields from file even though they were available");

    // Return the data
    return outputFieldLineData;
}













