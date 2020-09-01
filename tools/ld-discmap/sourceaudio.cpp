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
    QFileInfo inputAudioFileInfo(inputFileInfo.absolutePath() + inputFileInfo.baseName() + ".pcm");

    // Open the metadata for the input TBC file
    QFileInfo inputMetadataFileInfo(inputFileInfo.filePath() + ".json");
    ldDecodeMetaData->read(inputMetadataFileInfo.filePath());

    // Open the TBC metadata file
    if (!ldDecodeMetaData->read(inputMetadataFileInfo.filePath())) {
        // Open failed
        qDebug() << "Cannot load JSON metadata from" << inputMetadataFileInfo.filePath();
        return false;
    }

    // Open the audio source data file
    if (!inputAudioFile.open(QIODevice::ReadOnly)) {
        // Failed to open named input file
        qWarning() << "Could not open " << inputAudioFileInfo.filePath() << "as source audio input file";
        return false;
    }

    // Read the metadata and create an index to the field audio (position and length)
    qint32 numberOfFields = ldDecodeMetaData->getVideoParameters().numberOfSequentialFields;
    startPosition.resize(numberOfFields);
    fieldLength.resize(numberOfFields);

    for (qint32 fieldNo = 0; fieldNo < numberOfFields; fieldNo++) {
        fieldLength[fieldNo] = static_cast<qint64>(ldDecodeMetaData->getField(fieldNo + 1).audioSamples);
        if (fieldNo > 0) startPosition[fieldNo] = startPosition[fieldNo - 1] + fieldLength[fieldNo];
        else startPosition[fieldNo] = 0;
    }

    return true;
}

// Close an audio source file
void SourceAudio::close()
{
    // Clear the indexes
    startPosition.clear();
    fieldLength.clear();

    // Close the audio source data file
    inputAudioFile.close();
}

// Get audio data for a single field from the audio source file
QVector<qint16> SourceAudio::getAudioForField(qint32 fieldNo)
{
    QVector<qint16> audioData;

    // Check the requested field number is value
    if (fieldNo > ldDecodeMetaData->getVideoParameters().numberOfSequentialFields) {
        qFatal("Application requested an audio field number that exceeds the available number of fields");
        return audioData;
    }
    qint64 maxPosition = (startPosition[fieldNo] + fieldLength[fieldNo]) * 4; // 16-bit word * stereo - to byte
    if (maxPosition > inputAudioFile.bytesAvailable()) {
        qFatal("Application requested audio field number that exceeds the boundaries of the input PCM audio file");
        return audioData;
    }

    // Resize the audio buffer
    audioData.resize(fieldLength[fieldNo]);

    // Seek to the correct file position (if not already there)
    if (!inputAudioFile.seek(startPosition[fieldNo] * 4)) {
        // Seek failed
        qFatal("Could not seek to field position in input audio file!");
        return audioData;
    }

    // Read the audio data from the audio input file
    qint64 totalReceivedBytes = 0;
    qint64 receivedBytes = 0;
    do {
        receivedBytes = inputAudioFile.read(reinterpret_cast<char *>(audioData.data()) + totalReceivedBytes,
                                       ((fieldLength[fieldNo]) * 4) - totalReceivedBytes);
        totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < ((fieldLength[fieldNo]) * 4));

    // Verify read was ok
    if (totalReceivedBytes != ((fieldLength[fieldNo]) * 4)) {
        qFatal("Could not get enough input bytes from input audio file");
        return audioData;
    }

    return audioData;
}
