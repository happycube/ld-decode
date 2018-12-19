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
    qDebug() << "SourceVideo::SourceVideo(): Object created";

    // Default object settings
    isSourceVideoValid = false;
    availableFields = -1;
    fileName.clear();
    fieldLength = -1;
    inputFile = nullptr;
}

SourceVideo::~SourceVideo()
{
    if (inputFile != nullptr) delete inputFile;
}

// Source Video file manipulation methods -----------------------------------------------------------------------------

// Open an input video data file (returns true on success)
bool SourceVideo::open(QString fileNameParam, qint32 fieldLengthParam)
{
    fieldLength = fieldLengthParam;
    qDebug() << "SourceVideo::open(): Called with field length =" << fieldLength;

    if (isSourceVideoValid) {
        // Video file is already open, close it
        qInfo() << "A source video input file is already open, cannot open a new one";
        return false;
    }

    // Open the source video file
    inputFile = new QFile(fileNameParam);
    if (!inputFile->open(QIODevice::ReadOnly)) {
        // Failed to open input file
        qWarning() << "Could not open " << fileNameParam << "as source video input file";
        isSourceVideoValid = false;
        return false;
    }

    // File open successful - configure source video parameters
    isSourceVideoValid = true;
    fileName = fileNameParam;
    qint64 tAvailableFields = (inputFile->size() / (fieldLength * 2));
    availableFields = static_cast<qint32>(tAvailableFields);
    qDebug() << "SourceVideo::open(): Successful -" << availableFields << "fields available";

    return true;
}

// Close an input video data file
void SourceVideo::close(void)
{
    if (!isSourceVideoValid) {
        qDebug() << "SourceVideo::close(): Called but no source video input file is open";
        return;
    }

    qDebug() << "SourceVideo::close(): Called, closing the source video file and emptying the frame cache";
    inputFile->close();
    isSourceVideoValid = false;

    // Clear the frame cache
    fieldCache.clear();

    qDebug() << "SourceVideo::close(): Source video input file closed";
}

// Get the validity of the source video file
bool SourceVideo::isSourceValid(void)
{
    return isSourceVideoValid;
}

// Get the number of fields available from the source video file
qint32 SourceVideo::getNumberOfAvailableFields(void)
{
    return availableFields;
}

// Frame data retrieval methods ---------------------------------------------------------------------------------------

// Method to retrieve a single video frame (with caching)
SourceField* SourceVideo::getVideoField(qint32 fieldNumber)
{
    // Check the cache
    if (fieldCache.contains(fieldNumber)) {
        qDebug() << "SourceVideo::getVideoField(): Returning cached field" << fieldNumber;
        return fieldCache.object(fieldNumber);
    }

    // Verify that we have an open file
    if (!isSourceVideoValid) {
        qWarning() << "Source video getVideoField called, but no input file is open";
        // Return with error
        return nullptr;
    }

    // Range check the requested field range
    if (fieldNumber < 1 || fieldNumber > availableFields) {
        qWarning() << "Requested field number" << fieldNumber << "is out of range!";
        return nullptr;
    }

    // Seek to the requested field
    if (!seekToFieldNumber(fieldNumber)) {
        // Seeking failed, just return the current cached field
        qWarning() << "Source video seek failed... staying on the current field";
        return nullptr;
    }

    // Persistant object for storing a field (managed by qcache)
    sourceField = new SourceField();

    // Add the raw field data from the source video file to the field object
    sourceField->setFieldData(readRawFieldData());

    // Place the frame in the frame cache
    fieldCache.insert(fieldNumber, sourceField, 1);

    qDebug() << "SourceVideo::getVideoField(): Completed";
    return fieldCache.object(fieldNumber);
}

// Private methods for image and file manipulation --------------------------------------------------------------------

// Seeks the input file to the specified field number
bool SourceVideo::seekToFieldNumber(qint32 fieldNumber)
{
    qDebug() << "SourceVideo::seekToFieldNumber(): Called with fieldNumber =" << fieldNumber;

    if (!isSourceVideoValid) {
        qWarning() << "Source video seekToFieldNumber called, but no input file is open";
        return false;
    }

    // Check that the required field number is in range (and possible)
    if (fieldNumber > availableFields || fieldNumber < 1) {
        qWarning() << "Source video seekToFieldNumber - Requested field number" << fieldNumber << "is out of bounds!";
        return false;
    }

    qint64 requiredPosition = static_cast<qint64>((fieldLength * 2)) * static_cast<qint64>(fieldNumber - 1);
    if (!inputFile->seek(requiredPosition)) {
        qWarning() << "Source video seek to requested field number" << fieldNumber << "of" << availableFields << "failed!";
        return false;
    }

    return true;
}

// Read a field of data from the input file into the current field data QByteArray
QByteArray SourceVideo::readRawFieldData(void)
{
    qDebug() << "SourceVideo::readRawFieldData(): Called" <<
                " - field length is" << fieldLength << "words";

    QByteArray outputData;

    // Resize the raw field buffer
    // The size is fieldLength with 16-bit data words
    outputData.resize((fieldLength * 2));

    // Read the data from the file into the raw field buffer
    qint64 totalReceivedBytes = 0;
    qint64 receivedBytes = 0;
    do {
        receivedBytes = inputFile->read(outputData.data(), outputData.size() - receivedBytes);

        if (receivedBytes > 0) totalReceivedBytes += receivedBytes;
        //qDebug() << "SourceVideo::readRawFieldData(): Got" << receivedBytes << "bytes from input file";
    } while (receivedBytes > 0 && totalReceivedBytes < outputData.size());
    //qDebug() << "SourceVideo::readRawFieldData(): Got a total of" << totalReceivedBytes << "bytes from input file";

    // Did we run out of data before filling the buffer?
    if (receivedBytes == 0) {
        // Determine why we failed
        if (totalReceivedBytes == 0) {
            // We didn't get any data at all...
            qWarning() << "Zero data received when reading raw field data";
        } else {
            // End of file was reached before filling buffer
            qWarning() << "Reached end of file before filling buffer";
        }

        // Return with empty data
        outputData.clear();
        return outputData;
    }

    // Successful
    return outputData;
}
