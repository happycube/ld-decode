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
    fieldLength = -1;

    // Set up the cache
    cache.maximumItems = 100;
    cache.storage.resize(cache.maximumItems);
    cache.items = 0;
    cache.startFieldNumber = 0;
}

SourceVideo::~SourceVideo()
{
    if (isSourceVideoOpen) inputFile.close();
}

// Source Video file manipulation methods -----------------------------------------------------------------------------

// Open an input video data file (returns true on success)
bool SourceVideo::open(QString filename, qint32 _fieldLength)
{
    fieldLength = _fieldLength;
    qDebug() << "SourceVideo::open(): Called with field length =" << fieldLength;

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
    qint64 tAvailableFields = (inputFile.size() / (fieldLength * 2));
    availableFields = static_cast<qint32>(tAvailableFields);
    qDebug() << "SourceVideo::open(): Successful -" << availableFields << "fields available";

    // Initialise the frame cache
    cache.storage.clear();
    cache.storage.resize(cache.maximumItems);
    cache.items = 0;
    cache.startFieldNumber = -1;
    cache.hit = 0;
    cache.miss = 0;
    for (qint32 i = 0; i < cache.maximumItems; i++) cache.storage[i].resize(fieldLength * 2);

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
QByteArray SourceVideo::getVideoField(qint32 fieldNumber, bool noPreCache)
{
    // Adjust the field number to index from zero
    fieldNumber--;

    // Check the cache
    if (fieldNumber >= cache.startFieldNumber && fieldNumber < cache.startFieldNumber + cache.items) {
        cache.hit++;
        return cache.storage[fieldNumber - cache.startFieldNumber];
    } else cache.miss++;
    qDebug() << "SourceVideo::getVideoField(): Cache hits =" << cache.hit << "misses =" << cache.miss;

    // Ensure source video is open and field is in range
    if (!isSourceVideoOpen) qFatal("Application requested video field before opening TBC file - Fatal error");
    if (fieldNumber < 0 || fieldNumber >= availableFields) qFatal("Application request non-existant TBC field");

    // Seek to the correct file position for the requested field (if not already there)
    qint64 requiredPosition = static_cast<qint64>((fieldLength * 2)) * static_cast<qint64>(fieldNumber);
    if (inputFile.pos() != requiredPosition) {
        if (!inputFile.seek(requiredPosition)) qFatal("Could not seek to required field position in input TBC file");
    }

    if (!noPreCache) {
        // Fill the cache with data
        qint32 fieldsToRead = availableFields - fieldNumber;
        if (fieldsToRead > cache.maximumItems) fieldsToRead = cache.maximumItems;

        // Read the data from the file into the cache
        cache.startFieldNumber = fieldNumber;
        cache.items = fieldsToRead;

        for (qint32 i = 0; i < fieldsToRead; i++)
        {
            qint64 totalReceivedBytes = 0;
            qint64 receivedBytes = 0;
            do {
                receivedBytes = inputFile.read(cache.storage[i].data(), cache.storage[i].size() - receivedBytes);
                totalReceivedBytes += receivedBytes;
            } while (receivedBytes > 0 && totalReceivedBytes < cache.storage[i].size());

            // Verify read was ok
            if (receivedBytes != cache.storage[i].size()) qFatal("Could not read input fields from file even though they were available");
        }
    } else {
        // Do not perform pre-caching

        // Read the data from the file into the cache
        qint64 totalReceivedBytes = 0;
        qint64 receivedBytes = 0;
        cache.startFieldNumber = fieldNumber;
        cache.items = 1;

        do {
            receivedBytes = inputFile.read(cache.storage[0].data(), cache.storage[0].size() - receivedBytes);
            totalReceivedBytes += receivedBytes;
        } while (receivedBytes > 0 && totalReceivedBytes < cache.storage[0].size());

        // Verify read was ok
        if (receivedBytes != cache.storage[0].size()) qFatal("Could not read input fields from file even though they were available");

        // Return the field
        return cache.storage[0];
    }

    // Return the originally request field
    return cache.storage[fieldNumber - cache.startFieldNumber];
}

