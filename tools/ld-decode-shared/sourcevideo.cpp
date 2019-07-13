/************************************************************************

    sourcevideo.cpp

    ld-decode-tools shared library
    Copyright (C) 2018 Simon Inns

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
    fileName.clear();
    fieldLength = -1;

    // Track caching success rate
    cacheHit = 0;
    cacheMiss = 0;

    // Set cache maximum cost (number of objects to cache)
    fieldCache.setMaxCost(200);
}

SourceVideo::~SourceVideo()
{
    if (isSourceVideoOpen) inputFile.close();
}

// Source Video file manipulation methods -----------------------------------------------------------------------------

// Open an input video data file (returns true on success)
bool SourceVideo::open(QString fileNameParam, qint32 fieldLengthParam)
{
    fieldLength = fieldLengthParam;
    qDebug() << "SourceVideo::open(): Called with field length =" << fieldLength;

    if (isSourceVideoOpen) {
        // Video file is already open, close it
        qInfo() << "A source video input file is already open, cannot open a new one";
        return false;
    }

    // Open the source video file
    inputFile.setFileName(fileNameParam);
    if (!inputFile.open(QIODevice::ReadOnly)) {
        // Failed to open input file
        qWarning() << "Could not open " << fileNameParam << "as source video input file";
        isSourceVideoOpen = false;
        return false;
    }

    // File open successful - configure source video parameters
    isSourceVideoOpen = true;
    fileName = fileNameParam;
    qint64 tAvailableFields = (inputFile.size() / (fieldLength * 2));
    availableFields = static_cast<qint32>(tAvailableFields);
    qDebug() << "SourceVideo::open(): Successful -" << availableFields << "fields available";

    return true;
}

// Close an input video data file
void SourceVideo::close(void)
{
    if (!isSourceVideoOpen) {
        qDebug() << "SourceVideo::close(): Called but no source video input file is open";
        return;
    }

    qDebug() << "SourceVideo::close(): Called, closing the source video file and emptying the frame cache";
    inputFile.close();
    isSourceVideoOpen = false;

    // Clear the frame cache
    fieldCache.clear();

    qDebug() << "SourceVideo::close(): Source video input file closed";
}

// Get the validity of the source video file
bool SourceVideo::isSourceValid(void)
{
    return isSourceVideoOpen;
}

// Get the number of fields available from the source video file
qint32 SourceVideo::getNumberOfAvailableFields(void)
{
    return availableFields;
}

// Frame data retrieval methods ---------------------------------------------------------------------------------------

// Method to retrieve a single video frame (with pre-caching)
// When calling from interactive applications, setting noPreCache to true
// will speed up random-accesses (as opposed to sequential field reads)
SourceField* SourceVideo::getVideoField(qint32 fieldNumber, bool noPreCache)
{
    // Check the cache
    if (fieldCache.contains(fieldNumber)) return fieldCache.object(fieldNumber);

    // Ensure source video is open and field is in range
    if (!isSourceVideoOpen) qFatal("Application requested video field before opening TBC file - Fatal error");
    if (fieldNumber < 1 || fieldNumber > availableFields) qFatal("Application request non-existant TBC field");

    // Seek to the correct file position for the requested field (if not already there)
    qint64 requiredPosition = static_cast<qint64>((fieldLength * 2)) * static_cast<qint64>(fieldNumber - 1);
    if (inputFile.pos() != requiredPosition) {
        if (!inputFile.seek(requiredPosition)) qFatal("Could not seek to required field position in input TBC file");
    }

    if (!noPreCache) {
        // Read 100 fields of data (or the rest of the available fields)
        qint32 fieldsToRead = availableFields - (fieldNumber - 1);
        if (fieldsToRead > 100) fieldsToRead = 100;
        qint32 fieldLengthInBytes = fieldLength * 2;

        QByteArray inputFields;
        inputFields.resize(fieldLengthInBytes * fieldsToRead);

        // Read the data from the file into the field buffer
        qint64 totalReceivedBytes = 0;
        qint64 receivedBytes = 0;
        do {
            receivedBytes = inputFile.read(inputFields.data(), inputFields.size() - receivedBytes);
            totalReceivedBytes += receivedBytes;
        } while (receivedBytes > 0 && totalReceivedBytes < inputFields.size());

        // Verify read was ok
        if (receivedBytes != inputFields.size()) qFatal("Could not read input fields from file even though they were available");

        // Cache the received fields
        qint32 fieldPointer = fieldNumber;
        for (qint32 i = 0; i < fieldsToRead; i++) {
            SourceField* sourceField = new SourceField(inputFields.mid(i * fieldLengthInBytes, fieldLengthInBytes));
            fieldCache.insert(fieldPointer, sourceField, 1);
            fieldPointer++;
        }
    } else {
        // Do not perform pre-caching
        QByteArray inputFields;
        inputFields.resize(fieldLength * 2);

        // Read the data from the file into the field buffer
        qint64 totalReceivedBytes = 0;
        qint64 receivedBytes = 0;
        do {
            receivedBytes = inputFile.read(inputFields.data(), inputFields.size() - receivedBytes);
            totalReceivedBytes += receivedBytes;
        } while (receivedBytes > 0 && totalReceivedBytes < inputFields.size());

        // Verify read was ok
        if (receivedBytes != inputFields.size()) qFatal("Could not read input fields from file even though they were available");

        // Cache the received field
        SourceField* sourceField = new SourceField(inputFields);
        fieldCache.insert(fieldNumber, sourceField, 1);
    }

    // Return the originally request field
    return fieldCache.object(fieldNumber);
}

