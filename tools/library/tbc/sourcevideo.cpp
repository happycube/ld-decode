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

// Method to retrieve a range of field lines from a single video field.
// If startFieldLine and endFieldLine are both -1, read the whole field.
QByteArray SourceVideo::getVideoField(qint32 fieldNumber, qint32 startFieldLine, qint32 endFieldLine)
{
    // Adjust the field number to index from zero
    fieldNumber--;

    // Ensure source video is open and field is in range
    if (!isSourceVideoOpen) qFatal("Application requested TBC field before opening TBC file - Fatal error");
    if (fieldNumber < 0 || fieldNumber >= availableFields) qFatal("Application requested non-existant TBC field");

    // Calculate the position of the require field line data
    qint64 requiredStartPosition = static_cast<qint64>(fieldByteLength) * static_cast<qint64>(fieldNumber);
    qint64 requiredReadLength;

    if (startFieldLine == -1 && endFieldLine == -1) {
        // Read the whole field

        // Check the cache (we only cache whole fields)
        if (fieldCache.contains(fieldNumber)) {
            return *fieldCache.object(fieldNumber);
        }

        requiredReadLength = static_cast<qint64>(fieldByteLength);
    } else {
        // Read a range of lines

        // Adjust the field line range to index from zero
        startFieldLine--;
        endFieldLine--;

        // Verify the required range
        if (fieldLineLength == -1) qFatal("Application did not set field line length when opening TBC file");
        if (startFieldLine < 0) qFatal("Application requested out-of-bounds field line");

        requiredStartPosition += static_cast<qint64>(fieldLineLength) * static_cast<qint64>(startFieldLine);
        requiredReadLength = static_cast<qint64>(endFieldLine - startFieldLine + 1) * static_cast<qint64>(fieldLineLength);
    }

    if (requiredStartPosition + requiredReadLength > (static_cast<qint64>(fieldByteLength) * availableFields))
        qFatal("Application requested field line range that exceeds the boundaries of the input TBC file");

    // Resize the output buffer
    outputFieldData.resize(static_cast<qint32>(requiredReadLength));

    // Seek to the correct file position (if not already there)
    if (inputFile.pos() != requiredStartPosition) {
        if (!inputFile.seek(requiredStartPosition)) qFatal("Could not seek to required field position in input TBC file");
    }

    // Read the field lines from the input
    qint64 totalReceivedBytes = 0;
    qint64 receivedBytes = 0;
    do {
        receivedBytes = inputFile.read(outputFieldData.data() + totalReceivedBytes, requiredReadLength - totalReceivedBytes);
        totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < requiredReadLength);

    // Verify read was ok
    if (totalReceivedBytes != requiredReadLength) qFatal("Could not read field data from input TBC file");

    if (startFieldLine == -1 && endFieldLine == -1) {
        // Insert the field data into the cache
        fieldCache.insert(fieldNumber, new QByteArray(outputFieldData), 1);
    }

    // Return the data
    return outputFieldData;
}













