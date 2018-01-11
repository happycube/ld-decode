/************************************************************************

    tbc.cpp

    Time-Based Correction
    ld-decode - Software decode of Laserdiscs from raw RF
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode.

    ld-decode is free software: you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public License
    as published by the Free Software Foundation, either version 3 of
    the License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    Email: simon.inns@gmail.com

************************************************************************/

#include "tbc.h"
#include "../../deemp.h"

//
// Notes on video frequencies to help understand this code:
//
// NTSC ---
//
// NTSC has 525 scanlines per frame (483 visible and 42 in the Vertical Blanking Interval)
// Each frame has 2 fields with 262.5 scan lines in each field
//
// The field rate (Vfreq) of NTSC is 60 * (1000/1001) = 59.939 Hz (this is the root frequency from which all others are calculated)
// The frame rate of NTSC is (field rate / 2) = 29.97 Hz
//
// If there are 262.5 scan lines per field and 59.939 fields/sec, the line rate (Hfreq) is 262.5 * 59.939 = 15.734 KHz
//
// The colour sub-carrier is 455/2 times the line rate i.e. 15.734 KHz * (455/2) = 3.579485 MHz (or 315/88 MHz)
// The colour sub-carrier frequency is determined from the 'colour burst' signal which is 9 cycles of the
// sub-carrier used to encode the colour information (and is included at the 'start' of each video signal)
//
// The 'sync' signal precedes the colour burst signal and there is an exact amount of time between the start of the sync
// signal (known as the sync tip) and the start of the colour burst.
//
// If the line rate is 15734 Hz and the colour rate (aka dot-clock) is 3579485 Hz then the dot rate is 227.5 per line
//
// The colour rate is determined by the colour-burst signal which is 9 cycles long (and matches the frequency at which
// the colour is encoded (i.e. modulated) into the video signal that follows the burst).
//
// FSC (in this code) is the relative frequency of the sampling clock to the colour rate (this is important since
// 1 cycle of the colour sub-carrier is the smallest unit we need to measure in the video signal).
//
// If the colour sub-carrier is 3579485 Hz and the sampling clock is 28.635 MHz then the FSC is 8.0
// meaning that every 8 samples represent 1 cycle of the colour sub-carrier (as per the cxadc sampler).
// For the Domesday Duplicator the FSC is 8.9398 (32,000,000 / 3579485).
//
//
// PAL --
//
// PAL has 625 scanlines per frame (576 visible and 49 in the Vertical Blanking Interval)
// Each frame has 2 fields with 312.5 scan lines in each field
//
// The field rate (Vfreq) of PAL is 50 Hz
// The frame rate of PAL is (field rate / 2) = 25 Hz
//
// If there are 312.5 scan lines per field and 50 fields/sec, the line rate (Hfreq) is 312.5 * 50 = 15,625 KHz
//
// The colour sub-carrier is 4.43361875 MHz.
// The colour sub-carrier frequency is determined from the 'colour burst' signal which is 9 cycles of the
// sub-carrier used to encode the colour information (and is included at the 'start' of each video signal)
//
// The 'sync' signal precedes the colour burst signal and there is an exact amount of time between the start of the sync
// signal (known as the sync tip) and the start of the colour burst.
//
// If the line rate is 15625 Hz and the colour rate (aka dot-clock) is 4433618.75 Hz then the dot rate is 283.75 per line
// Note: The actual figure is 283.7516, but there is a 25 Hz offset included which causes the dot rate to be exactly 283.75
//
// The colour rate is determined by the colour-burst signal which is 9 cycles long (and matches the frequency at which
// the colour is encoded (i.e. modulated) into the video signal that follows the burst).
//
// FSC (in this code) is the relative frequency of the sampling clock to the colour rate (this is important since
// 1 cycle of the colour sub-carrier is the smallest unit we need to measure in the video signal).
//
// If the colour sub-carrier is 4433618.75 Hz and the sampling clock is 28.635 MHz then the FSC is 6.458
// meaning that every 6.458 samples represent 1 cycle of the colour sub-carrier (as per the cxadc sampler).
// For the Domesday Duplicator the FSC is 7.217 (32,000,000 / 4433618.75).

Tbc::Tbc()
{
    // Default configuration is NTSC capture from cxADC (8-bit 28.8MSPS):
    setTbcMode(ntsc_cxadc);

    // Global configuration
    setSourceVideoFile(""); // Default is empty
    setSourceAudioFile(""); // Default is empty
    setTargetVideoFile(""); // Default is empty
    setTargetAudioFile(""); // Default is empty

    setMagneticVideoMode(false);
    setFlipFields(false);
    setAudioOutputOnly(false);
    setPerformFreezeFrame(false);
    setRotDetectLevel(40.0);
    setSkipFrames(0);
    setMaximumFrames(0);

    // Note: the following settings are always false as they
    // point to stale code
    // TODO: Remove code completely (unless Chad needs it for something?)
    tbcConfiguration.performAutoRanging = false;
    tbcConfiguration.sevenFiveMode = false;
    tbcConfiguration.highBurst = false;
    tbcConfiguration.performDespackle = false;

    // Globals for processAudio()
    processAudioState.afreq = 48000;
    processAudioState.prev_time = -1;
    processAudioState.nextAudioSample = 0;
    processAudioState.prev_loc = -1;
    processAudioState.prev_index = 0;
    processAudioState.prev_i = 0;
    processAudioState.firstloc = -1;

    processAudioState.a_read = 0;
    processAudioState.v_read = 0;
    processAudioState.va_ratio = 80;

    // Globals for processAudioSample()
    processAudioState.audioChannelOneFilter = new Filter(f_fmdeemp);
    processAudioState.audioChannelTwoFilter = new Filter(f_fmdeemp);
    processAudioState.audioOutputBufferPointer = 0;

    // Globals to do with the line processing functions
    processLineState.frameno = -1;

    // Auto-ranging state
    autoRangeState.low = 65535;
    autoRangeState.high = 0;
    autoRangeState.inputMaximumIreLevel = 327.68;
    autoRangeState.inputMinimumIreLevel = (autoRangeState.inputMaximumIreLevel * 20);	// IRE == -40
}

// TODO: Split the file handling logic from the processing logic; this function is too
// general purpose and long at the moment...
qint32 Tbc::execute(void)
{
    // Show some info in the output
    qInfo() << "Laserdisc time-based correction (TBC)";
    qInfo() << "Part of the Software Decode of Laserdiscs project";
    qInfo() << "(c)2018 Chad Page and Simon Inns";
    qInfo() << "LGPLv3 Open-Source - github: https://github.com/happycube/ld-decode";
    qInfo() << "";

    // Show the TBC's user-configuration so we can work out what a user did when
    // analysing debug output...
    qInfo() << "TBC options are as follows:";

    // Show which mode the TBC is processing in:
    if (tbcConfiguration.tbcMode == ntsc_cxadc)  qInfo() << "  TBC mode is NTSC 8-bit 28.8MSPS";
    if (tbcConfiguration.tbcMode == ntsc_domdup) qInfo() << "  TBC mode is NTSC 16-bit 30MSPS";
    if (tbcConfiguration.tbcMode == pal_cxadc)   qInfo() << "  TBC mode is PAL 8-bit 28.8MSPS";
    if (tbcConfiguration.tbcMode == pal_cxadc)   qInfo() << "  TBC mode is PAL 16-bit 30MSPS";

    qInfo() << "  Video input frequency (FSC) =" << (double)tbcConfiguration.videoInputFrequencyInFsc;
    qInfo() << "  Write on field =" << tbcConfiguration.writeOnField;
    qInfo() << "  Flip fields is" << tbcConfiguration.fieldFlip;
    qInfo() << "  Audio only is" << tbcConfiguration.audioOutputOnly;
    qInfo() << "  Freeze-frame is" << tbcConfiguration.freezeFrame;
    qInfo() << "  Laser-rot detection level =" << (double)tbcConfiguration.rotDetectLevel;
    qInfo() << "  Skip frames =" << (double)tbcConfiguration.skipFrames;
    qInfo() << "  Maximum frames =" << (double)tbcConfiguration.maximumFrames;
    qInfo() << "";

    // Define our video and audio input buffers
    QVector<quint16> videoInputBuffer;
    QVector<QVector<quint16 > > videoOutputBuffer; // A Vector of 505 Vectors * 844 pixels
    QVector<double_t> audioInputBuffer;

    // Define out video and audio output buffers
    QVector<quint16> audioOutputBuffer;

    // Note: any variables dealing with file length should be 64 bits, otherwise we can
    // run into issues with big files on modern operating systems...

    // All vector operations are defined in terms of elements (rather than bytes) - this
    // is to make the code independent from the actual storage type chosen (i.e. quint16 or similar)

    // Define the required number of elements in the video and audio buffers
    qint32 videoInputBufferNumberOfElements;
    qint32 audioInputBufferNumberOfElements;
    qint32 audioOuputBufferNumberOfElements;
    qint32 videoOutputBufferNumberOfLines;
    qint32 videoOutputBufferNumberOfSamples;

    if (tbcConfiguration.isNtsc) {
        // NTSC configuration
        // TODO: Where do 1100 and 40 come from?
        // Note from Chad: some of the #'s like 1100/40 are arbitrary, different ones might work just as well.
        // NTSC cxadc is 910 input samples per line, 910 * 1100 = 1,001,000 / 16 = 62562.5 (i.e. not divisible by 16...)
        // So... what we are really doing is setting our buffer length to approximately 1100 lines of video, or about 2 frames of NTSC
        videoInputBufferNumberOfElements = ((qint64)tbcConfiguration.inputSamplesPerVideoLine * 1100);
        audioInputBufferNumberOfElements = ((qint64)tbcConfiguration.inputSamplesPerVideoLine * 1100) / 40;
        audioOuputBufferNumberOfElements = 512; // Fixed length
        videoOutputBufferNumberOfLines = tbcConfiguration.numberOfVideoLinesPerFrame; // This is set to 505 lines for NTSC

        // 4 * 211 = 844 - This is the dots per line (pixels) in our output buffer?
        // Makes no sense to me at all... surely this should be a ratio of the expected input dots per line?
        videoOutputBufferNumberOfSamples = (tbcConfiguration.videoOutputFrequencyInFsc * 211); // Number of video samples
    } else {
        // PAL configuration - DOES NOT WORK AT ALL
        videoInputBufferNumberOfElements = ((qint64)tbcConfiguration.inputSamplesPerVideoLine * 1300);
        audioInputBufferNumberOfElements = ((qint64)tbcConfiguration.inputSamplesPerVideoLine * 1300) / 40;
        audioOuputBufferNumberOfElements = 512; // Fixed length
        videoOutputBufferNumberOfLines = tbcConfiguration.numberOfVideoLinesPerFrame; // The display is 610 lines for PAL
        videoOutputBufferNumberOfSamples = (tbcConfiguration.videoOutputFrequencyInFsc * 288); // number of visible lines per field /2
    }

    // Ensure that our buffer vectors are the correct length
    videoInputBuffer.resize(videoInputBufferNumberOfElements);
    audioInputBuffer.resize(audioInputBufferNumberOfElements);
    audioOutputBuffer.resize(audioOuputBufferNumberOfElements);

    videoOutputBuffer.resize(videoOutputBufferNumberOfLines);
    // As this is a vector of vectors, we have to resize each vector individually
    // The vector represents the video 'lines' and the quint16 vector represents the samples
    for (qint32 line = 0; line < videoOutputBufferNumberOfLines; line++)
        videoOutputBuffer[line].resize(videoOutputBufferNumberOfSamples);
    // This basically gives us videoOutputBuffer[lines][samples], i.e. a 2D 'array'

    // Define the file handles for the video and audio buffers
    // Set them to NULL in case the handle isn't used (so we can detect that later...)
    QFile* audioInputFileHandle = NULL;
    QFile* videoInputFileHandle = NULL;
    QFile* videoOutputFileHandle = NULL;
    QFile* audioOutputFileHandle = NULL;

    // Flag set if we should process audio data (and all the required
    // file names are supplied)
    bool processAudioData = false;

    // Set the maximum frames and skip frames configuration
    // TODO: Move this logic into the 'set' functions
    tbcConfiguration.maximumFrames = 1 << 28;
    if (tbcConfiguration.skipFrames > 0) tbcConfiguration.maximumFrames += tbcConfiguration.skipFrames;


    // Open the video and audio input files ready for use --------------------------------------------

    // The TBC process expects a raw binary file containing a sequence of
    // unsigned 16-bit integer values representing the RF sample as proecessed
    // by the ld-decoder application (video signal is bandpassed and FM
    // demodulated).  The unsigned integer values are offset-centre with the
    // DC-offset of the signal at 32767 (for Domesday Duplicator) - 8-bit centred
    // at 128 if using the old TV capture card ADC.

    // Do we have a file name for the video file?
    if (tbcConfiguration.sourceVideoFileName.isEmpty()) {
        // No source video file name was specified, using stdin instead
        videoInputFileHandle = new QFile;
        if (!videoInputFileHandle->open(stdin, QIODevice::ReadOnly)) {
            // Failed to open stdin
            qWarning() << "Could not open stdin...";
            return -1;
        }
        qInfo() << "Reading video data from stdin";
    } else {
        // Open video file as for reading (quint16 data)
        videoInputFileHandle = new QFile(tbcConfiguration.sourceVideoFileName);
        if (!videoInputFileHandle->open(QIODevice::ReadOnly)) {
            // Failed to open video file
            qWarning() << "Could not open specified video file";
            return -1;
        }
        qInfo() << "Reading video data from" << tbcConfiguration.sourceVideoFileName;
    }

    // The source audio file is as per the video file (described above), however
    // the audio has been low-passed (to remove the video signal).  Note that the
    // signal contains both channel 1 and channel 2 audio combined and therefore
    // must be band-passed into individual channels before further processing
    //
    // Band-passing would be better performing in the ld-decoder process rather than
    // in the TBC, but it is what it is

    // Do we have a file name for the audio input file?
    if (tbcConfiguration.sourceAudioFileName.isEmpty()) {
        // No file to process...
        qDebug() << "The audio input file name was not set";
        processAudioData = false;
    } else {
        // Open audio file for reading (quint16 data)
        audioInputFileHandle = new QFile(tbcConfiguration.sourceAudioFileName);
        if (!audioInputFileHandle->open(QFile::ReadOnly)) {
            // Failed to open audio file
            qWarning() << "Could not open specified audio file";
            return -1;
        } else {
            processAudioData = true; // Flag that audio data should be processed
            qInfo() << "Reading audio data from" << tbcConfiguration.sourceAudioFileName;

            // Do we have a file name for the audio output file?
            if (tbcConfiguration.targetAudioFileName.isEmpty()) {
                // No audio output file name specified...
                qDebug() << "The audio output file name was not set (will not process audio)";
                processAudioData = false;
            } else {
                // Attempt to open the audio output file
                audioOutputFileHandle = new QFile(tbcConfiguration.targetAudioFileName);

                // Check if the file was opened
                if (!audioOutputFileHandle->open(QIODevice::WriteOnly)) {
                    // Failed to open file
                    qWarning() << "Could not open audio output file";
                    return -1;
                }
            }
        }
    }

    // Do we have a file name for the output video file?
    if (tbcConfiguration.targetVideoFileName.isEmpty()) {
        // No target video file name was specified, using stdout instead
        videoOutputFileHandle = new QFile;
        if (!videoOutputFileHandle->open(stdout, QIODevice::WriteOnly)) {
            // Failed to open stdout
            qWarning() << "Could not open stdout";
            return -1;
        }
        qInfo() << "Writing video data to stdout";
    } else {
        // Open target video file for writing (quint16 data)
        videoOutputFileHandle = new QFile(tbcConfiguration.targetVideoFileName);
        if (!videoOutputFileHandle->open(QIODevice::WriteOnly)) {
            // Failed to open video output file
            qWarning() << "Could not open specified video output file";
            return -1;
        }
        qInfo() << "Writing video data to" << tbcConfiguration.targetVideoFileName;
    }


    // Perform the input video and audio file processing --------------------------------------------
    size_t numberOfAudioBufferElementsProcessed = 0;

    // Buffer tracking variables
    qint32 videoElementsInBuffer = 0;
    qint32 audioElementsInBuffer = 0;

    // Get the input video file size (for progress reporting)
    qint64 inputFileSize = videoInputFileHandle->bytesAvailable();

    // File tracking variables
    qint64 receivedVideoBytes = 0;

    do {
        qDebug() << "Beginning video TBC processing loop with videoElementsInBuffer =" <<
                    videoElementsInBuffer << "( buffer size is" << videoInputBuffer.size() << ")";

        // Calculate processing progress in % (cannot do this for stdin...)
        if (!tbcConfiguration.sourceVideoFileName.isEmpty()) {
            double_t percentDone = 100.0 - (100.0 / (double_t)inputFileSize) *
                    (double_t)videoInputFileHandle->bytesAvailable();
            qInfo() << (qint32)percentDone << "% of input file processed";
        }

        // Fill the video buffer from the video input file
        while ((videoElementsInBuffer < videoInputBuffer.size()) && (!videoInputFileHandle->atEnd())) {
            qDebug() << "Requesting" << (videoInputBuffer.size() - videoElementsInBuffer) <<
                        "elements from video file to fill video buffer";

            // Read from the video input file and store in the video buffer vector
            // This operation uses bytes, so we multiply the elements by the size of the data-type
            receivedVideoBytes = videoInputFileHandle->read(reinterpret_cast<char *>(videoInputBuffer.data()) +
                                                            (videoElementsInBuffer * sizeof(quint16)),
                                                         ((videoInputBuffer.size() - videoElementsInBuffer) * sizeof(quint16)));

            // If received bytes is -1, the video readRawData operation failed for some unknown reason
            // If received bytes is 0, it's probably because we are reading from stdin with nothing avaiable
            if (receivedVideoBytes < 0) {
                qCritical() << "readRawData() operation on video input file returned error - aborting";
                return -1;
            }
            qDebug() << "Received" << (receivedVideoBytes / sizeof(quint16)) << "elements (" << receivedVideoBytes <<
                        "bytes ) from file read operation";

            // Add the received elements count to the video elements in buffer count
            videoElementsInBuffer += (qint32)(receivedVideoBytes / sizeof(quint16));
        }

        // Are we processing audio data?
        if (processAudioData) {
            qDebug() << "Requesting" << (audioInputBuffer.size() - audioElementsInBuffer) <<
                        "elements from audio file to fill audio buffer";

            // Read from the audio input file and store in the audio buffer vector
            // This operation uses bytes, so we multiply the elements by the size of the data-type
            qint64 receivedAudioBytes =
                    audioInputFileHandle->read(reinterpret_cast<char *>(audioInputBuffer.data()) +
                                               (audioElementsInBuffer * sizeof(double_t)),
                                               ((audioInputBuffer.size() - audioElementsInBuffer) * sizeof(double_t)));

            // If received bytes is -1, the readRawData operation failed for some unknown reason
            // If received bytes is 0, it's probably because we are reading from stdin with nothing avaiable
            if (receivedAudioBytes < 0) {
                qCritical() << "readRawData() operation on audio input file returned error - aborting";
                return -1;
            }
            qDebug() << "Received" << (receivedAudioBytes / sizeof(double_t)) << "elements (" <<
                        receivedAudioBytes << "bytes ) from file read operation";

            // Add the received elements count to the video elements in buffer count
            audioElementsInBuffer += (qint32)(receivedAudioBytes / sizeof(double_t));
        }

        // Only perform processing if there's something to process
        if (receivedVideoBytes > 0) {
            // Perform automatic ranging on the input video data?
            if (tbcConfiguration.performAutoRanging) {
                // Perform auto range of input video data
                qDebug() << "Performing auto ranging...";
                autoRange(videoInputBuffer);
            }

            // Process the video and audio buffer (only the number of elements read from the file are processed,
            // not the whole buffer)
            qDebug() << "Processing the video and audio buffers...";
            bool videoOutputBufferReady = false;
            bool audioOutputBufferReady = false;

            qint32 numberOfVideoBufferElementsProcessed =
                    processVideoAndAudioBuffer(videoInputBuffer, videoElementsInBuffer,
                                               audioInputBuffer, processAudioData,
                                               &videoOutputBufferReady, &audioOutputBufferReady,
                                               videoOutputBuffer, audioOutputBuffer);

            qDebug() << "Processed" << numberOfVideoBufferElementsProcessed << "elements from video buffer";

            // Write the video frame buffer to disk?
            if (videoOutputBufferReady && numberOfVideoBufferElementsProcessed > 0) {
                if (!tbcConfiguration.audioOutputOnly) {
                    qDebug() << "Writing frame data to disc";

                    // Note: in a 2D vector only the vector is in continuous memory
                    // not the vector of vectors, so we have to write each contained
                    // vector seperately here...
                    for (qint32 line = 0; line < videoOutputBufferNumberOfLines; line++) {
                        videoOutputFileHandle->write(reinterpret_cast<char *>(videoOutputBuffer[line].data()), videoOutputBuffer[line].size() * sizeof(quint16));
                    }
                } else qDebug() << "Audio only selected - discarding video frame data";

                // Note: this writes a complete buffer at the end of the file even if
                // the buffer isn't completely full. Causes the size of file to be a little
                // bit larger than the original TBC version.

                // Clear the video output buffer
                //memset(videoOutputBuffer, 0, sizeof(videoOutputBuffer));
                for (qint32 line = 0; line < videoOutputBufferNumberOfLines; line++) {
                    videoOutputBuffer[line].clear();
                    videoOutputBuffer[line].resize(videoOutputBufferNumberOfSamples);
                }
            }

            // Write the audio output buffer to disk?
            if (audioOutputBufferReady && numberOfVideoBufferElementsProcessed > 0) {
                qDebug() << "Writing audio data to disc";
                audioOutputFileHandle->write(reinterpret_cast<char *>(audioOutputBuffer.data()), audioOutputBuffer.size() * sizeof(quint16));

                // Note: this writes a complete buffer at the end of the file even if
                // the buffer isn't completely full. Causes the size of file to be a little
                // bit larger than the original TBC version.

                // Clear the audio output buffer
                audioOutputBuffer.clear();
                audioOutputBuffer.resize(audioOuputBufferNumberOfElements);
            }

            // Check if the processing found no video in the current buffer... and discard the buffer if required
            if (numberOfVideoBufferElementsProcessed <= 0) {
                qDebug() << "No video detected in video buffer, discarding buffer data"; // skipping ahead

                // Set the number of processed bytes to the whole buffer, so all data will be shifted back
                numberOfVideoBufferElementsProcessed = videoInputBuffer.size();
            }

            // These v_read/a_read variables seem to be used by both processVideoAndAudio and processAudio
            // as part of the processings... but they are not passed, they are globals.  Messy
            // They are also only set on the second-pass of those procedures... hopefully the defaults are sane?
            // Not sure what they are actually for - probably tracking the audio data vs the video data
            processAudioState.v_read += numberOfVideoBufferElementsProcessed;
            numberOfAudioBufferElementsProcessed =
                    (processAudioState.v_read / processAudioState.va_ratio) - processAudioState.a_read;
            processAudioState.a_read += numberOfAudioBufferElementsProcessed;

            // If the current buffer doesn't contain enough data for a complete line, the buffer is shifted around to
            // the beginning of the detected line (detected by the processVideoAndAudioBuffer function) and then refilled
            // to ensure the rest of the line data is in the buffer the next time it is processed

            // Shift back the contents of videoBuffer
            qDebug() << "Shifting back the video buffer contents by" <<
                        numberOfVideoBufferElementsProcessed << "elements";

            // We need to remove (videoBufferNumberOfElements - (videoProcessLengthInBytes / sizeof(quint16))
            // elements from the start of the video buffer (as they are already processed)
            videoInputBuffer.remove(0, numberOfVideoBufferElementsProcessed);

            // Now we adjust videoBytesReceived to reflect the number of elements still in the buffer
            // (based on the new size of the buffer due to the remove() operation)
            videoElementsInBuffer = videoInputBuffer.size();

            // Now we resize the video buffer back to its original length
            videoInputBuffer.resize(videoInputBufferNumberOfElements);

            // Are we processing audio?
            if (processAudioData) {
                // Shift back the audio data buffer by the same amount as the video buffer
                qDebug() << "Shifting back the audio buffer contents by" <<
                            numberOfVideoBufferElementsProcessed << "elements";

                audioInputBuffer.remove(0, numberOfAudioBufferElementsProcessed);
                audioElementsInBuffer = audioInputBuffer.size();
                audioInputBuffer.resize(audioInputBufferNumberOfElements);
            }
        } else qInfo() << "Nothing received from the video input file/stdin";
    } while ((!videoInputFileHandle->atEnd()) && (receivedVideoBytes > 0)); // Keep going until we hit the end of the video input file

    qDebug() << "Closing open files...";

    // Close the video input file handle
    if (videoInputFileHandle->isOpen()) videoInputFileHandle->close();

    // Close the video output file handle
    if (videoOutputFileHandle->isOpen()) videoOutputFileHandle->close();

    // Only close the audio input file handle if it was used
    if (audioInputFileHandle != NULL) {
        if (audioInputFileHandle->isOpen()) audioInputFileHandle->close();
    }

    // Only close the audio output file handle if it was used
    if (audioOutputFileHandle != NULL) {
        if (audioOutputFileHandle->isOpen()) audioOutputFileHandle->close();
    }

    // Exit with success
    qInfo() << "Processing complete";
    return 0;
}

// Private functions -------------------------------------------------------------------------------------

// This function automatically finds the input range and
// calculates where low (-40 IRE) and high (100 IRE) is in the signal
//
// Result is stored in these two globals:
//      inputMaximumIreLevel
//      inputMinimumIreLevel
//
// Returns:
//      videoSyncLevel
//      videoInputBuffer (by reference)
quint16 Tbc::autoRange(QVector<quint16> &videoInputBuffer)
{
    QVector<double_t> longSyncFilterResult(videoInputBuffer.size());
    bool fullagc = true; // Note: this was a passed parameter, but it was always true
    qint32 lowloc = -1;
    qint32 checklen = (qint32)(tbcConfiguration.videoInputFrequencyInFsc * 4);

    if (!fullagc) { // Note: Never used as fullagc is always true...
        autoRangeState.low = 65535;
        autoRangeState.high = 0;
    }

    qDebug() << "Scale before auto-ranging is =" << (double)autoRangeState.inputMinimumIreLevel << ':' <<
                (double)autoRangeState.inputMaximumIreLevel;

    // Phase 1:  Get the low (-40 IRE) and high (?? IRE) values
    // Note: this code is quite slow...
    for (int currentVideoBufferElement = 0;
         currentVideoBufferElement < videoInputBuffer.size();
         currentVideoBufferElement++) {
        longSyncFilterResult[currentVideoBufferElement] =
                autoRangeState.longSyncFilter->feed(videoInputBuffer[currentVideoBufferElement]);

        // TODO: Where does 256 come from? - as the videoInputFrequency is a small (double_t) number
        // it's likely that 256 is a scaling factor?
        if ((currentVideoBufferElement > (tbcConfiguration.videoInputFrequencyInFsc * 256)) &&
                (longSyncFilterResult[currentVideoBufferElement] < autoRangeState.low) &&
                (longSyncFilterResult[currentVideoBufferElement - checklen] < autoRangeState.low)) {
            if (longSyncFilterResult[currentVideoBufferElement - checklen] >
                    longSyncFilterResult[currentVideoBufferElement])
                autoRangeState.low = longSyncFilterResult[currentVideoBufferElement - checklen];
            else
                autoRangeState.low = longSyncFilterResult[currentVideoBufferElement];

            lowloc = currentVideoBufferElement;
        }

        if ((currentVideoBufferElement > (tbcConfiguration.videoInputFrequencyInFsc * 256)) &&
                (longSyncFilterResult[currentVideoBufferElement] > autoRangeState.high) &&
                (longSyncFilterResult[currentVideoBufferElement - checklen] > autoRangeState.high)) {
            if (longSyncFilterResult[currentVideoBufferElement - checklen] <
                    longSyncFilterResult[currentVideoBufferElement])
                autoRangeState.high = longSyncFilterResult[currentVideoBufferElement - checklen];
            else
                autoRangeState.high = longSyncFilterResult[currentVideoBufferElement];
        }
    }

    // Phase 2: Attempt to figure out the 0 IRE porch near the sync
    if (!fullagc) { // Note: Never used as fullagc is always true...
        qint32 gap = autoRangeState.high - autoRangeState.low;
        qint32 nloc;

        for (nloc = lowloc;
             // TODO: Where does 320 come from?
             (nloc > lowloc - (tbcConfiguration.videoInputFrequencyInFsc * 320)) &&
             (longSyncFilterResult[nloc] < (autoRangeState.low + (gap / 8))); nloc--);

        qDebug() << nloc << (lowloc - nloc) / (double)tbcConfiguration.videoInputFrequencyInFsc << (double)longSyncFilterResult[nloc];

        nloc -= (tbcConfiguration.videoInputFrequencyInFsc * 4);
        qDebug() << nloc << (lowloc - nloc) / (double)tbcConfiguration.videoInputFrequencyInFsc << (double)longSyncFilterResult[nloc];

        qDebug() << "Scale before auto-ranging is =" << (double)autoRangeState.inputMinimumIreLevel <<
                    ':' << (double)autoRangeState.inputMaximumIreLevel;

        autoRangeState.inputMaximumIreLevel = (longSyncFilterResult[nloc] - autoRangeState.low) /
                ((tbcConfiguration.sevenFiveMode) ? 47.5 : 40.0);
        autoRangeState.inputMinimumIreLevel = autoRangeState.low -
                (20 * autoRangeState.inputMaximumIreLevel); // Should be in the range of -40 IRE to -60 IRE

        if (autoRangeState.inputMinimumIreLevel < 1) autoRangeState.inputMinimumIreLevel = 1;
        qDebug() << "Scale after auto-ranging is =" << (double)autoRangeState.inputMinimumIreLevel << ':' <<
                    (double)autoRangeState.inputMaximumIreLevel;
    } else {
        autoRangeState.inputMaximumIreLevel = (autoRangeState.high - autoRangeState.low) / 140.0;
    }

    autoRangeState.inputMinimumIreLevel = autoRangeState.low;	// -40 IRE to -60 IRE
    if (autoRangeState.inputMinimumIreLevel < 1) autoRangeState.inputMinimumIreLevel = 1;

    qDebug() << "Scale after auto-ranging is =" << (double)autoRangeState.inputMinimumIreLevel << ':'
             << (double)autoRangeState.inputMaximumIreLevel << " low:" << (double)autoRangeState.low <<
                (double)autoRangeState.high;

    return autoRangeState.inputMinimumIreLevel + (autoRangeState.inputMaximumIreLevel * 20);
}

// Process a buffer of video and audio data
// The function seems to work out where the video frames begin and end in
// the video buffer and then passes each line of video (and corresponding 'line'
// of audio) to the processAudio and processLine functions to be further processed
// into 'frames' of data.
//
// Returns:
//      The number of videoInputBuffer elements that were processed
//      A flag indicating if the video frame buffer is ready to be written to disc (by reference)
//      A flag indicating if the audio buffer is ready to be written to disc (by reference)
//      The videoOutputBuffer (by reference)
//      The audioOutputBuffer (by reference)
qint32 Tbc::processVideoAndAudioBuffer(QVector<quint16> videoInputBuffer, qint32 videoInputBufferElementsToProcess,
                                           QVector<double_t> audioInputBuffer, bool processAudioData,
                                           bool *isVideoOutputBufferReadyForWrite, bool *isAudioOutputBufferReadyForWrite,
                                           QVector<QVector<quint16 > > &videoOutputBuffer, QVector<quint16> &audioOutputBuffer)
{
    // Set the write buffer flag to a default of false (do not write)
    *isVideoOutputBufferReadyForWrite = false;
    *isAudioOutputBufferReadyForWrite = false;

    double_t lineBuffer[tbcConfiguration.inputSamplesPerVideoLine];
    double_t horizontalSyncs[tbcConfiguration.numberOfVideoLinesPerField];
    qint32 field = -1;
    qint32 offset;

    // Starts looking for a vsync 500 samples into the video input buffer (about 1 NTSC frame)
    // 600 samples for PAL
    if (tbcConfiguration.isNtsc) offset = 500; else offset = 600;

    // Note: The video output buffer should be cleared by the calling function (process())
    // before invoking this function

    // Keep going until we have a valid field
    while (field < 1) {
        // Try to find a vertical sync in the inputBuffer and place the position in 'verticalSync'
        qint32 verticalSync = findVsync(videoInputBuffer.data(), videoInputBufferElementsToProcess, offset);

        bool oddEven = verticalSync > 0; // VSync is for odd field if true (false = even field)
        verticalSync = abs(verticalSync);

        if (oddEven) qDebug() << "findvsync (odd) at" << verticalSync;
        else qDebug() << "findvsync (even) at" << verticalSync;

        // If the sync is for an even field and this is the first pass of the while() loop
        if ((oddEven == false) && (field == -1)) {
            // An NTSC field is 262.5 lines
            // So; this moves us approximately 240 lines ahead in the video input buffer (for NTSC)
            qint32 skipAhead;
            if (tbcConfiguration.isNtsc) skipAhead = 240; else skipAhead = 300;
            return verticalSync + (tbcConfiguration.videoInputFrequencyInFsc * tbcConfiguration.dotsPerVideoLine * skipAhead);
        }

        // Process skip-frames mode - zoom forward an entire frame
        if (processLineState.frameno < tbcConfiguration.skipFrames) {
            processLineState.frameno++;
            // An NTSC frame is 525 lines
            // So; this moves us approximately 510 lines ahead in the video input buffer (for NTSC)
            qint32 skipAhead;
            if (tbcConfiguration.isNtsc) skipAhead = 510; else skipAhead = 610;
            return verticalSync + (tbcConfiguration.videoInputFrequencyInFsc * tbcConfiguration.dotsPerVideoLine * skipAhead);
        }

        field++;

        // Zoom ahead to close to the first full proper sync
        if (oddEven) {
            // This is timing information.... work it out!
            // TODO: What is 750? about 3.2 NTSC lines since x * FSC = x dots
            verticalSync = abs(verticalSync) + (750 * tbcConfiguration.videoInputFrequencyInFsc);
        } else {
            // TODO: What is 871? about 3.8 NTSC lines
            verticalSync = abs(verticalSync) + (871 * tbcConfiguration.videoInputFrequencyInFsc);
        }

        // Find all of the horizontal syncs for the current field and place in horizontalSyncs[]
        // horizontalSync[] value is negative if the sync was not found
        findHsyncs(videoInputBuffer.data(), videoInputBufferElementsToProcess, verticalSync, horizontalSyncs);
        bool isLineBad[tbcConfiguration.numberOfVideoLinesPerField-1];

        // Store any errors in isLineBad[] and store the absolute of the horizontal
        // sync end locations in horizontalSyncs[]
        for (qint32 line = 0; line < tbcConfiguration.numberOfVideoLinesPerField-1; line++) {
            isLineBad[line] = horizontalSyncs[line] < 0;
            horizontalSyncs[line] = abs(horizontalSyncs[line]);
        }

        // Determine vsync->0/7.5IRE transition point (TODO: break into function)
        for (qint32 line = 0; line < tbcConfiguration.numberOfVideoLinesPerField-1; line++) {
            if (isLineBad[line] == true) continue;

            double_t previous = 0;
            double_t startSync = -1;
            double_t endSync = -1;
            quint16 tPoint = ire_to_in(-20);

            // Find beginning of horizontal sync
            autoRangeState.f_endsync->clear(0);
            previous = 0;
            for (qint32 i = horizontalSyncs[line] - (20 * tbcConfiguration.videoInputFrequencyInFsc);
                 i < horizontalSyncs[line] - (8 * tbcConfiguration.videoInputFrequencyInFsc); i++) {
                double_t current = autoRangeState.f_endsync->feed(videoInputBuffer[i]);

                if ((previous > tPoint) && (current < tPoint)) {
                    // qDebug() << "B" << i << line << hsyncs[line];
                    double_t diff = current - previous;
                    startSync = ((i - 8) + (tPoint - previous) / diff);

                    // qDebug() << prev << tpoint << cur << hsyncs[line];
                    break;
                }
                previous = current;
            }

            // Find end of horizontal sync
            autoRangeState.f_endsync->clear(0);
            previous = 0;
            for (qint32 counter = horizontalSyncs[line] - (2 * tbcConfiguration.videoInputFrequencyInFsc);
                 counter < horizontalSyncs[line] + (4 * tbcConfiguration.videoInputFrequencyInFsc); counter++) {
                double_t current = autoRangeState.f_endsync->feed(videoInputBuffer[counter]);

                if ((previous < tPoint) && (current > tPoint)) {
                    // qDebug() << "E" << line << hsyncs[line];
                    double_t difference = current - previous;
                    endSync = ((counter - 8) + (tPoint - previous) / difference);

                    // qDebug() << prev << tpoint << cur << hsyncs[line];
                    break;
                }
                previous = current;
            }

            qDebug() << "Sync S" << line << (double)startSync << (double)endSync << (double)(endSync - startSync);

            // TODO: Why 15.75 and 17.25?
            // Detect if syncs is too long (must be between 15.75 and 17.25 dots?)
            if ((!inRangeCF(endSync - startSync, 15.75, 17.25)) || (startSync == -1) || (endSync == -1)) {
                isLineBad[line] = true;
            } else {
                horizontalSyncs[line] = endSync;
            }
        }

        // We need semi-correct lines for the next phases
        correctDamagedHSyncs(horizontalSyncs, isLineBad);

        bool phaseFlip;
        double_t bLevel[tbcConfiguration.numberOfVideoLinesPerField-1];
        double_t tpOdd = 0, tpEven = 0;
        qint32 nOdd = 0, nEven = 0; // need to track these to exclude bad lines
        double_t bPhase = 0;
        // detect alignment (undamaged lines only)
        for (qint32 line = 0; line < 64; line++) {
            double_t line1 = horizontalSyncs[line], line2 = horizontalSyncs[line + 1];

            if (isLineBad[line] == true) {
                qDebug() << "Error on line" << line;
                continue;

            }

            // Colour burst detection/correction
            scale(videoInputBuffer.data(), lineBuffer, line1, line2, tbcConfiguration.dotsPerVideoLine * tbcConfiguration.videoInputFrequencyInFsc);
            if (!burstDetect2(lineBuffer, tbcConfiguration.videoInputFrequencyInFsc, 4, bLevel[line], bPhase, phaseFlip)) {
                qDebug() << "Error (no burst) on line" << line;
                isLineBad[line] = true;
                continue; // Exits the for loop...
            }

            if (line % 2) {
                tpOdd += phaseFlip;
                nOdd++;
            } else {
                tpEven += phaseFlip;
                nEven++;
            }

            qDebug() << "Burst" << line << (double)line1 << (double)line2 << (double)bLevel[line] << (double)bPhase;
        }

        bool fieldPhase = fabs(tpEven / nEven) < fabs(tpOdd / nOdd);
        qDebug() << "Phases:" << nEven + nOdd << (double)(tpEven / nEven) << (double)(tpOdd / nOdd) << fieldPhase;

        for (qint32 pass = 0; pass < 4; pass++) {
               for (qint32 line = 0; line < tbcConfiguration.numberOfVideoLinesPerField-1; line++) {
            bool lPhase = ((line % 2) == 0);
            if (fieldPhase) lPhase = !lPhase;

            // TODO: Why 14.0?
            double_t line1c = horizontalSyncs[line] + ((horizontalSyncs[line + 1] - horizontalSyncs[line]) * 14.0 / tbcConfiguration.dotsPerVideoLine);

            scale(videoInputBuffer.data(), lineBuffer, horizontalSyncs[line], line1c, 14 * tbcConfiguration.videoInputFrequencyInFsc);
            if (!burstDetect2(lineBuffer, tbcConfiguration.videoInputFrequencyInFsc, 4, bLevel[line], bPhase, phaseFlip)) {
                isLineBad[line] = true;
                continue; // Exits the for loop...
            }

            // TODO: why .260?
            double_t tgt = .260;
//			if (bphase > .5) tgt += .5;

            double_t adj = (tgt - bPhase) * 8;

            //qDebug() << "ADJ" << line << pass << bphase << tgt << adj;
            horizontalSyncs[line] -= adj;
           }
        }

        correctDamagedHSyncs(horizontalSyncs, isLineBad);

        // Final output (this had a bug in the original code (line < 252) which caused oline to overflow to 505 -
        // which causes a segfault in the line "frameBuffer[oline][t] = (quint16)clamp(o, 1, 65535);"
        for (qint32 line = 0; line < tbcConfiguration.numberOfVideoLinesPerField-2; line++) {
            double_t line1 = horizontalSyncs[line], line2 = horizontalSyncs[line + 1];
            qint32 oline = 3 + (line * 2) + (oddEven ? 0 : 1);

            // 33 degree shift
            double_t shift33 = (33.0 / 360.0) * 4 * 2;

            // TODO: Remove?
            if (tbcConfiguration.videoInputFrequencyInFsc == 4) {
                // XXX THIS IS BUGGED, but works
                shift33 = (107.0 / 360.0) * 4 * 2;
            }

            double_t pt = -12 - shift33; // align with previous-gen tbc output

            scale(videoInputBuffer.data(), lineBuffer, line1 + pt, line2 + pt, 910, 0);

            // 525 is the NTSC number of lines
            double_t framePosition = (line / 525.0) + processLineState.frameno + (field * .50);

            if (!field) framePosition -= .001;

            // Process audio?
            if (processAudioData) {
                *isAudioOutputBufferReadyForWrite =
                        processAudio(framePosition,processAudioState.v_read + horizontalSyncs[line],
                                     audioInputBuffer.data(), audioOutputBuffer.data());
            }
            bool lphase = ((line % 2) == 0);
            if (fieldPhase) lphase = !lphase;
            videoOutputBuffer[oline][0] = (lphase == 0) ? 32768 : 16384;
            videoOutputBuffer[oline][1] = bLevel[line] * (327.68 / autoRangeState.inputMaximumIreLevel); // ire_to_out(in_to_ire(blevel[line]));

            if (isLineBad[line]) {
                        videoOutputBuffer[oline][3] = videoOutputBuffer[oline][5] = 65000;
                    videoOutputBuffer[oline][4] = videoOutputBuffer[oline][6] = 0;
            }

            // TODO: What is 844? It's the number of samples in the output video buffer?
            for (qint32 t = 4; t < videoOutputBuffer[0].size(); t++) {
                double_t o = lineBuffer[t];
                if (tbcConfiguration.performAutoRanging) o = ire_to_out(in_to_ire(o));

                videoOutputBuffer[oline][t] = (quint16)clamp(o, 1, 65535);
            }
        }
        if (tbcConfiguration.isNtsc) offset = abs(horizontalSyncs[250]); // Set offset to the end of the 250th line detected
        else offset = abs(horizontalSyncs[300]); // Set offset to the end of the 300th line detected
        // i.e. move video buffer forward slightly less than one NTSC/PAL field

        qDebug() << "New offset is" << offset;
    } // on to the next field...

    qDebug() << "Field processed, performing post-processing actions";

    // Perform despackle of field?
    if (tbcConfiguration.performDespackle) {
        despackle(videoOutputBuffer);
    }

    // Decode field VBI data
    decodeVbiData(videoOutputBuffer);

    // TODO: Add check for white flag back in here (as it's not really part of the VBI decoding function
    // and should be split by itself)

    // Increment the frame number
    processLineState.frameno++;

    // Flag that the video frame buffer is ready to be written to disk:
    *isVideoOutputBufferReadyForWrite = true;

    qDebug() << "Field processing complete";

    // Done
    return offset;
}

// Find the sync signal
qint32 Tbc::findSync(quint16 *videoInputBuffer, qint32 videoLength)
{
    // TODO: Why 50?
    qint32 tgt = 50;

    return findSync(videoInputBuffer, videoLength, tgt);
}

// TODO:
// When combined with auto-ranging this function can generate a segfault
// I haven't tracked down the root cause yet though.  All vectors/arrays
// seem to be in bounds.
//
// findSync looks for the next sync pulse in the video input buffer (which
// could be either a hsync or vsync) and returns the location in the input
// buffer in which the detected sync ends.
//
// I *think* tgt is the maximum length of a sync pulse in number of input
// samples; if the sync is longer it results in an error
qint32 Tbc::findSync(quint16 *videoInputBuffer, qint32 videoLength, qint32 tgt)
{
    qint32 pad = 96;
    qint32 result = -1;

    qint32 to_min = ire_to_in(-45), to_max = ire_to_in(-35);
    qint32 err_min = ire_to_in(-55), err_max = ire_to_in(30);

    qint32 circularBufferLength = tgt * 3;
    QVector<bool> circularBuffer(circularBufferLength);
    QVector<bool> circularBufferError(circularBufferLength);

    qint32 count = 0, errorCount = 0, peak = 0, locationOfPeak = 0;

    for (qint32 videoSample = 0; (result == -1) && (videoSample < videoLength); videoSample++) {
        // Is input sample >= -45 IRE and <= -35 IRE?
        bool isInputSampleInRange = (videoInputBuffer[videoSample] >= to_min) && (videoInputBuffer[videoSample] < to_max);

        // Is input sample <= -55 IRE or >= 30 IRE?
        bool isInputSampleOutOfRange = (videoInputBuffer[videoSample] <= err_min) || (videoInputBuffer[videoSample] >= err_max);

        if (isInputSampleInRange) count = count - circularBuffer[videoSample % circularBufferLength] + 1;
        else count = count - circularBuffer[videoSample % circularBufferLength];
        circularBuffer[videoSample % circularBufferLength] = isInputSampleInRange;

        if (isInputSampleOutOfRange) errorCount = errorCount - circularBufferError[videoSample % circularBufferLength] + 1;
        else errorCount = errorCount - circularBufferError[videoSample % circularBufferLength];
        circularBufferError[videoSample % circularBufferLength] = isInputSampleOutOfRange;

        if (count > peak) {
            peak = count;
            locationOfPeak = videoSample;
        } else if ((count > tgt) && ((videoSample - locationOfPeak) > pad)) {
            result = locationOfPeak;

            if ((tbcConfiguration.videoInputFrequencyInFsc > 4) && (errorCount > 1)) {
                qDebug() << "Horizontal Error HERR" << errorCount;
                result = -result;
            }
        }
    }

    if (result == -1) qDebug() << "Not found" << peak << locationOfPeak;

    return result;
}

// This could probably be used for more than just field det, but eh
//
// Returns the number of samples between begin and end that are at the correct IRE level range for a sync pulse
// This will give you the relative length of the sync pulse?
qint32 Tbc::countSlevel(quint16 *videoBuffer, qint32 begin, qint32 end)
{
    const quint16 to_min = ire_to_in(-45), to_max = ire_to_in(-35);
    qint32 count = 0;

    for (qint32 i = begin; i < end; i++) {
        count += (videoBuffer[i] >= to_min) && (videoBuffer[i] < to_max);
    }

    return count;
}

// Returns index of end of VSYNC - negative if _ field
qint32 Tbc::findVsync(quint16 *videoBuffer, qint32 videoLength)
{
    // Default value - offset into video input buffer
    qint32 offset = 0;

    return findVsync(videoBuffer, videoLength, offset);
}

// Note: This function has an out-of-bounds error that can cause a segfault.  Need to track
// down the cause.  Seems to happen when loc=505 and i=5 (when auto-ranging is configured true)
//
// Returns:
//      Returns positive number for odd field and negative number for even field
//      The absolute of the returned number is the location in the input video buffer of the end of sync signal
qint32 Tbc::findVsync(quint16 *videoInputBuffer, qint32 videoInputBufferNumberOfElements, qint32 offset)
{
    // Set the approximate video field length in input samples (i.e. 8.0 * 227.5 * 280)
    // 280 is the NTSC field length of 262.5 lines plus a bit of error margin
    qint32 approxInputSamplesPerField;
    if (tbcConfiguration.isNtsc) approxInputSamplesPerField = tbcConfiguration.videoInputFrequencyInFsc * tbcConfiguration.dotsPerVideoLine * 280;
    else approxInputSamplesPerField = tbcConfiguration.videoInputFrequencyInFsc * tbcConfiguration.dotsPerVideoLine * 320;

    // If there aren't enough input samples to contain a video field, give up...
    if (videoInputBufferNumberOfElements < approxInputSamplesPerField) return -1;

    qint32 pulse_ends[6];
    qint32 sampleLength = videoInputBufferNumberOfElements;

    // vertical syncs are widely spaced in the sample (since they are only at the beginning of each field,
    // horizontal syncs are closer together (since they are at the beginning of each line)
    //
    // A vertical sync consists of:
    //      Pre-equalizing pulses (6 to start scanning odd lines, 5 to start scanning even lines)
    //      Long-sync pulses (5 pulses)
    //      Post-equalizing pulses (5 to start scanning odd lines, 4 to start scanning even lines)

    qint32 startLocation = offset;
    for (qint32 i = 0; i < 6; i++) {
        // 32xFSC is *much* shorter, but it shouldn't get confused for an hsync -
        // and on rotted disks and ones with burst in vsync, this helps

        // Get the end location of the next sync in the input video buffer
        qint32 syncEndLocation = abs(findSync(&videoInputBuffer[startLocation], sampleLength, 32 * tbcConfiguration.videoInputFrequencyInFsc));

        // Set pulse_ends[i] to the location of the sync end in the input video buffer
        pulse_ends[i] = syncEndLocation + startLocation;
        qDebug() << "Pulse ends"<< pulse_ends[i];

        // Move to the end of the detected sync
        startLocation += syncEndLocation;

        // Limit the next sync search to 3840 samples which is about 480 lines of NTSC at 8 FSC
        if (tbcConfiguration.isNtsc) sampleLength = tbcConfiguration.videoInputFrequencyInFsc * 480;
        else sampleLength = tbcConfiguration.videoInputFrequencyInFsc * 580;
    }
    qint32 result = pulse_ends[5];

    // Determine line type (even or odd?)
    // TODO: What is 127.5 and 4.5?
    // Note from Chad: 127.5 and 4.5 are there to help lock down the size of the sync pulse... in vsync they can run very long
    qint32 before_end = pulse_ends[0] - (127.5 * tbcConfiguration.videoInputFrequencyInFsc);
    qint32 before_start = before_end - (tbcConfiguration.dotsPerVideoLine * 4.5 * tbcConfiguration.videoInputFrequencyInFsc);

    // Range check these variables as they can end up negative and cause a segfault
    if (before_end < 0) before_end = 0;
    if (before_start < 0) before_start = 0;

    // Count the length of the sync signal before the end point
    qint32 pulseLengthBefore = countSlevel(videoInputBuffer, before_start, before_end);

    qint32 after_start = pulse_ends[5];
    qint32 after_end = after_start + (tbcConfiguration.dotsPerVideoLine * 4.5 * tbcConfiguration.videoInputFrequencyInFsc);

    // Count the length of the sync signal after the end point
    qint32 pulseLengthAfter = countSlevel(videoInputBuffer, after_start, after_end);

    qDebug() << "Before/after:" << pulse_ends[0] + offset << pulse_ends[5] + offset << pulseLengthBefore << pulseLengthAfter;

    // Returns positive number for odd field and negative number for even field
    // The absolute of the returned number is the location in the input video buffer of the end of sync signal
    if (pulseLengthBefore < pulseLengthAfter) result = -result;

    return result;
}

// Overload for findHsyncs - sets the number of lines to a field
bool Tbc::findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *horizontalSyncs)
{
    // Default value (which is fixed, but should be based on the video buffer length or something?)
    qint32 nlines = tbcConfiguration.numberOfVideoLinesPerField;

    return findHsyncs(videoBuffer, videoLength, offset, horizontalSyncs, nlines);
}

// Returns the end location of each linein horizontalSyncs[]
// Returned location is negative if an error was detected for the video line
// (caller responsible for freeing array)
bool Tbc::findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *horizontalSyncs, qint32 nlines)
{
    // sanity check (XXX: assert!)
    if (videoLength < (nlines * tbcConfiguration.videoInputFrequencyInFsc * tbcConfiguration.dotsPerVideoLine))
        return false;

    qint32 loc = offset;

    for (qint32 line = 0; line < nlines; line++) {
        qint32 syncend = findSync(&videoBuffer[loc], tbcConfiguration.dotsPerVideoLine * 3 * tbcConfiguration.videoInputFrequencyInFsc,
                               8 * tbcConfiguration.videoInputFrequencyInFsc);

        // gap is one line of video
        double_t gap = tbcConfiguration.dotsPerVideoLine * tbcConfiguration.videoInputFrequencyInFsc;

        qint32 err_offset = 0;
        while (syncend < -1) {
            qDebug() << "Error found on line" << line << syncend;
            err_offset += gap;
            syncend = findSync(&videoBuffer[loc] + err_offset, tbcConfiguration.dotsPerVideoLine * 3 * tbcConfiguration.videoInputFrequencyInFsc,
                               8 * tbcConfiguration.videoInputFrequencyInFsc);
            qDebug() << "Error syncend" << syncend;
        }

        // If it skips a scan line, fake it
        if ((line > 0) && (line < nlines) && (syncend > (40 * tbcConfiguration.videoInputFrequencyInFsc))) {
            horizontalSyncs[line] = -(abs(horizontalSyncs[line - 1]) + gap);
            qDebug() << "XX" << line << loc << syncend << (double)horizontalSyncs[line];
            syncend -= gap;
            loc += gap;
        } else {
            horizontalSyncs[line] = loc + syncend;
            if (err_offset) horizontalSyncs[line] = -horizontalSyncs[line];

            if (syncend != -1) {
                // Skip 200 dots beyond the end of the last sync (slightly less than 1 NTSC line)
                if (tbcConfiguration.isNtsc) loc += fabs(syncend) + (200 * tbcConfiguration.videoInputFrequencyInFsc);
                else loc += fabs(syncend) + (280 * tbcConfiguration.videoInputFrequencyInFsc);
            } else {
                loc += gap;
            }
        }
    }

    return horizontalSyncs;
}

// correct damaged hsyncs by interpolating neighboring lines
void Tbc::correctDamagedHSyncs(double_t *hsyncs, bool *err)
{
    for (qint32 line = 1; line < tbcConfiguration.numberOfVideoLinesPerField-2; line++) {
        if (err[line] == false) continue;

        qint32 lprev;
        qint32 lnext;

        for (lprev = line - 1; (err[lprev] == true) && (lprev >= 0); lprev--);
        for (lnext = line + 1; (err[lnext] == true) && (lnext < tbcConfiguration.numberOfVideoLinesPerField-1); lnext++);

        // This shouldn't happen...
        if ((lprev < 0) || (lnext == tbcConfiguration.numberOfVideoLinesPerField-1)) continue;

        double_t linex = (hsyncs[line] - hsyncs[0]) / line;

        qDebug() << "Fixed:" << line << (double)linex << (double)hsyncs[line] <<
                    (double)(hsyncs[line] - hsyncs[line - 1]) << lprev << lnext ;

        double_t lavg = (hsyncs[lnext] - hsyncs[lprev]) / (lnext - lprev);
        hsyncs[line] = hsyncs[lprev] + (lavg * (line - lprev));
        qDebug() << "hsyncs:" << (double)hsyncs[line];
    }
}

// Process a video frame's worth of audio
//
// Returns:
//      true - if audio buffer is full (and ready to be written to disc)
//      false - audio buffer not ready
bool Tbc::processAudio(double_t frameBuffer, qint64 loc, double_t *audioInputBuffer, quint16 *audioOutputBuffer)
{
    bool isAudioBufferReadyForWrite = false;
    double_t time = frameBuffer / (30000.0 / 1001.0); // TODO: What are these constants?
    // Note from Chad: 30000/1001.0 is the NTSC frame rate (~29.976), 525 is the # of lines in an NTSC frame

    // Default firstloc if required
    if (processAudioState.firstloc == -1) processAudioState.firstloc = loc;

    if (processAudioState.prev_time >= 0) {
        while (processAudioState.nextAudioSample < time) {
            double_t i1 = (processAudioState.nextAudioSample - processAudioState.prev_time) /
                    (time - processAudioState.prev_time);
            qint64 i = (i1 * (loc - processAudioState.prev_loc)) + processAudioState.prev_loc;

            if (i < processAudioState.v_read) {
                isAudioBufferReadyForWrite = processAudioSample(processAudioState.audioChannelOneFilter->filterValue(),
                                   processAudioState.audioChannelTwoFilter->filterValue(), audioOutputBuffer);
            } else {
                qint64 index = (i / processAudioState.va_ratio) - processAudioState.a_read;
                if (index >= (qint64)(sizeof(audioInputBuffer) / sizeof(double_t))) {
                    qDebug() << "Audio error" << (double)frameBuffer << (double)time << (double)i1
                             << i << index << (sizeof(audioInputBuffer) / sizeof(double_t));
                    index = (sizeof(audioInputBuffer) / sizeof(double_t)) - 1;
                }
                double_t channelOne = audioInputBuffer[index * 2], channelTwo = audioInputBuffer[(index * 2) + 1];
                // TODO: Where does 525.0 come from?
                double_t frameb = (double_t)(i - processAudioState.firstloc) / (double_t)tbcConfiguration.inputSamplesPerVideoLine / 525.0; // TODO: What are these constants?
                qDebug() << "Audio" << (double)frameBuffer << loc << (double)frameb << (double)i1 << i <<
                            i - processAudioState.prev_i <<
                            index << index - processAudioState.prev_index << (double)channelOne << (double)channelTwo;
                processAudioState.prev_index = index;
                processAudioState.prev_i = i;
                isAudioBufferReadyForWrite = processAudioSample(channelOne, channelTwo, audioOutputBuffer);
            }

            processAudioState.nextAudioSample += 1.0 / processAudioState.afreq;
        }
    }

    processAudioState.prev_time = time;
    processAudioState.prev_loc = loc;

    return isAudioBufferReadyForWrite;
}

// Process a sample of audio (from what to what?)
//
// Returns:
//      true - if audio buffer is full (and ready to be written to disc)
//      false - audio buffer not ready
bool Tbc::processAudioSample(double_t channelOne, double_t channelTwo, quint16 *audioOutputBuffer)
{
    // 300000 is likely to do with the video frame rate
    channelOne = processAudioState.audioChannelOneFilter->feed(channelOne * (65535.0 / 300000.0));
    channelOne += 32768;

    channelTwo = processAudioState.audioChannelTwoFilter->feed(channelTwo * (65535.0 / 300000.0));
    channelTwo += 32768;

    audioOutputBuffer[processAudioState.audioOutputBufferPointer * 2] = clamp(channelOne, 0, 65535);
    audioOutputBuffer[(processAudioState.audioOutputBufferPointer * 2) + 1] = clamp(channelTwo, 0, 65535);

    // Need to pass this buffer back to the main process function and write it to
    // disk there rather than being buried here...
    processAudioState.audioOutputBufferPointer++;
    if (processAudioState.audioOutputBufferPointer == 256) {
        qDebug() << "Audio buffer is ready to be written";
        return true;
    }

    return false;
}

// If value is less than lowValue, function returns lowValue
// If value is greated than highValue, function returns highValue
// otherwise function returns value
inline double_t Tbc::clamp(double_t value, double_t lowValue, double_t highValue)
{
        if (value < lowValue) return lowValue;
        else if (value > highValue) return highValue;
        else return value;
}

// Convert from input scale to IRE
inline double_t Tbc::in_to_ire(quint16 level)
{
    if (level == 0) return -100;

    return -40 + ((double_t)(level - autoRangeState.inputMinimumIreLevel) / autoRangeState.inputMaximumIreLevel);
}

// Convert from IRE to input scale
inline quint16 Tbc::ire_to_in(double_t ire)
{
    if (ire <= -60) return 0;

    return clamp(((ire + 40) * autoRangeState.inputMaximumIreLevel) + autoRangeState.inputMinimumIreLevel, 1, 65535);
}

// Convert from IRE to output scale
inline quint16 Tbc::ire_to_out(double_t ire)
{
    if (ire <= -60) return 0;

    return clamp(((ire + 60) * 327.68) + 1, 1, 65535);
}

// Convert from output level to IRE
double_t Tbc::out_to_ire(quint16 in)
{
    return (in / 327.68) - 60;
}

// No idea what this function is for
inline double_t Tbc::peakdetect_quad(double_t *y)
{
    return (2 * (y[2] - y[0]) / (2 * (2 * y[1] - y[0] - y[2])));
}

// Note: Processing performance could probably be improved by changing
// the interpolate to act directly on the data (rather than one element
// at a time)...

// Perform bicubic interpolation of the passed values
// taken from http://www.paulinternet.nl/?page=bicubic
inline double_t Tbc::cubicInterpolate(quint16 *y, double_t x)
{
    double_t p[4];
    p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

    return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
}

// This function takes a video line that is the wrong length
// and interpolates the line to the correct (predicted) length
void Tbc::scale(quint16 *buf, double_t *outbuf, double_t start, double_t end,
                           double_t outlen)
{
    // Defaults
    double_t offset = 0;
    qint32 from = 0;
    qint32 to = -1;

    scale(buf, outbuf, start, end, outlen, offset, from, to);
}

void Tbc::scale(quint16 *buf, double_t *outbuf, double_t start, double_t end,
                           double_t outlen, double_t offset)
{
    // Defaults
    qint32 from = 0;
    qint32 to = -1;

    scale(buf, outbuf, start, end, outlen, offset, from, to);
}

void Tbc::scale(quint16 *buf, double_t *outbuf, double_t start, double_t end,
                           double_t outlen, double_t offset, qint32 from, qint32 to)
{
    double_t inlen = end - start;
    double_t perpel = inlen / outlen;

    if (to == -1) to = (int)outlen;

    double_t p1 = start + (offset * perpel);
    for (qint32 i = from; i < to; i++) {
        qint32 index = (qint32)p1;
        if (index < 1) index = 1;

        outbuf[i] = clamp(cubicInterpolate(&buf[index - 1], p1 - index), 0, 65535);

        p1 += perpel;
    }
}

// Function returns true if v is within the range of l to h
bool Tbc::inRange(double_t v, double_t l, double_t h)
{
    return ((v > l) && (v < h));
}

// Function returns true if v is within the range of l to h
// Note: l and h are scaled according to the video input frequency in FSC (i.e. video dots)
bool Tbc::inRangeCF(double_t v, double_t l, double_t h)
{
    return inRange(v, l * tbcConfiguration.videoInputFrequencyInFsc, h * tbcConfiguration.videoInputFrequencyInFsc);
}

// Function to detect the colour burst signal's location within a line of video
// Could do with a description of how it works?
bool Tbc::burstDetect2(double_t *line, qint32 freq, double_t _loc, double_t &plevel,
                           double_t &pphase, bool &phaseflip)
{
    qint32 len = (6 * freq);
    qint32 loc = _loc * freq;
    double_t start = 0 * freq;

    double_t peakh = 0, peakl = 0;
    qint32 npeakh = 0, npeakl = 0;
    double_t lastpeakh = -1, lastpeakl = -1;

    double_t highmin = ire_to_in(tbcConfiguration.highBurst ? 11 : 9);
    double_t highmax = ire_to_in(tbcConfiguration.highBurst ? 23 : 22);
    double_t lowmin = ire_to_in(tbcConfiguration.highBurst ? -11 : -9);
    double_t lowmax = ire_to_in(tbcConfiguration.highBurst ? -23 : -22);

    int begin = loc + (start * freq);
    int end = begin + len;

    // first get average (probably should be a moving one)

    double_t avg = 0;
    for (qint32 i = begin; i < end; i++) {
        avg += line[i];
    }
    avg /= (end - begin);

    // or we could just ass-u-me IRE 0...
    //avg = ire_to_in(0);

    // get first and last ZC's, along with first low-to-high transition
    double_t firstc = -1;
    double_t firstc_h = -1;

    double_t avg_htl_zc = 0, avg_lth_zc = 0;
    qint32 n_htl_zc = 0, n_lth_zc = 0;

    for (qint32 i = begin ; i < end; i++) {
        if ((line[i] > highmin) && (line[i] < highmax) && (line[i] > line[i - 1]) && (line[i] > line[i + 1])) {
            peakh += line[i];
            npeakh++;
            lastpeakh = i; lastpeakl = -1;
        } else if ((line[i] < lowmin) && (line[i] > lowmax) && (line[i] < line[i - 1]) && (line[i] < line[i + 1])) {
            peakl += line[i];
            npeakl++;
            lastpeakl = i; lastpeakh = -1;
        } else if (((line[i] >= avg) && (line[i - 1] < avg)) && (lastpeakl != -1)) {
            // XXX: figure this out quadratically
            double_t diff = line[i] - line[i - 1];
            double_t zc = i - ((line[i] - avg) / diff);

            if (firstc == -1) firstc = zc;
            if (firstc_h == -1) firstc_h = zc;

            double_t ph_zc = (zc / freq) - floor(zc / freq);
            // XXX this has a potential edge case where a legit high # is wrapped
            if (ph_zc > .9) ph_zc -= 1.0;
            avg_lth_zc += ph_zc;
            n_lth_zc++;

            //qDebug() << "ZCH" << i << line[i - 1] << avg << line[i] << zc << ph_zc;
        } else if (((line[i] <= avg) && (line[i - 1] > avg)) && (lastpeakh != -1)) {
            // XXX: figure this out quadratically
            double_t diff = line[i] - line[i - 1];
            double_t zc = i - ((line[i] - avg) / diff);

            if (firstc == -1) firstc = zc;

            double_t ph_zc = (zc / freq) - floor(zc / freq);
            // XXX this has a potential edge case where a legit high # is wrapped
            if (ph_zc > .9) ph_zc -= 1.0;
            avg_htl_zc += ph_zc;
            n_htl_zc++;

            //qDebug() << "ZCL" << i << line[i - 1] << avg << line[i] << zc <<  ph_zc;
        }
    }

//	qDebug() << "ZC" << n_htl_zc << n_lth_zc;

    if (n_htl_zc) {
        avg_htl_zc /= n_htl_zc;
    } else {
        qDebug() << "Burst 1 return";
        return false;
    }

    if (n_lth_zc) {
        avg_lth_zc /= n_lth_zc;
    } else {
        qDebug() << "Burst 2 return";
        return false;
    }

    //qDebug() << "PDETECT" << fabs(avg_htl_zc - avg_lth_zc) <<
    //                         n_htl_zc << avg_htl_zc << n_lth_zc << avg_lth_zc;

    double_t pdiff = fabs(avg_htl_zc - avg_lth_zc);

    if ((pdiff < .35) || (pdiff > .65)) {
        qDebug() << "Burst detect error, pdiff out of range, pdiff =" << (double)pdiff;
        return false;
    }

    plevel = ((peakh / npeakh) - (peakl / npeakl)) / 4.3;

    if (avg_htl_zc < .5) {
        pphase = (avg_htl_zc + (avg_lth_zc - .5)) / 2;
        phaseflip = false;
    } else {
        pphase = (avg_lth_zc + (avg_htl_zc - .5)) / 2;
        phaseflip = true;
    }

    return true;
}

// Describe me
bool Tbc::isPeak(QVector<double_t> p, qint32 i)
{
    return (fabs(p[i]) >= fabs(p[i - 1])) && (fabs(p[i]) >= fabs(p[i + 1]));
}

// This function was a bit odd... it references deltaFrame and
// deltaFrameFilter (in the original code) - but never actually
// stores anything in the arrays (and they are huge arrays).
// So I've removed them...
//
// Returns:
//      videoOutputBuffer (by reference)
//
// Note from Chad: despackle is the de-rotting code
void Tbc::despackle(QVector<QVector<quint16 > > &videoOutputBuffer)
{
    // Create a vector and copy the contents of videoOutputBuffer into it
    QVector<QVector<quint16 > > originalVideoOutputBuffer(videoOutputBuffer);

    qint32 outputX = videoOutputBuffer[0].size(); // Same as number of samples
    qint32 outputY = videoOutputBuffer.size(); // Same as number of lines

    for (qint32 inputY = 22; inputY < outputY; inputY++) {
        double_t rotDetect = tbcConfiguration.rotDetectLevel * autoRangeState.inputMaximumIreLevel;

        for (qint32 inputX = 60; inputX < outputX - 16; inputX++) {

            if ((out_to_ire(videoOutputBuffer[inputY][inputX]) < -20) ||
                    (out_to_ire(videoOutputBuffer[inputY][inputX]) > 140)) {

                qDebug() << "Despackle R" <<
                            inputY <<
                            inputX <<
                            (double)rotDetect;

                for (qint32 m = inputX - 4; (m < (inputX + 14)) && (m < outputX); m++) {
                    double_t tmp = (((double_t)originalVideoOutputBuffer[inputY - 2][m - 2]) +
                            ((double_t)originalVideoOutputBuffer[inputY - 2][m + 2])) / 2;

                    if (inputY < (outputY - 3)) {
                        tmp /= 2;
                        tmp += ((((double_t)originalVideoOutputBuffer[inputY + 2][m - 2]) +
                                ((double_t)originalVideoOutputBuffer[inputY + 2][m + 2])) / 4);
                    }

                    videoOutputBuffer[inputY][m] = clamp(tmp, 0, 65535);
                }
                inputX = inputX + 14;
            }
        }
    }
}

// Read data encoded in the VBI
// TODO: This function doesn't work correctly...
quint32 Tbc::readVbiData(QVector<QVector<quint16 > > videoOutputBuffer, quint16 line)
{
    qDebug() << "Attempting to read VBI data in line" << line;

    // 3,500,000 cycles/sec
    // Our output sampling rate is 4x the colour burst frequency
    double_t outputSampleRateMHz;
    if (tbcConfiguration.isNtsc) outputSampleRateMHz = tbcConfiguration.videoOutputFrequencyInFsc * (315.0 / 88.0);
    else outputSampleRateMHz = tbcConfiguration.videoOutputFrequencyInFsc * 4.43361875;

    qint32 first_bit = -1; // 108 - outputSampleRateMHz;
    quint32 out = 0;

    QVector<double_t> deltaLine;
    deltaLine.resize(videoOutputBuffer[0].size()); // Same as number of samples;

    // This generates the difference (delta) between two video lines in the output
    // buffer - combining the two video fields... is this really what we want?
    for (qint32 i = 1; i < videoOutputBuffer[0].size() - 1; i++) {
        deltaLine[i] = videoOutputBuffer[line][i] - videoOutputBuffer[line][i - 1];
    }

    // find first positive transition (exactly halfway into bit 0 which is *always* 1)
    // TODO: Why 140 and 327.68?
    // Note from Chad: 70->140 seemed a reasonable range to look for the first white pulse.  Could be replaced by much more exact timing
    for (qint32 i = 70; (first_bit == -1) && (i < 140); i++) {
        // is the current dot a peak and is it > 32768?
        if (isPeak(deltaLine, i) && (deltaLine[i] > 32768.00)) {
            first_bit = i;
        }
    }
    if (first_bit < 0) {
        qDebug() << "No valid data found in line" << line;
        return 0;
    }

    for (qint32 i = 0; i < 24; i++) {
        qint32 rloc = -1, loc = (first_bit + (i * 2 * outputSampleRateMHz)); // 2 is 2 uSecs?
        double_t rpeak = -1;

        for (qint32 h = loc - 8; (h < loc + 8); h++) {
            if (isPeak(deltaLine, h)) {
                if (fabs(deltaLine[h]) > rpeak) {
                    rpeak = fabs(deltaLine[h]);
                    rloc = h;
                }
            }
        }

        if (rloc == -1) rloc = loc;

        out |= (deltaLine[rloc] > 0) ? (1 << (23 - i)) : 0;
        qDebug() << "VBI Delta (line" << line << "):" << i << loc << (double)deltaLine[loc] << rloc << (double)deltaLine[rloc] <<
                    (double)(deltaLine[rloc] / autoRangeState.inputMaximumIreLevel) << out;

        if (!i) first_bit = rloc;
    }
    qDebug() << "VBI data in line" << line << "is hex:" << hex << out;

    return out;
}

// Used by the decodeVBI function for something...
// Note from Chad: the white flag check is there for CAV film disks to determine if a field is the beginning of a pulled down frame or not.
bool Tbc::checkWhiteFlag(qint32 l, QVector<QVector<quint16 > > videoOutputBuffer)
{
    qint32 wc = 0;

    // TODO: Why 100, 800 and 200?
    for (qint32 i = 100; i < 800; i++) { // TODO: verify constants
        if (out_to_ire(videoOutputBuffer[l][i]) > 80) wc++;
        if (wc >= 200) return true;
    }

    return false;
}

// Decode VBI data
// Decodes the VBI data based on the information in the videoOutputBuffer
// and then writes the decode VBI codes back into the videoOutputBuffer (which is an
// odd way of doing things really)
//
// Returns:
//      videoOutputBuffer (by reference)
void Tbc::decodeVbiData(QVector<QVector<quint16 > > &videoOutputBuffer)
{
    // For both NTSC and PAL discs there can be a maximum of 3 lines containing
    // data.  The line number is relative to the field order in which the disc
    // was encoded:
    //
    //   NTSC: 16, 17, 18 (or in reverse field order 279, 280, 281)
    //    PAL: 16, 17, 18 (or in reverse field order 329, 330, 331)
    //
    // Since the field order is not determined here, the VBI will always appear
    // on lines 16, 17 and 18 in the videoOutputBuffer (unless something flips the
    // field order).

    // TODO notes:
    // The original code was reading lines 14 to 20 and I'm not sure why...
    // It could be that the outputBuffer has both fields interlaced together
    // meaning that the order is:
    //
    // 279, 16, 280, 17, 281, 18 (field 1 first)
    // 16, 279, 17, 280, 18, 281 (field 0 first)
    //
    // but which field order (or why it starts on line 14) - I don't understand
    //
    // The original code was also interpreting frame numbers as decimal values -
    // and they are hex values... so the readVbiData function isn't working anyway...
    // making it all very tough to debug right now.

    quint32 dataOnLine16 = readVbiData(videoOutputBuffer, 16);
    quint32 dataOnLine17 = readVbiData(videoOutputBuffer, 17);
    quint32 dataOnLine18 = readVbiData(videoOutputBuffer, 18);

    // Show the VBI data in the debug output
    qInfo() << "VBI data:" << hex <<
                ": 16 =" << dataOnLine16 <<
                ": 17 =" << dataOnLine17 <<
                ": 18 =" << dataOnLine18;

    // Interpret the VBI data (just to get the debug right now)
    InterpretVbi interpretVbi(dataOnLine16, dataOnLine17, dataOnLine18);

    // Show VBI data in debug
    switch(interpretVbi.getDiscType()) {
    case InterpretVbi::DiscTypes::cav:
        qInfo() << "Disc type is CAV";
        break;
    case InterpretVbi::DiscTypes::clv:
        qInfo() << "Disc type is CLV";
        break;
    case InterpretVbi::DiscTypes::unknownType:
        qInfo() << "Disc type is unknown";
        break;
    }

    // Debug for CAV disks
    if (interpretVbi.getDiscType() == InterpretVbi::DiscTypes::cav) {
        if (interpretVbi.isPictureNumberAvailable())
            qInfo() << "Picture number is:" << interpretVbi.getPictureNumber();
    }

//    flags = (clv ? FRAME_INFO_CLV : 0) | (even ? FRAME_INFO_CAV_EVEN : 0) |
//            (odd ? FRAME_INFO_CAV_ODD : 0) | (cx ? FRAME_INFO_CX : 0);
//    flags |= checkWhiteFlag(4, videoOutputBuffer) ? FRAME_INFO_WHITE_EVEN : 0;
//    flags |= checkWhiteFlag(5, videoOutputBuffer) ? FRAME_INFO_WHITE_ODD  : 0;

//    qDebug() << "VBI Status" << hex << flags << dec << "chapter" << chap;

//    videoOutputBuffer[0][12] = chap;
//    videoOutputBuffer[0][13] = flags;
//    videoOutputBuffer[0][14] = fnum >> 16;
//    videoOutputBuffer[0][15] = fnum & 0xffff;
//    videoOutputBuffer[0][16] = clv_time >> 16;
//    videoOutputBuffer[0][17] = clv_time & 0xffff;
}

// Configuration parameter handling functions -----------------------------------------

// Set TBC mode
void Tbc::setTbcMode(TbcModes setting)
{
    switch(setting) {
    case ntsc_cxadc:
        // Configure the TBC
        tbcConfiguration.tbcMode = ntsc_cxadc;
        tbcConfiguration.isNtsc = true;

        tbcConfiguration.videoInputFrequencyInFsc = 8.0;
        tbcConfiguration.videoOutputFrequencyInFsc = 4.0;

        tbcConfiguration.numberOfVideoLinesPerFrame = 505;
        tbcConfiguration.numberOfVideoLinesPerField = 253; // 505 / 2
        tbcConfiguration.dotsPerVideoLine = 227.5;
        tbcConfiguration.inputSamplesPerVideoLine = tbcConfiguration.dotsPerVideoLine * tbcConfiguration.videoInputFrequencyInFsc;

        // Configure the auto-range filters
        autoRangeState.longSyncFilter = new Filter(f_dsync);
        autoRangeState.f_endsync = new Filter(f_esync8);
        break;

    case ntsc_domdup:
        // Configure the TBC
        tbcConfiguration.tbcMode = ntsc_domdup;
        tbcConfiguration.isNtsc = true;
        tbcConfiguration.videoInputFrequencyInFsc = 32.0 / (315.0 / 88.0); // = 8.93;
        tbcConfiguration.videoOutputFrequencyInFsc = 4.0;
        tbcConfiguration.numberOfVideoLinesPerFrame = 505;
        tbcConfiguration.numberOfVideoLinesPerField = 253; // 505 / 2
        tbcConfiguration.dotsPerVideoLine = 227.5;
        tbcConfiguration.inputSamplesPerVideoLine = tbcConfiguration.dotsPerVideoLine * tbcConfiguration.videoInputFrequencyInFsc;

        // Configure the auto-range filters
        autoRangeState.longSyncFilter = new Filter(f_dsync32);
        autoRangeState.f_endsync = new Filter(f_esync32);
        break;

    case pal_cxadc:
        // Configure the TBC
        tbcConfiguration.tbcMode = pal_cxadc;
        tbcConfiguration.isNtsc = false;
        tbcConfiguration.videoInputFrequencyInFsc = 8.0;
        tbcConfiguration.videoOutputFrequencyInFsc = 4.0;
        tbcConfiguration.numberOfVideoLinesPerFrame = 625;
        tbcConfiguration.numberOfVideoLinesPerField = 313;
        tbcConfiguration.dotsPerVideoLine = 283.75;
        tbcConfiguration.inputSamplesPerVideoLine = tbcConfiguration.dotsPerVideoLine * tbcConfiguration.videoInputFrequencyInFsc;

        // Configure the auto-range filters
        autoRangeState.longSyncFilter = new Filter(f_dsync);
        autoRangeState.f_endsync = new Filter(f_esync8);
        break;

    case pal_domdup:
        // Configure the TBC
        tbcConfiguration.tbcMode = pal_domdup;
        tbcConfiguration.isNtsc = false;
        tbcConfiguration.videoInputFrequencyInFsc = 32.0 / 4.43361875;
        tbcConfiguration.videoOutputFrequencyInFsc = 4.0;
        tbcConfiguration.numberOfVideoLinesPerFrame = 625;
        tbcConfiguration.numberOfVideoLinesPerField = 313;
        tbcConfiguration.dotsPerVideoLine = 283.75;
        tbcConfiguration.inputSamplesPerVideoLine = tbcConfiguration.dotsPerVideoLine * tbcConfiguration.videoInputFrequencyInFsc;

        // Configure the auto-range filters
        autoRangeState.longSyncFilter = new Filter(f_dsync32);
        autoRangeState.f_endsync = new Filter(f_esync32);

        // Configure the auto-range levels
        // Input scale is from -95 IRE (for pilot signal) to 145 IRE
        // which is a sweep of 240 IRE. 65535 / 240 = 273.0625
        autoRangeState.inputMaximumIreLevel = 273.06;
        autoRangeState.inputMinimumIreLevel = (autoRangeState.inputMaximumIreLevel * 95); // 0 IRE
        break;

    default:
        // Unsupported mode!
        qCritical() << "setTbcMode(): Unsupported mode!";
        exit(1);
    }
}

// Set magnetic video mode
void Tbc::setMagneticVideoMode(bool setting)
{
    // 2 for normal, 1 for magnetic video mode
    if (setting) tbcConfiguration.writeOnField = 1;
    else tbcConfiguration.writeOnField = 2;
}

// Set field flipping
void Tbc::setFlipFields(bool setting)
{
    tbcConfiguration.fieldFlip = setting;
}

// Set audio output only
void Tbc::setAudioOutputOnly(bool setting)
{
    tbcConfiguration.audioOutputOnly = setting;
}

// Set perform freeze frame
void Tbc::setPerformFreezeFrame(bool setting)
{
    tbcConfiguration.freezeFrame = setting;
}

// Set rot detect level
// TODO: Range check parameter
void Tbc::setRotDetectLevel(double_t value)
{
    tbcConfiguration.rotDetectLevel = value;
}

// Set skip frames
void Tbc::setSkipFrames(qint32 value)
{
    tbcConfiguration.skipFrames = value;
}

// Set maximum frames
void Tbc::setMaximumFrames(qint32 value)
{
    tbcConfiguration.maximumFrames = value;
}

// Set the source video file's file name
void Tbc::setSourceVideoFile(QString stringValue)
{
    tbcConfiguration.sourceVideoFileName = stringValue;
}

// Set the source audio file's file name
void Tbc::setSourceAudioFile(QString stringValue)
{
    tbcConfiguration.sourceAudioFileName = stringValue;
}

// Set the target video file's file name
void Tbc::setTargetVideoFile(QString stringValue)
{
    tbcConfiguration.targetVideoFileName = stringValue;
}

// Set the target audio file's file name
void Tbc::setTargetAudioFile(QString stringValue)
{
    tbcConfiguration.targetAudioFileName = stringValue;
}
