/************************************************************************

    processaudio.cpp

    ld-process-audio - Analogue audio processing for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-audio is free software: you can redistribute it and/or
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

#include "processaudio.h"

ProcessAudio::ProcessAudio(QObject *parent) : QObject(parent)
{

}

bool ProcessAudio::process(QString inputFileName)
{
    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    videoParameters = ldDecodeMetaData.getVideoParameters();

    // Open the analogue audio .pcm file for the specified .tbc
    QString inputAudioFilename = QFileInfo(inputFileName).path() + "/" + QFileInfo(inputFileName).baseName() + ".pcm";
    QString outputAudioFilename = QFileInfo(inputFileName).path() + "/" + QFileInfo(inputFileName).baseName() + "_doc.pcm";
    qInfo() << "Input tbc file is:" << inputFileName;
    qInfo() << "Input pcm file is:" << inputAudioFilename;
    qInfo() << "Output pcm file is:" << outputAudioFilename;

    if (!openInputAudioFile(inputAudioFilename)) {
        qInfo() << "Could not open the source PCM audio file";
        return false;
    }

    if (!openOutputAudioFile(outputAudioFilename)) {
        qInfo() << "Could not open the target PCM audio file";
        return false;
    }

    // Process the fields
    for (qint32 fieldNumber = 1; fieldNumber <= ldDecodeMetaData.getNumberOfFields(); fieldNumber++) {
    //for (qint32 fieldNumber = 1; fieldNumber <= 10; fieldNumber++) {
        QVector<AudioData> audioData;

        // Read a field of audio data
        audioData = readFieldAudio(fieldNumber);
        qDebug() << "ProcessAudio::process(): Processing" << audioData.size() << "samples for field" << fieldNumber;

        if (audioData.isEmpty()) {
            qCritical() << "Hit end of audio data when expecting more...";
            break;
        }

        // Check the VBI data to see if the field contains audio data
        bool silenceField = false;
        LdDecodeMetaData::VbiSoundModes soundMode = ldDecodeMetaData.getField(fieldNumber).vbi.soundMode;
        if (soundMode == LdDecodeMetaData::VbiSoundModes::futureUse) silenceField = true;
        if (soundMode == LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff) silenceField = true;

        if (silenceField) {
            qDebug() << "ProcessAudio::process(): Field" << fieldNumber << "does not contain audio according to the the VBI";
            audioData = silenceAudioSample(audioData);
        }

        // Write a field of audio data
        writeFieldAudio(audioData);
    }

    // Close the analogue audio .pcm files
    closeInputAudioFile();
    closeOutputAudioFile();

    return true;
}

// Method to silence an audio sample
QVector<ProcessAudio::AudioData> ProcessAudio::silenceAudioSample(QVector<ProcessAudio::AudioData> audioData)
{
    for (qint32 sampleNumber = 0; sampleNumber < audioData.size(); sampleNumber++) {
        audioData[sampleNumber].left = 0;
        audioData[sampleNumber].right = 0;
    }

    return audioData;
}

// Method to write the audio data for a field
void ProcessAudio::writeFieldAudio(QVector<ProcessAudio::AudioData> audioData)
{
    qint32 audioSamplesPerField = 800; // NTSC
    if (videoParameters.isSourcePal) audioSamplesPerField = 960; // PAL

    QByteArray rawData;
    rawData.resize(audioSamplesPerField * 4);

    // Copy the fieldAudio vector into the raw data array
    qint16 *dataPointer = reinterpret_cast<qint16*>(rawData.data());
    qint32 rawDataPointer = 0;
    for (qint32 samplePointer = 0; samplePointer < audioSamplesPerField; samplePointer++) {
        dataPointer[rawDataPointer++] = audioData[samplePointer].left;
        dataPointer[rawDataPointer++] = audioData[samplePointer].right;
    }

    // Write the raw data array to disc
    if (!audioOutputFile->write(rawData.data(), rawData.size())) {
        qWarning() << "Writing to output audio file failed!";
    }
}

// Method to get the audio data for a field
QVector<ProcessAudio::AudioData> ProcessAudio::readFieldAudio(qint32 fieldNumber)
{
    QVector<AudioData> fieldAudio;
    videoParameters = ldDecodeMetaData.getVideoParameters();

    if (fieldNumber < 1 || fieldNumber > ldDecodeMetaData.getNumberOfFields()) {
        qCritical() << "ProcessAudio::readFieldAudio(): Requested field" << fieldNumber << "is out of bounds!";
        return fieldAudio;
    }

    // Audio data is:
    //   Signed 16-bit PCM
    //   Little-endian
    //   2 Channel (stereo)
    //   48000Hz sample rate

    qint32 audioSamplesPerField = 800; // NTSC
    if (videoParameters.isSourcePal) audioSamplesPerField = 960; // PAL

    qint32 fieldStartSample = audioSamplesPerField * (fieldNumber - 1);

    // Seek to the start sample position of the 16-bit input file
    // 2 channels of 2 byte samples = * 4
    qint64 requiredPosition = static_cast<qint64>(fieldStartSample * 4);
        if (!audioInputFile->seek(requiredPosition)) {
            qWarning() << "Source audio seek to requested field number" << fieldNumber << "failed!";
            return fieldAudio;
    }

    // Resize the audio data to the length of the field
    fieldAudio.resize(audioSamplesPerField);

    // Read the audio data
    QByteArray rawData;
    rawData.resize(audioSamplesPerField * 4);

    // Read the data from the file into the raw field buffer
    qint64 totalReceivedBytes = 0;
    qint64 receivedBytes = 0;
    do {
        receivedBytes += audioInputFile->read(rawData.data(), rawData.size() - receivedBytes);

        if (receivedBytes > 0) totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < rawData.size());

    // Did we run out of data before filling the buffer?
    if (receivedBytes == 0) {
        // Determine why we failed
        if (totalReceivedBytes == 0) {
            // We didn't get any data at all...
            qWarning() << "Zero data received when reading audio data";
        } else {
            // End of file was reached before filling buffer
            qWarning() << "Reached end of file before filling buffer";
        }

        // Return with empty data
        fieldAudio.clear();
        return fieldAudio;
    }

    // Copy the raw data into the fieldAudio vector
    qint16 *dataPointer = reinterpret_cast<qint16*>(rawData.data());
    for (qint32 samplePointer = 0; samplePointer < audioSamplesPerField; samplePointer++) {
        fieldAudio[samplePointer].left = dataPointer[(samplePointer * 2)];
        fieldAudio[samplePointer].right = dataPointer[(samplePointer * 2) + 1];
    }

    return fieldAudio;
}

// Method to open a ld-decode PCM audio file as input
bool ProcessAudio::openInputAudioFile(QString filename)
{
    // Open the source audio file
    audioInputFile = new QFile(filename);
    if (!audioInputFile->open(QIODevice::ReadOnly)) {
        // Failed to open input file
        qWarning() << "Could not open " << filename << "as source audio file";
        return false;
    }
    return true;
}

// Method to close a ld-decode PCM audio input file
void ProcessAudio::closeInputAudioFile(void)
{
    audioInputFile->close();
}

// Method to open a ld-decode PCM audio file as output
bool ProcessAudio::openOutputAudioFile(QString filename)
{
    // Open the source audio file
    audioOutputFile = new QFile(filename);
    if (!audioOutputFile->open(QIODevice::WriteOnly)) {
        // Failed to open output file
        qWarning() << "Could not open " << filename << "as target audio file";
        return false;
    }
    return true;
}

// Method to close a ld-decode PCM audio output file
void ProcessAudio::closeOutputAudioFile(void)
{
    audioOutputFile->close();
}










