/************************************************************************

    tcbntsc.cpp

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

#include "tbcntsc.h"
#include "../../deemp.h"

TbcNtsc::TbcNtsc(quint16 fscSetting)
{
    // Note: FSC must be an even number
    // This was controlled by a define statement that
    // seemed to support FSC4, FSC10 or C32MHZ...
    switch(fscSetting) {
    case 10: // 10FSC
        c32mhz = false;
        videoInputFrequencyInFsc = 10.0;
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync10);
        f_endsync = new Filter(f_esync10);
        break;

    case 32: // C32MHZ
        c32mhz = true;
        videoInputFrequencyInFsc = 32.0 / (315.0 / 88.0); // = 8.93
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync32);
        f_endsync = new Filter(f_esync32);
        break;

    case 4: // FSC4
        c32mhz = false;
        videoInputFrequencyInFsc = 4.0;
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync4);
        f_endsync = new Filter(f_esync4);
        break;

    default:
        c32mhz = false;
        videoInputFrequencyInFsc = 8.0;
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync);
        f_endsync = new Filter(f_esync8);
    }

    // File names
    setSourceVideoFile(""); // Default is empty
    setSourceAudioFile(""); // Default is empty
    setTargetVideoFile(""); // Default is empty

    // Default tol setting
    //setTol(1.5); // f_tol = 1.5; // NTSC TBC doesn't have a tol setting...

    // Set global configuration settings

    // Global 'configuration'
    writeOnField = 1;
    f_flip = false;
    audio_only = false;
    performAutoRanging = (videoInputFrequencyInFsc == 4);
    freeze_frame = false;
    f_despackle = true;
    seven_five = (videoInputFrequencyInFsc == 4);
    f_highburst = false; // (FSC == 4);
    p_rotdetect = 40;
    p_skipframes = 0;

    inputMaximumIreLevel = 327.68;
    inputMinimumIreLevel = (inputMaximumIreLevel * 20);	// IRE == -40
    a_read = 0;
    v_read = 0;
    va_ratio = 80;

    // If this is changed, all the buffer sizes change
    // for NTSC it's 505x(Fsc * 211)
    outputFrequencyInFsc = 4; // in FSC

    // Globals for processAudio()
    afreq = 48000;
    prev_time = -1;
    nextAudioSample = 0;
    prev_loc = -1;
    prev_index = 0;
    prev_i = 0;

    // Globals for processAudioSample()
    audioChannelOneFilter = new Filter(f_fmdeemp);
    audioChannelTwoFilter = new Filter(f_fmdeemp);
    audioOutputBufferPointer = 0;

    // Globals to do with the line processing functions
    // handlebadline() and processline()
    line = -2;
    phase = -1;
    first = true;
    frameno = -1;
    firstloc = -1;

    // Auto-ranging state
    low = 65535;
    high = 0;
}

qint32 TbcNtsc::execute(void)
{
    // Show some info in the output
    qInfo() << "NTSC laserdisc time-based correction (TBC)";
    qInfo() << "Part of the Software Decode of Laserdiscs project";
    qInfo() << "(c)2018 Chad Page and Simon Inns";
    qInfo() << "LGPLv3 Open-Source - github: https://github.com/happycube/ld-decode";
    qInfo() << "";

    // Define our video and audio input buffers
    QVector<quint16> videoBuffer;
    QVector<double_t> audioBuffer;

    // Note: any variables dealing with file length should be 64 bits, otherwise we can
    // run into issues with big files on modern operating systems...

    // All vector operations are defined in terms of elements (rather than bytes) - this
    // is to make the code independent from the actual storage type chosen (i.e. quint16 or similar)

    // Define the required number of elements in the video and audio buffers
    qint32 videoBufferNumberOfElements = ((qint64)ntsc_iplinei * 1100);	// should be divisible evenly by 16
    qint32 audioBufferNumberOfElements = ((qint64)ntsc_iplinei * 1100) / 40;

    // Ensure that our buffer vectors are the correct length
    videoBuffer.resize(videoBufferNumberOfElements);
    audioBuffer.resize(audioBufferNumberOfElements);

    QFile* audioInputFileHandle;
    QFile* videoInputFileHandle;
    QFile* videoOutputFileHandle;
    bool processAudioData = false;

    // Set the expected video sync level to -30 IRE
    quint16 videoSyncLevel = inputMinimumIreLevel + (inputMaximumIreLevel * 15);

    // Show the configured video input frequency in FSC (what does FSC stand for?)
    qDebug() << "Video input frequency (FSC) = " << (double)videoInputFrequencyInFsc;

    // Some unspecified setup involving globals?
    p_maxframes = 1 << 28;
    if (p_skipframes > 0) p_maxframes += p_skipframes;

    // Open the video and audio input files ready for use --------------------------------------------

    // The TBC process expects a raw binary file containing a sequence of
    // unsigned 16-bit integer values representing the RF sample as proecessed
    // by the ld-decoder application (video signal is bandpassed and FM
    // demodulated).  The unsigned integer values are offset-centre with the
    // DC-offset of the signal at 32767.

    // Do we have a file name for the video file?
    if (sourceVideoFileName.isEmpty()) {
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
        videoInputFileHandle = new QFile(sourceVideoFileName);
        if (!videoInputFileHandle->open(QIODevice::ReadOnly)) {
            // Failed to open video file
            qWarning() << "Could not open specified video file";
            return -1;
        }
        qInfo() << "Reading video data from" << sourceVideoFileName;
    }

    // The source audio file is as per the video file (described above), however
    // the audio has been low-passed (to remove the video signal).  Note that the
    // signal contains both channel 1 and channel 2 audio combined and therefore
    // must be band-passed into individual channels before further processing
    //
    // Band-passing would be better performing in the ld-decoder process rather than
    // in the TBC, but it is what it is

    // Do we have a file name for the audio file?
    if (sourceAudioFileName.isEmpty()) {
        // No file to process...
        qDebug() << "The audio input file name was not set";

        // Make sure we can detect later that the file handle wasn't used...
        audioInputFileHandle = NULL;
    } else {
        // Open audio file for reading (quint16 data)
        audioInputFileHandle = new QFile(sourceAudioFileName);
        if (!audioInputFileHandle->open(QFile::ReadOnly)) {
            // Failed to open audio file
            qWarning() << "Could not open specified audio file";
            return -1;
        } else {
            processAudioData = true; // Flag that audio data should be processed
            qInfo() << "Reading audio data from" << sourceAudioFileName;
        }
    }

    // Do we have a file name for the output video file?
    if (targetVideoFileName.isEmpty()) {
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
        videoOutputFileHandle = new QFile(targetVideoFileName);
        if (!videoOutputFileHandle->open(QIODevice::WriteOnly)) {
            // Failed to open video output file
            qWarning() << "Could not open specified video output file";
            return -1;
        }
        qInfo() << "Writing video data to" << targetVideoFileName;
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
                    videoElementsInBuffer << "( buffer size is" << videoBuffer.size() << ")";

        // Calculate processing progress in % (cannot do this for stdin...)
        if (!sourceVideoFileName.isEmpty()) {
            double_t percentDone = 100.0 - (100.0 / (double_t)inputFileSize) * (double_t)videoInputFileHandle->bytesAvailable();
            qInfo() << (qint32)percentDone << "% of input file processed";
        }

        // Fill the video buffer from the video input file
        while ((videoElementsInBuffer < videoBuffer.size()) && (!videoInputFileHandle->atEnd())) {
            qDebug() << "Requesting" << (videoBuffer.size() - videoElementsInBuffer) <<
                        "elements from video file to fill video buffer";

            // Read from the video input file and store in the video buffer vector
            // This operation uses bytes, so we multiply the elements by the size of the data-type
            receivedVideoBytes = videoInputFileHandle->read(reinterpret_cast<char *>(videoBuffer.data()) + (videoElementsInBuffer * sizeof(quint16)),
                                                         ((videoBuffer.size() - videoElementsInBuffer) * sizeof(quint16)));

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
            qDebug() << "Requesting" << (audioBuffer.size() - audioElementsInBuffer) <<
                        "elements from audio file to fill audio buffer";

            // Read from the audio input file and store in the audio buffer vector
            // This operation uses bytes, so we multiply the elements by the size of the data-type
            qint64 receivedAudioBytes = audioInputFileHandle->read(reinterpret_cast<char *>(audioBuffer.data()) + (audioElementsInBuffer * sizeof(double_t)),
                                                         ((audioBuffer.size() - audioElementsInBuffer) * sizeof(double_t)));

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
            if (performAutoRanging) {
                // Perform auto range of input video data
                qDebug() << "Performing auto ranging...";
                videoSyncLevel = autoRange(videoBuffer);
            }

            // Process the video and audio buffer (only the number of elements read from the file are processed,
            // not the whole buffer)
            qDebug() << "Processing the video and audio buffers...";
            bool videoFrameBufferReady = false;
            qint32 numberOfVideoBufferElementsProcessed = processVideoAndAudioBuffer(videoBuffer, videoElementsInBuffer,
                                                                                     audioBuffer, processAudioData,
                                                                                     &videoFrameBufferReady);
            qDebug() << "Processed" << numberOfVideoBufferElementsProcessed << "elements from video buffer";

            // Write the video frame buffer to disk?
            if (videoFrameBufferReady && numberOfVideoBufferElementsProcessed > 0) {
                if (!audio_only) {
                    qInfo() << "Writing frame data to disc...";
                    videoOutputFileHandle->write(reinterpret_cast<char *>(frameBuffer), sizeof(frameBuffer));
                } else qInfo() << "Audio only selected - discarding video frame data";

                // Note: this writes a complete buffer at the end of the file even if
                // the buffer isn't completely full. Causes the size of file to be a little
                // bit larger than the original TBC version.

                // Clear the frame buffer
                memset(frameBuffer, 0, sizeof(frameBuffer));
            }

            // Check if the processing found no video in the current buffer... and discard the buffer if required
            if (numberOfVideoBufferElementsProcessed <= 0) {
                qDebug() << "No video detected in video buffer, discarding buffer data"; // skipping ahead

                // Set the number of processed bytes to the whole buffer, so all data will be shifted back
                numberOfVideoBufferElementsProcessed = videoBuffer.size();
            }

            // These v_read/a_read variables seem to be used by both processVideoAndAudio and processAudio
            // as part of the processings... but they are not passed, they are globals.  Messy
            // They are also only set on the second-pass of those procedures... hopefully the defaults are sane?
            // Not sure what they are actually for - probably tracking the audio data vs the video data
            v_read += numberOfVideoBufferElementsProcessed;
            numberOfAudioBufferElementsProcessed = (v_read / va_ratio) - a_read;
            a_read += numberOfAudioBufferElementsProcessed;

            // If the current buffer doesn't contain enough data for a complete line, the buffer is shifted around to
            // the beginning of the detected line (detected by the processVideoAndAudioBuffer function) and then refilled
            // to ensure the rest of the line data is in the buffer the next time it is processed

            // Shift back the contents of videoBuffer
            qDebug() << "Shifting back the video buffer contents by" <<
                        numberOfVideoBufferElementsProcessed << "elements";

            // We need to remove (videoBufferNumberOfElements - (videoProcessLengthInBytes / sizeof(quint16))
            // elements from the start of the video buffer (as they are already processed)
            videoBuffer.remove(0, numberOfVideoBufferElementsProcessed);

            // Now we adjust videoBytesReceived to reflect the number of elements still in the buffer
            // (based on the new size of the buffer due to the remove() operation)
            videoElementsInBuffer = videoBuffer.size();

            // Now we resize the video buffer back to its original length
            videoBuffer.resize(videoBufferNumberOfElements);

            // Are we processing audio?
            if (processAudioData) {
                // Shift back the audio data buffer by the same amount as the video buffer
                qDebug() << "Shifting back the audio buffer contents by" <<
                            numberOfVideoBufferElementsProcessed << "elements";

                audioBuffer.remove(0, numberOfAudioBufferElementsProcessed);
                audioElementsInBuffer = audioBuffer.size();
                audioBuffer.resize(audioBufferNumberOfElements);
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
quint16 TbcNtsc::autoRange(QVector<quint16> videoBuffer)
{
    QVector<double_t> longSyncFilterResult(videoBuffer.size());
    bool fullagc = true;
    qint32 lowloc = -1;
    qint32 checklen = (qint32)(videoInputFrequencyInFsc * 4);

    if (!fullagc) {
        low = 65535;
        high = 0;
    }

    qInfo() << "Performing auto-ranging";
    qDebug() << "Scale before auto-ranging is =" << (double)inputMinimumIreLevel << ':' << (double)inputMaximumIreLevel;

    //	f_longsync.clear(0);

    // Phase 1:  Get the low (-40 IRE) and high (?? IRE) values
    for (int currentVideoBufferElement = 0;
         currentVideoBufferElement < videoBuffer.size();
         currentVideoBufferElement++) {
        longSyncFilterResult[currentVideoBufferElement] =
                longSyncFilter->feed(videoBuffer[currentVideoBufferElement]);

        if ((currentVideoBufferElement > (videoInputFrequencyInFsc * 256)) &&
                (longSyncFilterResult[currentVideoBufferElement] < low) &&
                (longSyncFilterResult[currentVideoBufferElement - checklen] < low)) {
            if (longSyncFilterResult[currentVideoBufferElement - checklen] >
                    longSyncFilterResult[currentVideoBufferElement])
                low = longSyncFilterResult[currentVideoBufferElement - checklen];
            else
                low = longSyncFilterResult[currentVideoBufferElement];

            lowloc = currentVideoBufferElement;
        }

        if ((currentVideoBufferElement > (videoInputFrequencyInFsc * 256)) &&
                (longSyncFilterResult[currentVideoBufferElement] > high) &&
                (longSyncFilterResult[currentVideoBufferElement - checklen] > high)) {
            if (longSyncFilterResult[currentVideoBufferElement - checklen] < longSyncFilterResult[currentVideoBufferElement])
                high = longSyncFilterResult[currentVideoBufferElement - checklen];
            else
                high = longSyncFilterResult[currentVideoBufferElement];
        }
    }

    // Phase 2: Attempt to figure out the 0 IRE porch near the sync
    if (!fullagc) {
        qint32 gap = high - low;
        qint32 nloc;

        for (nloc = lowloc; (nloc > lowloc - (videoInputFrequencyInFsc * 320)) && (longSyncFilterResult[nloc] < (low + (gap / 8))); nloc--);

        qDebug() << nloc << (lowloc - nloc) / (double)videoInputFrequencyInFsc << (double)longSyncFilterResult[nloc];

        nloc -= (videoInputFrequencyInFsc * 4);
        qDebug() << nloc << (lowloc - nloc) / (double)videoInputFrequencyInFsc << (double)longSyncFilterResult[nloc];

        qDebug() << "Scale before auto-ranging is =" << (double)inputMinimumIreLevel << ':' << (double)inputMaximumIreLevel;

        inputMaximumIreLevel = (longSyncFilterResult[nloc] - low) / ((seven_five) ? 47.5 : 40.0);
        inputMinimumIreLevel = low - (20 * inputMaximumIreLevel); // Should be in the range of -40 IRE to -60 IRE

        if (inputMinimumIreLevel < 1) inputMinimumIreLevel = 1;
        qDebug() << "Scale after auto-ranging is =" << (double)inputMinimumIreLevel << ':' << (double)inputMaximumIreLevel;
    } else {
        inputMaximumIreLevel = (high - low) / 140.0;
    }

    inputMinimumIreLevel = low;	// -40IRE to -60IRE
    if (inputMinimumIreLevel < 1) inputMinimumIreLevel = 1;

    qDebug() << "Scale after auto-ranging is =" << (double)inputMinimumIreLevel << ':'
             << (double)inputMaximumIreLevel << " low:" << (double)low << (double)high;

    return inputMinimumIreLevel + (inputMaximumIreLevel * 20);
}

// Process a buffer of video and audio data
// The function seems to work out where the video frames begin and end in
// the video buffer and then passes each line of video (and corresponding 'line'
// of audio) to the processAudio and processLine functions to be further processed
// into 'frames' of data.
//
// Returns:
//      The number of videoBuffer elements that were processed
//      A flag indicating if the video frame buffer is ready to be written to disc (by reference)
qint32 TbcNtsc::processVideoAndAudioBuffer(QVector<quint16> videoBuffer, qint32 videoBufferElementsToProcess,
                                           QVector<double_t> audioBuffer, bool processAudioData,
                                           bool *isVideoFrameBufferReadyForWrite)
{
    // Set the write buffer flag to a default of false (do not write)
    *isVideoFrameBufferReadyForWrite = false;

    double_t lineBuffer[1820];
    double_t horizontalSyncs[253];
    qint32 field = -1;
    qint32 offset = 500;

    // Clear the video frame buffer
    memset(frameBuffer, 0, sizeof(frameBuffer));

    while (field < 1) {
        //find_vsync(&buf[firstsync - 1920], len - (firstsync - 1920));
        qint32 verticalSync = findVsync(videoBuffer.data(), videoBufferElementsToProcess, offset);

        bool oddEven = verticalSync > 0;
        verticalSync = abs(verticalSync);
        qDebug() << "findvsync" << oddEven << verticalSync;

        if ((oddEven == false) && (field == -1))
            return verticalSync + (videoInputFrequencyInFsc * 227.5 * 240);

        // Process skip-frames mode - zoom forward an entire frame
        if (frameno < p_skipframes) {
            frameno++;
            return verticalSync + (videoInputFrequencyInFsc * 227.5 * 510);
        }

        field++;

        // Zoom ahead to close to the first full proper sync
        if (oddEven) {
            verticalSync = abs(verticalSync) + (750 * videoInputFrequencyInFsc);
        } else {
            verticalSync = abs(verticalSync) + (871 * videoInputFrequencyInFsc);
        }

        findHsyncs(videoBuffer.data(), videoBufferElementsToProcess, verticalSync, horizontalSyncs);
        bool isLineBad[252];

        // Find horizontal syncs (rough alignment)
        for (qint32 line = 0; line < 252; line++) {
            isLineBad[line] = horizontalSyncs[line] < 0;
            horizontalSyncs[line] = abs(horizontalSyncs[line]);
        }

        // Determine vsync->0/7.5IRE transition point (TODO: break into function)
        for (qint32 line = 0; line < 252; line++) {
            if (isLineBad[line] == true) continue;

            double_t previous = 0;
            double_t startSync = -1;
            double_t endSync = -1;
            quint16 tPoint = ire_to_in(-20);

            // Find beginning of horizontal sync
            f_endsync->clear(0);
            previous = 0;
            for (qint32 i = horizontalSyncs[line] - (20 * videoInputFrequencyInFsc);
                 i < horizontalSyncs[line] - (8 * videoInputFrequencyInFsc); i++) {
                double_t current = f_endsync->feed(videoBuffer[i]);

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
            f_endsync->clear(0);
            previous = 0;
            for (qint32 counter = horizontalSyncs[line] - (2 * videoInputFrequencyInFsc);
                 counter < horizontalSyncs[line] + (4 * videoInputFrequencyInFsc); counter++) {
                double_t current = f_endsync->feed(videoBuffer[counter]);

                if ((previous < tPoint) && (current > tPoint)) {
                    // qDebug() << "E" << line << hsyncs[line];
                    double_t difference = current - previous;
                    endSync = ((counter - 8) + (tPoint - previous) / difference);

                    // qDebug() << prev << tpoint << cur << hsyncs[line];
                    break;
                }
                previous = current;
            }

            qDebug() << "S" << line << (double)startSync << (double)endSync << (double)(endSync - startSync);

            if ((!inRangeCF(endSync - startSync, 15.75, 17.25)) || (startSync == -1) || (endSync == -1)) {
                isLineBad[line] = true;
            } else {
                horizontalSyncs[line] = endSync;
            }
        }

        // We need semi-correct lines for the next phases
        correctDamagedHSyncs(horizontalSyncs, isLineBad);

        bool phaseFlip;
        double_t bLevel[252];
        double_t tpOdd = 0, tpEven = 0;
        qint32 nOdd = 0, nEven = 0; // need to track these to exclude bad lines
        double_t bPhase = 0;
        // detect alignment (undamaged lines only)
        for (qint32 line = 0; line < 64; line++) {
            double_t line1 = horizontalSyncs[line], line2 = horizontalSyncs[line + 1];

            if (isLineBad[line] == true) {
                qDebug() << "ERR" << line;
                continue;

            }

            // Burst detection/correction
            scale(videoBuffer.data(), lineBuffer, line1, line2, 227.5 * videoInputFrequencyInFsc);
            if (!burstDetect2(lineBuffer, videoInputFrequencyInFsc, 4, bLevel[line], bPhase, phaseFlip)) {
                qDebug() << "ERRnoburst" << line;
                isLineBad[line] = true;
                continue; // Exits the for loop...
            }

            // phase is not defined as an array?
            phase[line] = bPhase;

            if (line % 2) {
                tpOdd += phaseFlip;
                nOdd++;
            } else {
                tpEven += phaseFlip;
                nEven++;
            }

            qDebug() << "BURST" << line << (double)line1 << (double)line2 << (double)bLevel[line] << (double)bPhase;
        }

        bool fieldPhase = fabs(tpEven / nEven) < fabs(tpOdd / nOdd);
        qDebug() << "PHASES:" << nEven + nOdd << (double)(tpEven / nEven) << (double)(tpOdd / nOdd) << fieldPhase;

        for (qint32 pass = 0; pass < 4; pass++) {
               for (qint32 line = 0; line < 252; line++) {
            bool lPhase = ((line % 2) == 0);
            if (fieldPhase) lPhase = !lPhase;

            double_t line1c = horizontalSyncs[line] + ((horizontalSyncs[line + 1] - horizontalSyncs[line]) * 14.0 / 227.5);

            scale(videoBuffer.data(), lineBuffer, horizontalSyncs[line], line1c, 14 * videoInputFrequencyInFsc);
            if (!burstDetect2(lineBuffer, videoInputFrequencyInFsc, 4, bLevel[line], bPhase, phaseFlip)) {
                isLineBad[line] = true;
                continue; // Exits the for loop...
            }

            double_t tgt = .260;
//			if (bphase > .5) tgt += .5;

            double_t adj = (tgt - bPhase) * 8;

            //qDebug() << "ADJ" << line << pass << bphase << tgt << adj;
            horizontalSyncs[line] -= adj;
           }
        }

        correctDamagedHSyncs(horizontalSyncs, isLineBad);

        // Final output
        for (qint32 line = 0; line < 252; line++) {
            double_t line1 = horizontalSyncs[line], line2 = horizontalSyncs[line + 1];
            qint32 oline = 3 + (line * 2) + (oddEven ? 0 : 1);

            // 33 degree shift
            double_t shift33 = (33.0 / 360.0) * 4 * 2;

            if (videoInputFrequencyInFsc == 4) {
                // XXX THIS IS BUGGED, but works
                shift33 = (107.0 / 360.0) * 4 * 2;
            }

            double_t pt = -12 - shift33; // align with previous-gen tbc output

            scale(videoBuffer.data(), lineBuffer, line1 + pt, line2 + pt, 910, 0);

            double_t framePosition = (line / 525.0) + frameno + (field * .50);

            if (!field) framePosition -= .001;

            // Process audio?
            if (processAudioData) {
                processAudio(framePosition, v_read + horizontalSyncs[line], audioBuffer.data());
            }

            bool lphase = ((line % 2) == 0);
            if (fieldPhase) lphase = !lphase;
            frameBuffer[oline][0] = (lphase == 0) ? 32768 : 16384;
            frameBuffer[oline][1] = bLevel[line] * (327.68 / inputMaximumIreLevel); // ire_to_out(in_to_ire(blevel[line]));

            if (isLineBad[line]) {
                        frameBuffer[oline][3] = frameBuffer[oline][5] = 65000;
                    frameBuffer[oline][4] = frameBuffer[oline][6] = 0;
            }

            for (qint32 t = 4; t < 844; t++) {
                double_t o = lineBuffer[t];

                if (performAutoRanging) o = ire_to_out(in_to_ire(o));

                frameBuffer[oline][t] = (uint16_t)clamp(o, 1, 65535);
            }
        }

        offset = abs(horizontalSyncs[250]);

        qDebug() << "new offset" << offset;
    }

    if (f_despackle) despackle();

    // Decode VBI data
    decodeVBI();

    // Increment the frame number
    frameno++;

    // Flag that the video frame buffer is ready to be written to disk:
    *isVideoFrameBufferReadyForWrite = true;

    // Done
    return offset;
}

// Find the sync signal
qint32 TbcNtsc::findSync(quint16 *videoBuffer, qint32 videoLength, qint32 tgt = 50)
{
    const int pad = 96;
    int rv = -1;

    const uint16_t to_min = ire_to_in(-45), to_max = ire_to_in(-35);
    const uint16_t err_min = ire_to_in(-55), err_max = ire_to_in(30);

    uint16_t clen = tgt * 3;
    uint16_t circbuf[clen];
    uint16_t circbuf_err[clen];

    memset(circbuf, 0, clen * 2);
    memset(circbuf_err, 0, clen * 2);

    int count = 0, errcount = 0, peak = 0, peakloc = 0;

    for (int i = 0; (rv == -1) && (i < videoLength); i++) {
        int nv = (videoBuffer[i] >= to_min) && (videoBuffer[i] < to_max);
        int err = (videoBuffer[i] <= err_min) || (videoBuffer[i] >= err_max);

        count = count - circbuf[i % clen] + nv;
        circbuf[i % clen] = nv;

        errcount = errcount - circbuf_err[i % clen] + err;
        circbuf_err[i % clen] = err;

        if (count > peak) {
            peak = count;
            peakloc = i;
        } else if ((count > tgt) && ((i - peakloc) > pad)) {
            rv = peakloc;

            if ((videoInputFrequencyInFsc > 4) && (errcount > 1)) {
                qDebug() << "HERR" << errcount;
                rv = -rv;
            }
        }

        //qDebug() << i << videoBuffer[i] << peak << peakloc << i - peakloc;
    }

    if (rv == -1) qDebug() << "not found" << peak << peakloc;

    return rv;
}

// This could probably be used for more than just field det, but eh
qint32 TbcNtsc::countSlevel(quint16 *videoBuffer, qint32 begin, qint32 end)
{
    const uint16_t to_min = ire_to_in(-45), to_max = ire_to_in(-35);
    int count = 0;

    for (int i = begin; i < end; i++) {
        count += (videoBuffer[i] >= to_min) && (videoBuffer[i] < to_max);
    }

    return count;
}

// Returns index of end of VSYNC - negative if _ field
qint32 TbcNtsc::findVsync(quint16 *videoBuffer, qint32 videoLength, qint32 offset = 0)
{
    const uint16_t field_len = videoInputFrequencyInFsc * 227.5 * 280;

    if (videoLength < field_len) return -1;

    int pulse_ends[6];
    int slen = videoLength;

    int loc = offset;

    for (int i = 0; i < 6; i++) {
        // 32xFSC is *much* shorter, but it shouldn't get confused for an hsync -
        // and on rotted disks and ones with burst in vsync, this helps
        int syncend = abs(findSync(&videoBuffer[loc], slen, 32 * videoInputFrequencyInFsc));

        pulse_ends[i] = syncend + loc;
        qDebug() << pulse_ends[i];

        loc += syncend;
        slen = 3840;
    }

    int rv = pulse_ends[5];

    // determine line type
    int before_end = pulse_ends[0] - (127.5 * videoInputFrequencyInFsc);
    int before_start = before_end - (227.5 * 4.5 * videoInputFrequencyInFsc);

    int pc_before = countSlevel(videoBuffer, before_start, before_end);

    int after_start = pulse_ends[5];
    int after_end = after_start + (227.5 * 4.5 * videoInputFrequencyInFsc);
    int pc_after = countSlevel(videoBuffer, after_start, after_end);

    qDebug() << "beforeafter:" << pulse_ends[0] + offset << pulse_ends[5] + offset << pc_before << pc_after;

    if (pc_before < pc_after) rv = -rv;

    return rv;
}

// Returns end of each line, -end if error detected in this phase
// (caller responsible for freeing array)
bool TbcNtsc::findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *rv, qint32 nlines = 253)
{
    // sanity check (XXX: assert!)
    if (videoLength < (nlines * videoInputFrequencyInFsc * 227.5))
        return false;

    int loc = offset;

    for (int line = 0; line < nlines; line++) {
    //	qDebug() << line << loc;
        int syncend = findSync(&videoBuffer[loc], 227.5 * 3 * videoInputFrequencyInFsc,
                               8 * videoInputFrequencyInFsc);

        double_t gap = 227.5 * videoInputFrequencyInFsc;

        int err_offset = 0;
        while (syncend < -1) {
            qDebug() << "error found" << line << syncend << ' ';
            err_offset += gap;
            syncend = findSync(&videoBuffer[loc] + err_offset, 227.5 * 3 * videoInputFrequencyInFsc,
                               8 * videoInputFrequencyInFsc);
            qDebug() << syncend;
        }

        // If it skips a scan line, fake it
        if ((line > 0) && (line < nlines) && (syncend > (40 * videoInputFrequencyInFsc))) {
            rv[line] = -(abs(rv[line - 1]) + gap);
            qDebug() << "XX" << line << loc << syncend << (double)rv[line];
            syncend -= gap;
            loc += gap;
        } else {
            rv[line] = loc + syncend;
            if (err_offset) rv[line] = -rv[line];

            if (syncend != -1) {
                loc += fabs(syncend) + (200 * videoInputFrequencyInFsc);
            } else {
                loc += gap;
            }
        }
    }

    return rv;
}

// correct damaged hsyncs by interpolating neighboring lines
void TbcNtsc::correctDamagedHSyncs(double_t *hsyncs, bool *err)
{
    for (int line = 1; line < 251; line++) {
        if (err[line] == false) continue;

        int lprev, lnext;

        for (lprev = line - 1; (err[lprev] == true) && (lprev >= 0); lprev--);
        for (lnext = line + 1; (err[lnext] == true) && (lnext < 252); lnext++);

        // This shouldn't happen...
        if ((lprev < 0) || (lnext == 252)) continue;

        double_t linex = (hsyncs[line] - hsyncs[0]) / line;

        qDebug() << "FIX" << line << (double)linex << (double)hsyncs[line] << (double)(hsyncs[line] - hsyncs[line - 1]) << lprev << lnext ;

        double_t lavg = (hsyncs[lnext] - hsyncs[lprev]) / (lnext - lprev);
        hsyncs[line] = hsyncs[lprev] + (lavg * (line - lprev));
        qDebug() << (double)hsyncs[line];
    }
}

// Process a video frame's worth of audio
void TbcNtsc::processAudio(double_t frameBuffer, qint64 loc, double_t *audioBuffer)
{
    double_t time = frameBuffer / (30000.0 / 1001.0);

    // Default firstloc if required
    if (firstloc == -1) firstloc = loc;

    if (prev_time >= 0) {
        while (nextAudioSample < time) {
            double_t i1 = (nextAudioSample - prev_time) / (time - prev_time);
            long long i = (i1 * (loc - prev_loc)) + prev_loc;

            if (i < v_read) {
                processAudioSample(audioChannelOneFilter->filterValue(), audioChannelTwoFilter->filterValue());
            } else {
                long long index = (i / va_ratio) - a_read;
                if (index >= ablen) {
                    qDebug() << "audio error" << (double)frameBuffer << (double)time << (double)i1
                             << i << index << ablen;
                    index = ablen - 1;
                }
                float channelOne = audioBuffer[index * 2], channelTwo = audioBuffer[(index * 2) + 1];
                double_t frameb = (double_t)(i - firstloc) / 1820.0 / 525.0;
                qDebug() << "A" << (double)frameBuffer << loc << (double)frameb << (double)i1 << i << i - prev_i <<
                            index << index - prev_index << channelOne << channelTwo;
                prev_index = index;
                prev_i = i;
                processAudioSample(channelOne, channelTwo);
            }

            nextAudioSample += 1.0 / afreq;
        }
    }

    prev_time = time; prev_loc = loc;
}

// Process a sample of audio (from what to what?)
void TbcNtsc::processAudioSample(double_t channelOne, double_t channelTwo)
{
    quint16 audioOutputBuffer[512];

    channelOne = audioChannelOneFilter->feed(channelOne * (65535.0 / 300000.0));
    channelOne += 32768;

    channelTwo = audioChannelTwoFilter->feed(channelTwo * (65535.0 / 300000.0));
    channelTwo += 32768;

    audioOutputBuffer[audioOutputBufferPointer * 2] = clamp(channelOne, 0, 65535);
    audioOutputBuffer[(audioOutputBufferPointer * 2) + 1] = clamp(channelTwo, 0, 65535);

    // Need to pass this buffer back to the main process function and write it to
    // disk there rather than being buried here...
    audioOutputBufferPointer++;
    if (audioOutputBufferPointer == 256) {
//        int rv = write(audio_only ? 1 : 3, audioOutputBuffer, sizeof(audioOutputBuffer));
//        rv = audioOutputBufferPointer = 0;
        qWarning() << "Writing audio is not currently implemented!";
    }
}

// If value is less than lowValue, function returns lowValue
// If value is greated than highValue, function returns highValue
// otherwise function returns value
inline double_t TbcNtsc::clamp(double_t value, double_t lowValue, double_t highValue)
{
        if (value < lowValue) return lowValue;
        else if (value > highValue) return highValue;
        else return value;
}

// Convert from input scale to IRE
inline double_t TbcNtsc::in_to_ire(quint16 level)
{
    if (level == 0) return -100;

    return -40 + ((double_t)(level - inputMinimumIreLevel) / inputMaximumIreLevel);
}

// Convert from IRE to input scale
inline quint16 TbcNtsc::ire_to_in(double_t ire)
{
    if (ire <= -60) return 0;

    return clamp(((ire + 40) * inputMaximumIreLevel) + inputMinimumIreLevel, 1, 65535);
}

// Convert from IRE to output scale
inline quint16 TbcNtsc::ire_to_out(double_t ire)
{
    if (ire <= -60) return 0;

    return clamp(((ire + 60) * 327.68) + 1, 1, 65535);
}

// Convert from output level to IRE
double_t TbcNtsc::out_to_ire(quint16 in)
{
    return (in / 327.68) - 60;
}

// No idea what this function is for
inline double_t TbcNtsc::peakdetect_quad(double_t *y)
{
    return (2 * (y[2] - y[0]) / (2 * (2 * y[1] - y[0] - y[2])));
}

// Note: Processing performance could probably be improved by changing
// the interpolate to act directly on the data (rather than one element
// at a time)...

// Perform bicubic interpolation of the passed values
// taken from http://www.paulinternet.nl/?page=bicubic
inline double_t TbcNtsc::cubicInterpolate(quint16 *y, double_t x)
{
    double_t p[4];
    p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

    return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
}

// This function takes a video line that is the wrong length
// and interpolates the line to the correct (predicted) length
inline void TbcNtsc::scale(uint16_t *buf, double_t *outbuf, double_t start, double_t end,
                           double_t outlen, double_t offset = 0, qint32 from = 0, qint32 to = -1)
{
    double_t inlen = end - start;
    double_t perpel = inlen / outlen;

    if (to == -1) to = (int)outlen;

    double_t p1 = start + (offset * perpel);
    for (int i = from; i < to; i++) {
        int index = (int)p1;
        if (index < 1) index = 1;

        outbuf[i] = clamp(cubicInterpolate(&buf[index - 1], p1 - index), 0, 65535);

        p1 += perpel;
    }
}

// Function returns true if v is within the range of l to h
bool TbcNtsc::inRange(double_t v, double_t l, double_t h)
{
    return ((v > l) && (v < h));
}

// Function returns true if v is within the range of l to h
// Note: l and h are scaled according to the video input frequency in FSC
bool TbcNtsc::inRangeCF(double_t v, double_t l, double_t h)
{
    return inRange(v, l * videoInputFrequencyInFsc, h * videoInputFrequencyInFsc);
}

// Function to detect the burst signal within a line of video
// Could do with a description of how it works?
bool TbcNtsc::burstDetect2(double_t *line, qint32 freq, double_t _loc, double_t &plevel,
                           double_t &pphase, bool &phaseflip)
{
    int len = (6 * freq);
    int loc = _loc * freq;
    double_t start = 0 * freq;

    double_t peakh = 0, peakl = 0;
    int npeakh = 0, npeakl = 0;
    double_t lastpeakh = -1, lastpeakl = -1;

    double_t highmin = ire_to_in(f_highburst ? 11 : 9);
    double_t highmax = ire_to_in(f_highburst ? 23 : 22);
    double_t lowmin = ire_to_in(f_highburst ? -11 : -9);
    double_t lowmax = ire_to_in(f_highburst ? -23 : -22);

    int begin = loc + (start * freq);
    int end = begin + len;

    // first get average (probably should be a moving one)

    double_t avg = 0;
    for (int i = begin; i < end; i++) {
        avg += line[i];
    }
    avg /= (end - begin);

    // or we could just ass-u-me IRE 0...
    //avg = ire_to_in(0);

    // get first and last ZC's, along with first low-to-high transition
    double_t firstc = -1;
    double_t firstc_h = -1;
    double_t lastc = -1;

    double_t avg_htl_zc = 0, avg_lth_zc = 0;
    int n_htl_zc = 0, n_lth_zc = 0;

    for (int i = begin ; i < end; i++) {
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
            lastc = zc;

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
            lastc = zc;

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
    } else return false;

    if (n_lth_zc) {
        avg_lth_zc /= n_lth_zc;
    } else return false;

    //qDebug() << "PDETECT" << fabs(avg_htl_zc - avg_lth_zc) <<
    //                         n_htl_zc << avg_htl_zc << n_lth_zc << avg_lth_zc;

    double_t pdiff = fabs(avg_htl_zc - avg_lth_zc);

    if ((pdiff < .35) || (pdiff > .65)) return false;

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

// inline bool TbcPal::isPeak(double_t *p, qint32 i)
bool TbcNtsc::isPeak(double_t *p, qint32 i)
{
    return (fabs(p[i]) >= fabs(p[i - 1])) && (fabs(p[i]) >= fabs(p[i + 1]));
}


// Functions with no PAL equivilent ---------------------------------------------------------------

// Essential VBI/Phillips code reference: http://www.daphne-emu.com/mediawiki/index.php/VBIInfo
// (LD-V6000A info page is cryptic but very essential!)
quint32 TbcNtsc::readPhillipsCode(quint16 *line)
{
    // VBI? - Is this supposed to be based on FSC?  Looks like it...
    double_t dots_usec = 4.0 * 315.0 / 88.0;

    int first_bit = -1; // 108 - dots_usec;
    uint32_t out = 0;

    double_t deltaLine[844];

    for (int i = 1; i < 843; i++) {
        deltaLine[i] = line[i] - line[i - 1];
    }

    // find first positive transition (exactly halfway into bit 0 which is *always* 1)
    for (int i = 70; (first_bit == -1) && (i < 140); i++) {
//		qDebug() << i << out_to_ire(line[i]) << Δline[i];
        if (isPeak(deltaLine, i) && (deltaLine[i] > 10 * 327.68)) {
            first_bit = i;
        }
    }
    if (first_bit < 0) return 0;

    for (int i = 0; i < 24; i++) {
        int rloc = -1, loc = (first_bit + (i * 2 * dots_usec));
        double_t rpeak = -1;

        for (int h = loc - 8; (h < loc + 8); h++) {
            if (isPeak(deltaLine, h)) {
                if (fabs(deltaLine[h]) > rpeak) {
                    rpeak = fabs(deltaLine[h]);
                    rloc = h;
                }
            }
        }

        if (rloc == -1) rloc = loc;

        out |= (deltaLine[rloc] > 0) ? (1 << (23 - i)) : 0;
        qDebug() << i << loc << (double)deltaLine[loc] << rloc << (double)deltaLine[rloc] <<(double)(deltaLine[rloc] / inputMaximumIreLevel) << out;

        if (!i) first_bit = rloc;
    }
    qDebug() << "P" << hex << out << dec;

    return out;
}

inline double_t TbcNtsc::max(double_t a, double_t b)
{
    return (a > b) ? a : b;
}

void TbcNtsc::despackle(void)
{
    qint32 out_x = 844;
    qint32 out_y = 505;

    memcpy(frameOriginal, frameBuffer, sizeof(frameBuffer));

    for (int y = 22; y < out_y; y++) {
        double_t rotdetect = p_rotdetect * inputMaximumIreLevel;

        for (int x = 60; x < out_x - 16; x++) {

            double_t comp = 0;

            for (int cy = y - 1; (cy < (y + 2)) && (cy < out_y); cy++) {
                for (int cx = x - 3; (cx < x + 3) && (cx < (out_x - 12)); cx++) {
                    comp = max(comp, deltaFrameFilter[cy][cx]);
                }
            }

            if ((out_to_ire(frameBuffer[y][x]) < -20) || (out_to_ire(frameBuffer[y][x]) > 140) ||
                    ((deltaFrame[y][x] > rotdetect) && ((deltaFrame[y][x] - comp) > rotdetect))) {
                qDebug() << "R" << y << x << (double)rotdetect << (double)deltaFrame[y][x] << (double)comp << (double)deltaFrameFilter[y][x];
                for (int m = x - 4; (m < (x + 14)) && (m < out_x); m++) {
                    double_t tmp = (((double_t)frameOriginal[y - 2][m - 2]) +
                            ((double_t)frameOriginal[y - 2][m + 2])) / 2;

                    if (y < (out_y - 3)) {
                        tmp /= 2;
                        tmp += ((((double_t)frameOriginal[y + 2][m - 2]) +
                                ((double_t)frameOriginal[y + 2][m + 2])) / 4);
                    }

                    frameBuffer[y][m] = clamp(tmp, 0, 65535);
                }
                x = x + 14;
            }
        }
    }
}

// Used by the decodeVBI function for something...
bool TbcNtsc::checkWhiteFlag(qint32 l)
{
    int wc = 0;

    for (int i = 100; i < 800; i++) {
        if (out_to_ire(frameBuffer[l][i]) > 80) wc++;
        if (wc >= 200) return true;
    }

    return false;
}

// Decode VBI data
void TbcNtsc::decodeVBI(void)
{
    uint32_t code[6];

    uint32_t clv_time = 0;
    uint32_t chap = 0;
    uint32_t flags = 0;

    bool odd = false; // CAV framecode on odd scanline
    bool even = false; // on even scanline (need to report both, since some frames have none!)
    bool clv = false;
    bool cx  = false;
    int fnum = 0;

    memset(code, 0, sizeof(code));
    for (int i = 14; i < 20; i++) {
        code[i - 14] = readPhillipsCode(frameBuffer[i]);
    }
    qDebug() << "Phillips codes" << hex << code[0] << code[1] << code[2] << code[3] << code[4] << code[5] << dec;

    for (int i = 0; i < 6; i++) {
        frameBuffer[0][i * 2] = code[i] >> 16;
        frameBuffer[0][(i * 2) + 1] = code[i] & 0xffff;

        if ((code[i] & 0xf00fff) == 0x800fff) {
            chap =  ((code[i] & 0x00f000) >> 12);
            chap += (((code[i] & 0x0f0000) >> 16) - 8) * 10;
        }

        if ((code[i] & 0xfff000) == 0x8dc000) {
            cx = true;
        }

        if (0x87ffff == code[i]) {
            clv = true;
        }
    }

    if (clv == true) {
        uint16_t hours = 0;
        uint16_t minutes = 0;
        uint16_t seconds = 0;
        uint16_t framenum = 0;
        // Find CLV frame # data
        for (int i = 0; i < 6; i++) {
            // CLV Picture #
            if (((code[i] & 0xf0f000) == 0x80e000) && ((code[i] & 0x0f0000) >= 0x0a0000)) {
                seconds = (((code[i] & 0x0f0000) - 0x0a0000) >> 16) * 10;
                seconds += (code[i] & 0x000f00) >> 8;
                framenum = code[i] & 0x0f;
                framenum += ((code[i] & 0x000f0) >> 4) * 10;
            }
            if ((code[i] & 0xf0ff00) == 0xf0dd00) {
                hours = ((code[i] & 0x0f0000) >> 16);
                minutes = code[i] & 0x0f;
                minutes += ((code[i] & 0x000f0) >> 4) * 10;
            }
        }
        fnum = (((hours * 3600) + (minutes * 60) + seconds) * 30) + framenum;
        clv_time = (hours << 24) | (minutes << 16) || (seconds << 8) || framenum;
        qDebug() << "CLV" << hours << ':' << minutes << ':' << seconds << '.' << framenum;
    } else {
        for (int i = 0; i < 6; i++) {
            // CAV frame:  f80000 + frame
            if ((code[i] >= 0xf80000) && (code[i] <= 0xffffff)) {
                // Convert from BCD to binary
                fnum = code[i] & 0x0f;
                fnum += ((code[i] & 0x000f0) >> 4) * 10;
                fnum += ((code[i] & 0x00f00) >> 8) * 100;
                fnum += ((code[i] & 0x0f000) >> 12) * 1000;
                fnum += ((code[i] & 0xf0000) >> 16) * 10000;
                if (fnum >= 80000) fnum -= 80000;
                qDebug() << i << "CAV frame" << fnum;
                if (i % 2) odd = true;
                if (!(i % 2)) even = true;
            }
        }
    }
    qDebug() << "fnum" << fnum;

    flags = (clv ? FRAME_INFO_CLV : 0) | (even ? FRAME_INFO_CAV_EVEN : 0) |
            (odd ? FRAME_INFO_CAV_ODD : 0) | (cx ? FRAME_INFO_CX : 0);
    flags |= checkWhiteFlag(4) ? FRAME_INFO_WHITE_EVEN : 0;
    flags |= checkWhiteFlag(5) ? FRAME_INFO_WHITE_ODD  : 0;

    qDebug() << "Status" << hex << flags << dec << "chapter" << chap;

    frameBuffer[0][12] = chap;
    frameBuffer[0][13] = flags;
    frameBuffer[0][14] = fnum >> 16;
    frameBuffer[0][15] = fnum & 0xffff;
    frameBuffer[0][16] = clv_time >> 16;
    frameBuffer[0][17] = clv_time & 0xffff;
}

// Configuration parameter handling functions -----------------------------------------

// Set f_diff
void TbcNtsc::setShowDifferenceBetweenPixels(bool setting)
{
    qInfo() << "setTol is not supported by the NTSC TBC" << setting;
    // Doesn't appear to do anything useful...  Should this be removed?
    //f_diff = setting;
}

// Set writeonfield
void TbcNtsc::setMagneticVideoMode(bool setting)
{
    if (setting) qInfo() << "Magnetic video mode is selected";
    if (setting) writeOnField = 1;
    else writeOnField = 2;
}

// Set f_flip
void TbcNtsc::setFlipFields(bool setting)
{
    if (setting) qInfo() << "Flip fields is selected";
    f_flip = setting;
}

// Set audio_only
void TbcNtsc::setAudioOnly(bool setting)
{
    if (setting) qInfo() << "Audio only is selected";
    audio_only = setting;
}

// Toggle do_autoset
void TbcNtsc::setPerformAutoSet(bool setting)
{
    if (setting) qInfo() << "Audio ranging is selected";
    if (setting) performAutoRanging = !performAutoRanging;
}

// Set despackle
void TbcNtsc::setPerformDespackle(bool setting)
{
    if (setting) qInfo() << "Despackle is selected";
    f_despackle = setting; // Seems to be always forced to false?
}

// Set freeze_frame
void TbcNtsc::setPerformFreezeFrame(bool setting)
{
    if (setting) qInfo() << "Perform freeze frame is selected";
    freeze_frame = setting;
}

// Set seven_five
void TbcNtsc::setPerformSevenFive(bool setting)
{
    if (setting) qInfo() << "Perform seven-five is selected";
    seven_five = setting;
}

// Toggle f_highburst
void TbcNtsc::setPerformHighBurst(bool setting)
{
    if (setting) qInfo() << "Perform high-burst is selected";
    if (setting) f_highburst = !f_highburst;
}

// Set the source video file's file name
void TbcNtsc::setSourceVideoFile(QString stringValue)
{
    sourceVideoFileName = stringValue;
}

// Set the source audio file's file name
void TbcNtsc::setSourceAudioFile(QString stringValue)
{
    sourceAudioFileName = stringValue;
}

// Set the target video file's file name
void TbcNtsc::setTargetVideoFile(QString stringValue)
{
    targetVideoFileName = stringValue;
}

// Set f_tol
void TbcNtsc::setTol(double_t value)
{
    qInfo() << "setTol is not supported by the NTSC TBC" << (double)value;
    //f_tol = value;
}

// Set p_rotdetect
void TbcNtsc::setRot(double_t value)
{
    qInfo() << "setRot is not supported by the NTSC TBC" << (double)value;
    //p_rotdetect = value;
}

// Set skip frames
void TbcNtsc::setSkipFrames(qint32 value)
{
    p_skipframes = value;
}

// Set maximum frames
void TbcNtsc::setMaximumFrames(qint32 value)
{
    p_maxframes = value;
}


