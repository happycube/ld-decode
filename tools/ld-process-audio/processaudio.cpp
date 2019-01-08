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

bool ProcessAudio::process(QString inputFileName, bool outputLabels, bool silenceAudio, bool labelEveryField)
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
    if (outputLabels) qInfo() << "Output Audacity label file is:" << outputAudacityFilename;

    if (!openInputAudioFile(inputAudioFilename)) {
        qInfo() << "Could not open the source PCM audio file";
        return false;
    }

    if (!openOutputAudioFile(outputAudioFilename)) {
        qInfo() << "Could not open the target PCM audio file";
        return false;
    }

    if (outputLabels) {
        if (!openAudacityMetadataFile(outputAudacityFilename)) {
            qInfo() << "Could not open the target audacity metadata file";
            return false;
        }
    }

    // Process the field sample positions
    for (qint32 fieldNumber = 1; fieldNumber <= ldDecodeMetaData.getNumberOfFields(); fieldNumber++) {

        // Read a field of audio data
        fieldAudioData = readFieldAudio(fieldNumber);

        // Check that audio data was available
        if (fieldAudioData.isEmpty()) {
            qCritical() << "Hit end of audio data when expecting more...";
            break;
        }

        // If we are not silencing audio, always decide field contains analogue audio; otherwise
        // we use the VBI to see if the field should contain audio or not
        bool fieldContainsAudio;
        if (!silenceAudio) fieldContainsAudio = true;
        else fieldContainsAudio = fieldContainsAnalogueAudio(fieldNumber);

        // If the field isn't silenced due to VBI data, perform dropout correction of the audio
        if (fieldContainsAudio) {
            // Generate a list of audio dropouts for the field
            getFieldAudioDropouts(fieldNumber, 1);

            // Output Audacity label metadata for the field
            if (outputLabels) writeAudacityLabels(fieldNumber, labelEveryField);

            // Correct the audio dropouts
            for (qint32 dropout = 0; dropout < fieldAudioDropouts.size(); dropout++) {
                correctAudioDropout(fieldNumber, fieldAudioDropouts[dropout].startSample, fieldAudioDropouts[dropout].endSample);
            }
        } else {
            // Silence the field
            silenceAudioSample();
        }

        // Write the field audio data
        writeFieldAudio();

        // Output information for the user
        if (fieldAudioDropouts.size() != 0) {
            if (fieldContainsAudio) qInfo() << "Field" << fieldNumber << "has" << fieldAudioDropouts.size() << "audio dropouts";
            else qInfo() << "Field" << fieldNumber << "has no analogue audio";
        }
    }

    // Close the files
    closeInputAudioFile();
    closeOutputAudioFile();
    if (outputLabels) closeAudacityMetadataFile();

    return true;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to determine (using VBI) if field contains analogue audio
bool ProcessAudio::fieldContainsAnalogueAudio(qint32 fieldNumber)
{
    // Get the sound format for the current field from the VBI data (if available)
    if (!ldDecodeMetaData.getField(fieldNumber).vbi.inUse) {
        // No VBI metadata is available; assume the field contains analogue audio
        return true;
    }

    // To be on the safe-side we check for VBI data that indicates the field definately
    // doesn't have analogue audio data
    if (ldDecodeMetaData.getField(fieldNumber).vbi.soundMode == LdDecodeMetaData::VbiSoundModes::futureUse ||
            ldDecodeMetaData.getField(fieldNumber).vbi.soundMode == LdDecodeMetaData::VbiSoundModes::audioSubCarriersOff) {
        // No audio
        return false;
    }

    return true;
}

// Method to convert video dropouts into audio dropouts
void ProcessAudio::getFieldAudioDropouts(qint32 fieldNumber, qint32 minimumDropoutLength)
{
    fieldAudioDropouts.clear();

    // Process the video dropout records into audio dropout records
    LdDecodeMetaData::DropOuts dropouts = ldDecodeMetaData.getField(fieldNumber).dropOuts;;

    for (qint32 dropoutNumber = 0; dropoutNumber < dropouts.startx.size(); dropoutNumber++) {
        AudioDropout audioDropout;

        // Calculate the number of field lines represented by the field's audio samples
        qint32 linesInFieldAudio;
        if (videoParameters.isSourcePal) {
            qreal samplesPerLine = ldDecodeMetaData.getPcmAudioParameters().sampleRate / 25.0 / 625.0;
            linesInFieldAudio = qRound(static_cast<qreal>(ldDecodeMetaData.getField(fieldNumber).audioSamples) / samplesPerLine);
        } else {
            qreal samplesPerLine = ldDecodeMetaData.getPcmAudioParameters().sampleRate / (30000.0 / 1001.0) / 525.0;
            linesInFieldAudio = qRound(static_cast<qreal>(ldDecodeMetaData.getField(fieldNumber).audioSamples) / samplesPerLine);
        }

        // Calculate the start and end audio sample for the dropout

        // Samples per field / field height = samples per field line
        qreal samplesPerLine = static_cast<qreal>(ldDecodeMetaData.getField(fieldNumber).audioSamples / static_cast<qreal>(linesInFieldAudio));

        // There seems to be some form of calculation mismatch going on... this works around it, but I need to find the root-cause
        // Note: This is probably due to the inaccuracy of the dropout detection and should be revisited once its been correctly
        // implemented by ld-decode.
        qreal startOfLine =  (samplesPerLine * (dropouts.fieldLine[dropoutNumber] + 2));
        if (ldDecodeMetaData.getField(fieldNumber).isFirstField) startOfLine = (samplesPerLine * (dropouts.fieldLine[dropoutNumber] + 1));

        // Calculate field position of dropout in the sample
        qreal startOfDropout = startOfLine + ((samplesPerLine / static_cast<qreal>(ldDecodeMetaData.getVideoParameters().fieldWidth)) * static_cast<qreal>(dropouts.startx[dropoutNumber]));
        qreal endOfDropout = startOfLine + ((samplesPerLine / static_cast<qreal>(ldDecodeMetaData.getVideoParameters().fieldWidth)) * static_cast<qreal>(dropouts.endx[dropoutNumber]));

        audioDropout.startSample = static_cast<qint32>(startOfDropout);
        audioDropout.endSample = static_cast<qint32>(endOfDropout);

        // Ensure that the dropout is of the minimum allowed length
        if ((audioDropout.endSample - audioDropout.startSample) < minimumDropoutLength) {
            audioDropout.endSample += minimumDropoutLength - (audioDropout.endSample - audioDropout.startSample);
        }

        // Can the dropout be concatenated with or within an existing dropout?
        bool duplicate = false;
        for (qint32 count = 0; count < fieldAudioDropouts.size(); count++) {
            if ((audioDropout.startSample >= fieldAudioDropouts[count].startSample) && (audioDropout.startSample - 1 <= fieldAudioDropouts[count].endSample)) {
                // If the current dropout end is further than the existing one, extend the existing dropout
                if (audioDropout.endSample > fieldAudioDropouts[count].endSample) fieldAudioDropouts[count].endSample = audioDropout.endSample;
                duplicate = true;
                break;
            }
        }

        // Store the dropout
        if (!duplicate) {
            fieldAudioDropouts.append(audioDropout);
        }
    }
}

// Method to correct an audio sample
void ProcessAudio::correctAudioDropout(qint32 fieldNumber, qint32 startSample, qint32 endSample)
{
    qint32 startLeftValue = 0;
    qint32 endLeftValue = 0;
    qreal stepLeftValue = 0;

    qint32 startRightValue = 0;
    qint32 endRightValue = 0;
    qreal stepRightValue = 0;

    qint32 numberOfSamples = (endSample - startSample);

    if (startSample > 0) {
        startLeftValue = fieldAudioData[startSample - 1].left;
        startRightValue = fieldAudioData[startSample - 1].right;
    }

    if (endSample < fieldAudioData.size()) {
        endLeftValue = fieldAudioData[endSample + 1].left;
        endRightValue = fieldAudioData[endSample + 1].right;
    }

    // Underflow check for start sample
    if (startSample == 0) {
        // Get the end sample from the previous field
        if (fieldNumber != 1) {
            QVector<AudioData> previousFieldAudioData = readFieldAudio(fieldNumber - 1);
            startLeftValue = previousFieldAudioData[previousFieldAudioData.size()].left;
            startRightValue = previousFieldAudioData[previousFieldAudioData.size()].right;
        } else {
            // There is no previous field, so there's not much that can be done
            startLeftValue = endLeftValue;
            startRightValue = endRightValue;
        }
    }

    // Overflow check for end sample
    if (endSample >= fieldAudioData.size()) {
        if (fieldNumber <= ldDecodeMetaData.getNumberOfFields()) {
            QVector<AudioData> previousFieldAudioData = readFieldAudio(fieldNumber + 1);
            startLeftValue = previousFieldAudioData[0].left;
            startRightValue = previousFieldAudioData[0].right;
        } else {
            // There is no next field, so there's not much that can be done
            endLeftValue = startLeftValue;
            endRightValue = startRightValue;
        }
    }

    stepLeftValue = static_cast<qreal>(endLeftValue - startLeftValue) / static_cast<qreal>(numberOfSamples);
    stepRightValue = static_cast<qreal>(endRightValue - startRightValue) / static_cast<qreal>(numberOfSamples);

    qreal currentLeftValue = startLeftValue + stepLeftValue;
    qreal currentRightValue = startRightValue + stepRightValue;

    for (qint32 sampleNumber = startSample; sampleNumber <= endSample; sampleNumber++) {
        fieldAudioData[sampleNumber].left = static_cast<qint16>(currentLeftValue);
        fieldAudioData[sampleNumber].right = static_cast<qint16>(currentRightValue);

        currentLeftValue += stepLeftValue;
        currentRightValue += stepRightValue;
    }
}

// Method to silence an audio sample
void ProcessAudio::silenceAudioSample(void)
{
    for (qint32 sampleNumber = 0; sampleNumber < fieldAudioData.size(); sampleNumber++) {
        fieldAudioData[sampleNumber].left = 0;
        fieldAudioData[sampleNumber].right = 0;
    }
}

// Method to write the audio data for a field
void ProcessAudio::writeFieldAudio(void)
{
    QByteArray rawData;
    rawData.resize(fieldAudioData.size() * 4);

    // Copy the fieldAudio vector into the raw data array
    qint16 *dataPointer = reinterpret_cast<qint16*>(rawData.data());
    qint32 rawDataPointer = 0;
    for (qint32 samplePointer = 0; samplePointer < fieldAudioData.size(); samplePointer++) {
        dataPointer[rawDataPointer++] = fieldAudioData[samplePointer].left;
        dataPointer[rawDataPointer++] = fieldAudioData[samplePointer].right;
    }

    // Write the raw data array to disc
    if (!audioOutputFile->write(rawData.data(), rawData.size())) {
        qWarning() << "Writing to output audio file failed!";
        return;
    }
}

// Method to get the audio data for a field
QVector<ProcessAudio::AudioData> ProcessAudio::readFieldAudio(qint32 fieldNumber)
{
    QVector<AudioData> readAudioData;
    videoParameters = ldDecodeMetaData.getVideoParameters();

    if (fieldNumber < 1 || fieldNumber > ldDecodeMetaData.getNumberOfFields()) {
        qCritical() << "ProcessAudio::readFieldAudio(): Requested field" << fieldNumber << "is out of bounds!";
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
            readAudioData.clear();
            return readAudioData;
    }

    // Resize the audio data to the length of the field
    readAudioData.resize(ldDecodeMetaData.getField(fieldNumber).audioSamples);

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
        readAudioData.clear();
        return readAudioData;
    }

    // Copy the raw data into the audioData vector
    qint16 *dataPointer = reinterpret_cast<qint16*>(rawData.data());
    for (qint32 samplePointer = 0; samplePointer < ldDecodeMetaData.getField(fieldNumber).audioSamples; samplePointer++) {
        readAudioData[samplePointer].left = dataPointer[(samplePointer * 2)];
        readAudioData[samplePointer].right = dataPointer[(samplePointer * 2) + 1];
    }

    return readAudioData;
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

void ProcessAudio::writeAudacityLabels(qint32 fieldNumber, bool labelEveryField)
{
    if (!labelEveryField && (ldDecodeMetaData.getField(fieldNumber).dropOuts.startx.size() == 0)) {
        // Field does not contain any dropouts, so no need to write anything
        return;
    }

    // Write the field's start and end sample position to the audacity label metadata
    qint64 fieldStartSample = sampleStartPosition[fieldNumber];
    qint64 fieldEndSample = fieldStartSample + ldDecodeMetaData.getField(fieldNumber).audioSamples - 1;
    writeAudacityMetadataLabel(fieldStartSample, fieldEndSample, "F#" + QString::number(fieldNumber));

    // Write the field's dropouts to the audacity label metadata
    for (qint32 dropoutNumber = 0; dropoutNumber < fieldAudioDropouts.size(); dropoutNumber++) {
        writeAudacityMetadataLabel(fieldAudioDropouts[dropoutNumber].startSample + fieldStartSample,
                                   fieldAudioDropouts[dropoutNumber].endSample + fieldStartSample,
                                   "DO#" + QString::number(dropoutNumber));
    }
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

