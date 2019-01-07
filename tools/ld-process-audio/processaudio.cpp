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
    QString outputAudacityFilename = QFileInfo(inputFileName).path() + "/" + QFileInfo(inputFileName).baseName() + ".pcm.txt";
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

    if (!openAudacityMetadataFile(outputAudacityFilename)) {
        qInfo() << "Could not open the target audacity metadata file";
        return false;
    }

    // Process the field sample positions
    for (qint32 fieldNumber = 1; fieldNumber <= ldDecodeMetaData.getNumberOfFields(); fieldNumber++) {
    //for (qint32 fieldNumber = 1; fieldNumber <= 10; fieldNumber++) {
        QVector<AudioData> audioData;

        // Read a field of audio data
        audioData = readFieldAudio(fieldNumber);

        if (audioData.isEmpty()) {
            qCritical() << "Hit end of audio data when expecting more...";
            break;
        }

        // Only output meta data for fields that have dropouts
        if (ldDecodeMetaData.getField(fieldNumber).dropOuts.startx.size() > 0) {
            qint64 startSample = sampleStartPosition[fieldNumber];
            qint64 endSample = startSample + ldDecodeMetaData.getField(fieldNumber).audioSamples - 1;

            qInfo() << "Processing field" << fieldNumber << "- audio sample position =" << startSample << "-" << endSample;

            // Write the field's start and end sample position to the audacity label metadata
            writeAudacityMetadataLabel(startSample, endSample, "F#" + QString::number(fieldNumber));

            // Write the field's dropouts to the audacity label metadata
            LdDecodeMetaData::DropOuts dropouts = ldDecodeMetaData.getField(fieldNumber).dropOuts;;
            for (qint32 dropoutNumber = 0; dropoutNumber < dropouts.startx.size(); dropoutNumber++) {

                // Work around for JSON field height issue
                qint32 workAroundFieldHeight = 0;
                if (videoParameters.isSourcePal) {
                    if (ldDecodeMetaData.getField(fieldNumber).isFirstField) workAroundFieldHeight = 312;
                    else workAroundFieldHeight = 313;
                } else {
                    if (ldDecodeMetaData.getField(fieldNumber).isFirstField) workAroundFieldHeight = 262;
                    else workAroundFieldHeight = 263;
                }

                // Calculate the start and end audio sample for the dropout

                // Samples per field / field height = samples per field line
                qreal samplesPerLine = static_cast<qreal>(ldDecodeMetaData.getField(fieldNumber).audioSamples / static_cast<qreal>(workAroundFieldHeight));

                // There seems to be some form of calculation mismatch going on... this works around it, but I need to find the root-cause
                qreal startOfLine = startSample + (samplesPerLine * (dropouts.fieldLine[dropoutNumber] + 2));
                if (ldDecodeMetaData.getField(fieldNumber).isFirstField) startOfLine = startSample + (samplesPerLine * (dropouts.fieldLine[dropoutNumber] + 1));

                // Calculate absolute position of dropout in the sample
                qreal startOfDropout = startOfLine + ((samplesPerLine / static_cast<qreal>(ldDecodeMetaData.getVideoParameters().fieldWidth)) * static_cast<qreal>(dropouts.startx[dropoutNumber]));
                qreal endOfDropout = startOfLine + ((samplesPerLine / static_cast<qreal>(ldDecodeMetaData.getVideoParameters().fieldWidth)) * static_cast<qreal>(dropouts.endx[dropoutNumber]));

                qDebug() << "Field #" << fieldNumber << "- dropout #" << dropoutNumber << "line #" << dropouts.fieldLine[dropoutNumber] <<
                            "startSample =" << static_cast<qint64>(startOfDropout) << "endSample =" << static_cast<qint64>(endOfDropout);

                writeAudacityMetadataLabel(static_cast<qint64>(startOfDropout), static_cast<qint64>(endOfDropout), "DO#" + QString::number(dropoutNumber));

                // Correct the dropout

                // Calcualte the relative position of the dropout within the field
                startOfLine = (samplesPerLine * (dropouts.fieldLine[dropoutNumber] + 2));
                if (ldDecodeMetaData.getField(fieldNumber).isFirstField) startOfLine = (samplesPerLine * (dropouts.fieldLine[dropoutNumber] + 1));
                startOfDropout = startOfLine + ((samplesPerLine / static_cast<qreal>(ldDecodeMetaData.getVideoParameters().fieldWidth)) * static_cast<qreal>(dropouts.startx[dropoutNumber]));
                endOfDropout = startOfLine + ((samplesPerLine / static_cast<qreal>(ldDecodeMetaData.getVideoParameters().fieldWidth)) * static_cast<qreal>(dropouts.endx[dropoutNumber]));

                qDebug() << "Correcting field" << fieldNumber << "samples" << static_cast<qint32>(startOfDropout) << "-" << static_cast<qint32>(endOfDropout);
                audioData = correctAudioDropout(static_cast<qint32>(startOfDropout), static_cast<qint32>(endOfDropout), audioData);
            }
        }

        // Write the audio data for the current field
        writeFieldAudio(audioData);
    }

    // Close the analogue audio .pcm files
    closeInputAudioFile();
    closeOutputAudioFile();
    closeAudacityMetadataFile();

    return true;
}

// Method to correct an audio sample
QVector<ProcessAudio::AudioData> ProcessAudio::correctAudioDropout(qint32 startSample, qint32 endSample, QVector<ProcessAudio::AudioData> audioData)
{
    qint32 startLeftValue = 0;
    qint32 endLeftValue = 0;
    qreal stepLeftValue = 0;

    qint32 startRightValue = 0;
    qint32 endRightValue = 0;
    qreal stepRightValue = 0;

    // This sets the minimum number of samples to correct for any given dropout
    qint32 minimumDistance = 3;

    qint32 numberOfSamples = (endSample - startSample) + minimumDistance;

    if (startSample > 0) {
        startLeftValue = audioData[startSample - 1].left;
        startRightValue = audioData[startSample - 1].right;
    }

    if ((endSample + minimumDistance) < audioData.size()) {
        endLeftValue = audioData[endSample + 1 + minimumDistance].left;
        endRightValue = audioData[endSample + 1 + minimumDistance].right;
    }

    // Underflow check for start sample
    if (startSample == 0) {
        startLeftValue = endLeftValue;
        startRightValue = endRightValue;
    }

    // Overflow check for end sample
    if ((endSample + minimumDistance) >= audioData.size()) {
        endLeftValue = startLeftValue;
        endRightValue = startRightValue;
    }

    stepLeftValue = static_cast<qreal>(endLeftValue - startLeftValue) / static_cast<qreal>(numberOfSamples);
    stepRightValue = static_cast<qreal>(endRightValue - startRightValue) / static_cast<qreal>(numberOfSamples);

    qreal currentLeftValue = startLeftValue + stepLeftValue;
    qreal currentRightValue = startRightValue + stepRightValue;

    for (qint32 sampleNumber = startSample; sampleNumber <= endSample + minimumDistance; sampleNumber++) {
        audioData[sampleNumber].left = static_cast<qint16>(currentLeftValue);
        audioData[sampleNumber].right = static_cast<qint16>(currentRightValue);

        currentLeftValue += stepLeftValue;
        currentRightValue += stepRightValue;
    }

    return audioData;
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
    QByteArray rawData;
    rawData.resize(audioData.size() * 4);

    // Copy the fieldAudio vector into the raw data array
    qint16 *dataPointer = reinterpret_cast<qint16*>(rawData.data());
    qint32 rawDataPointer = 0;
    for (qint32 samplePointer = 0; samplePointer < audioData.size(); samplePointer++) {
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

    // Seek to the start sample position of the 16-bit input file
    // 2 channels of 2 byte samples = * 4
    qint64 requiredPosition = static_cast<qint64>(sampleStartPosition[fieldNumber] * 4);
        if (!audioInputFile->seek(requiredPosition)) {
            qWarning() << "Source audio seek to requested field number" << fieldNumber << "failed!";
            return fieldAudio;
    }

    // Resize the audio data to the length of the field
    fieldAudio.resize(ldDecodeMetaData.getField(fieldNumber).audioSamples);

    // Read the audio data
    QByteArray rawData;
    rawData.resize(ldDecodeMetaData.getField(fieldNumber).audioSamples * 4);

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
    for (qint32 samplePointer = 0; samplePointer < ldDecodeMetaData.getField(fieldNumber).audioSamples; samplePointer++) {
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

    // Scan the input sample and record the sample start positions for each field
    qint64 samplePosition = 0;
    sampleStartPosition.clear();

    // Field numbering starts from 1, so add a dummy value
    sampleStartPosition.append(0);

    for (qint32 fieldNumber = 1; fieldNumber <= ldDecodeMetaData.getNumberOfFields(); fieldNumber++) {
        sampleStartPosition.append(samplePosition);
        samplePosition += ldDecodeMetaData.getField(fieldNumber).audioSamples;
    }

    qint64 samplesInInputFile = audioInputFile->size() / 4;
    qDebug() << "Samples in input file =" << samplesInInputFile << "- samples according to metadata =" << samplePosition;

    if (samplesInInputFile != samplePosition) {
        qCritical() << "Samples in the input audio file do not match the number of samples in the metadata - Cannot continue!";
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

// Method to open an Audacity label metadata file as output
bool ProcessAudio::openAudacityMetadataFile(QString filename)
{
    // Open the source audio file
    audacityOutputFile = new QFile(filename);
    if (!audacityOutputFile->open(QIODevice::WriteOnly | QIODevice::Text)) {
        // Failed to open output file
        qWarning() << "Could not open " << filename << "as target Audacity metadata file";
        return false;
    }
    return true;
}

// Method to close an Audacity label metadata output file
void ProcessAudio::closeAudacityMetadataFile(void)
{
    audacityOutputFile->close();
}

// Method to write a metadata label in Audacity format
void ProcessAudio::writeAudacityMetadataLabel(qint64 startSample, qint64 endSample, QString description)
{
    // Convert the start and end sample positions into time (seconds to 10 decimal places)
    qreal samplesPerSecond = static_cast<qreal>(ldDecodeMetaData.getPcmAudioParameters().sampleRate);
    qreal startSecond = (1.0 / samplesPerSecond) * static_cast<qreal>(startSample);
    qreal endSecond = (1.0 / samplesPerSecond) * static_cast<qreal>(endSample);

    QTextStream stream(audacityOutputFile);
    stream << QString::number(startSecond, 'f', 10) << "\t" << QString::number(endSecond, 'f', 10) << "\t" << description << endl;
}








