/************************************************************************

    efmdecoder.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019-2022 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "efmdecoder.h"

EfmDecoder::EfmDecoder()
{

}

bool EfmDecoder::startDecoding(QString inputEfmFilename, QString outputFilename,
                               bool concealAudio, bool silenceAudio, bool passThroughAudio,
                               bool pad, bool decodeAsData, bool noTimeStamp)
{
    if (inputEfmFilename.isEmpty()) {
        qDebug() << "EfmDecoder::startDecoding(): Input EFM filename is empty!";
        return false;
    }

    // Open the input EFM data file
    inputFileHandle.setFileName(inputEfmFilename);
    if (!inputFileHandle.open(QIODevice::ReadOnly)) {
        // Failed to open file
        qDebug() << "EfmDecoder::startDecoding(): Could not open EFM input file";
        return false;
    } else {
        qDebug() << "EfmDecoder::startDecoding(): Opened EFM input file";
    }

    // Open output file
    outputFileHandle.setFileName(outputFilename);
    if (outputFileHandle.exists()) outputFileHandle.remove();
    if (!outputFileHandle.open(QIODevice::WriteOnly)) {
        // Failed to open file
        qFatal("EfmDecoder::startDecoding(): Could not open output file - this is fatal!");
        return false;
    } else {
        qDebug() << "EfmDecoder::startDecoding(): Opened output file";
    }

    EfmProcess efmProcess;

    // Set the debug states - FIX THIS!
    efmProcess.setDebug(false, false, false, false, false, false);

    // Set the audio error treatment option
    F1ToAudio::ErrorTreatment errorTreatment = F1ToAudio::ErrorTreatment::conceal; // Default
    if (concealAudio) errorTreatment = F1ToAudio::ErrorTreatment::conceal;
    if (silenceAudio) errorTreatment = F1ToAudio::ErrorTreatment::silence;
    if (passThroughAudio) errorTreatment = F1ToAudio::ErrorTreatment::passThrough;

    // Set the conceal type option (THIS SHOULD BE REMOVED)
    F1ToAudio::ConcealType concealType = F1ToAudio::ConcealType::linear;

    efmProcess.setAudioErrorTreatment(errorTreatment, concealType);

    // Set the audio options
    efmProcess.setDecoderOptions(pad, decodeAsData, noTimeStamp);

    // Process the EFM
    efmProcess.startProcessing(&inputFileHandle, &outputFileHandle);

    // Close files
    inputFileHandle.close();
    outputFileHandle.close();

    // Report the final decode statistics to qInfo
    efmProcess.reportStatistics();

    return true;
}
