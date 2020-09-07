/************************************************************************

    sourceaudio.cpp

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019-2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-discmap is free software: you can redistribute it and/or
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

#include "sourceaudio.h"

SourceAudio::SourceAudio()
{
}

// Open an audio source file
bool SourceAudio::open(QFileInfo inputFileInfo)
{
    // Get the input audio fileinfo from the input TBC fileinfo:
    QFileInfo inputAudioFileInfo(inputFileInfo.absolutePath() + "/" + inputFileInfo.baseName() + ".pcm");

    // Open the metadata for the input TBC file
    qDebug() << "Opening audio source metadata for sample analysis...";
    QFileInfo inputMetadataFileInfo(inputFileInfo.filePath() + ".json");
    ldDecodeMetaData = new LdDecodeMetaData;

    // Open the TBC metadata file
    if (!ldDecodeMetaData->read(inputMetadataFileInfo.filePath())) {
        // Open failed
        qDebug() << "Cannot load JSON metadata from" << inputMetadataFileInfo.filePath();
        return false;
    }

    // Open the audio source data file
    inputAudioFile.setFileName(inputAudioFileInfo.filePath());
    if (!inputAudioFile.open(QIODevice::ReadOnly)) {
        // Failed to open named input file
        qWarning() << "Could not open " << inputAudioFileInfo.filePath() << "as source audio input file";
        return false;
    }
    qDebug() << "Opened audio source; processing field sample lengths...";

    // Read the metadata and create an index to the field audio (byte position and byte length)
    qint32 numberOfFields = ldDecodeMetaData->getVideoParameters().numberOfSequentialFields;
    startBytePosition.resize(numberOfFields + 1);
    fieldByteLength.resize(numberOfFields + 1);
    totalByteSize = 0;

    for (qint32 fieldNo = 0; fieldNo < numberOfFields; fieldNo++) {
        // Each audio sample is 16 bit - and there are 2 samples per stereo pair
        fieldByteLength[fieldNo] = static_cast<qint64>(ldDecodeMetaData->getField(fieldNo + 1).audioSamples * 4);
        totalByteSize += fieldByteLength[fieldNo];
        if (fieldNo > 0) startBytePosition[fieldNo] = startBytePosition[fieldNo - 1] + fieldByteLength[fieldNo];
        else startBytePosition[fieldNo] = 0;
    }

    // Verify that the number of available bytes in the input sample file match
    // the total number of samples indicated by the input sample file
    if (totalByteSize != inputAudioFile.bytesAvailable()) {
        qDebug() << "Bytes of audio data according to metadata =" << totalByteSize << "Actual size in bytes =" << inputAudioFile.bytesAvailable();
        qFatal("Audio metadata for the source is not correct");
        return false;
    }

    return true;
}

// Close an audio source file
void SourceAudio::close()
{
    // Clear the indexes
    startBytePosition.clear();
    fieldByteLength.clear();

    // Close the audio source data file
    inputAudioFile.close();
}

// Get audio data for a single field from the audio source file
QByteArray SourceAudio::getAudioForField(qint32 fieldNo)
{
    QByteArray audioData;

    // Check the requested field number is valid
    if (fieldNo > ldDecodeMetaData->getVideoParameters().numberOfSequentialFields) {
        qFatal("Application requested an audio field number that exceeds the available number of fields");
        return audioData;
    }
    if (fieldNo < 1) {
        qFatal("Application requested an invalid audio field number of 0");
        return audioData;
    }

    // Re-index field number from 0
    fieldNo--;

    // Ensure the maximum requested byte doesn't overrun the acutal file length
    if ((startBytePosition[fieldNo] + fieldByteLength[fieldNo]) > totalByteSize) {
        qDebug() << "Size:" << inputAudioFile.bytesAvailable() << "Request:" <<
                    (startBytePosition[fieldNo] + fieldByteLength[fieldNo]) << "Field:" << fieldNo;
        qFatal("Application requested audio field number that exceeds the boundaries of the input PCM audio file");
        return audioData;
    }

    // Resize the audio buffer (2x 16-bit L/R sample)
    audioData.resize(fieldByteLength[fieldNo]);

    // Seek to the correct file position (if not already there)
    if (!inputAudioFile.seek(startBytePosition[fieldNo])) {
        // Seek failed
        qFatal("Could not seek to field position in input audio file!");
        return audioData;
    }

    // Read the audio data from the audio input file
    qint64 totalReceivedBytes = 0;
    qint64 receivedBytes = 0;
    do {
        receivedBytes = inputAudioFile.read(reinterpret_cast<char *>(audioData.data()) + totalReceivedBytes,
                                       fieldByteLength[fieldNo] - totalReceivedBytes);
        totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < fieldByteLength[fieldNo]);

    // Verify read was ok
    if (totalReceivedBytes != fieldByteLength[fieldNo]) {
        qFatal("Could not get enough input bytes from input audio file");
        return audioData;
    }

    return audioData;
}

