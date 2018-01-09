/************************************************************************

    tcbpal.cpp

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

#include "tbcpal.h"
#include "../../deemp.h"

// Notes from Simon:
//
// All of the constants in the previous version of the TBC have been removed
// (especially the #define constants) - this is because that style of coding is
// suboptimal for a class-based structure.  Here everything is encapsulated by the
// class; it's not super neat everywhere yet, but it's getting there...
//
// The basic aim of the rewrite is to improve the general maintainability of the code
// through the use of structure, encapsulation, readability and comments.
//
// The secondary aim is to allow the NTSC and PAL TBC code to be merged into a single
// code-base to improve reuse and help keep the NTSC and PAL code in sync.
//
// There are a number of points in the code where I'm not sure of the purpose; these
// are marked with appropriate comments and should be replaced with explanations.


// Class constructor function
TbcPal::TbcPal(quint16 fscSetting)
{
    // Note: FSC must be an even number
    // This was controlled by a define statement that
    // seemed to support FSC4, FSC10 or C32MHZ...
    switch(fscSetting) {
    case 10: // 10FSC
        c32mhz = false;
        videoInputFrequencyInFsc = 10.0;	// 10 FSC
        pal_iplinei = 229 * videoInputFrequencyInFsc; // pixels per line
        pal_ipline = 229 * videoInputFrequencyInFsc; // pixels per line
        pixels_per_usec = 1000000.0 / (videoInputFrequencyInFsc * (1000000.0 * 315.0 / 88.0));

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync10); // autoRange() uses this
        f_syncid = new Filter(f_syncid10);
        syncid_offset = syncid10_offset;
        break;

    case 32: // C32MHZ
        c32mhz = true;
        videoInputFrequencyInFsc = 32.0 / (315.0 / 88.0); // = 8.93
        pal_iplinei = 2048; // pixels per line
        pal_ipline = 2048; // pixels per line
        pixels_per_usec = 1000000.0 / 2048.0;

        // Filters  (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync32); // autoRange() uses this
        f_syncid = new Filter(f_syncid32);
        syncid_offset = syncid32_offset;
        break;

    case 4: // FSC4
        c32mhz = false;
        videoInputFrequencyInFsc = 4.0;
        pal_iplinei = 229 * videoInputFrequencyInFsc; // pixels per line
        pal_ipline = 229 * videoInputFrequencyInFsc; // pixels per line
        pixels_per_usec = 1000000.0 / (videoInputFrequencyInFsc * (1000000.0 * 315.0 / 88.0));

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync4); // autoRange() uses this
        f_syncid = new Filter(f_syncid4);
        syncid_offset = syncid4_offset;
        break;

    default:
        c32mhz = false;
        videoInputFrequencyInFsc = 8.0;
        pal_iplinei = 229 * videoInputFrequencyInFsc; // pixels per line
        pal_ipline = 229 * videoInputFrequencyInFsc; // pixels per line
        pixels_per_usec = 1000000.0 / (videoInputFrequencyInFsc * (1000000.0 * 315.0 / 88.0));

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync); // autoRange() uses this
        f_syncid = new Filter(f_syncid8);
        syncid_offset = syncid8_offset;
    }

    // File names
    setSourceVideoFile(""); // Default is empty
    setSourceAudioFile(""); // Default is empty
    setTargetVideoFile(""); // Default is empty

    // Default tol setting
    setTol(1.5); // f_tol = 1.5;

    // Set global configuration settings

    // Global 'configuration'
    f_diff = false; // Used in processVideoLineIntoFrame()
    writeOnField = 2;
    f_flip = false;
    audio_only = false;
    performAutoRanging = (videoInputFrequencyInFsc == 4); // True/false
    freeze_frame = false;
    despackle = false; // The functions around this seem to be perma-disabled...
    seven_five = (videoInputFrequencyInFsc == 4); // True/false
    f_highburst = (videoInputFrequencyInFsc == 4); // True/false
    p_rotdetect = 2000;

    // Set 'constants' - All need better comments
    pal_opline = 1052; // pixels per line

    // Include everything from first sync to end of second sync, plus padding
    // 1 (padding) + 64 (line) + 4.7 (sync) + 1 padding = 72.35
    pal_blanklen = 6.7;
    scale_linelen = (70.7 / 64);

    pal_ihsynctoline = pal_ipline * (pal_blanklen / 64);
    iscale15_len = pal_ipline + pal_ihsynctoline;

    pal_hsynctoline = pal_opline * (pal_blanklen / 64);

    // What are these for and what do they contain?
    outputFrequencyInFsc = 4; // in FSC.  Must be an even number!
    burstFrequencyMhz = 4.43361875;
    scale15_len = 15000000.0 * (70.7 / 1000000.0); // contains padding
    scale4fsc_len = 4 * 4433618 * (70.7 / 1000000.0); // endsync to next endsync
    a_read = 0;
    v_read = 0;
    va_ratio = 80;

    // Input scale is from -95 IRE (for pilot signal) to 145 IRE
    // which is a sweep of 240 IRE. 65535 / 240 = 273.0625
    inputMaximumIreLevel = 273.06;
    inputMinimumIreLevel = (inputMaximumIreLevel * 95); // 0 IRE

    // Globals for processAudio()
    processAudioState.afreq = 48000;
    processAudioState.prev_time = -1;
    processAudioState.next_audsample = 0;
    processAudioState.prev_loc = -1;
    processAudioState.prev_index = 0;
    processAudioState.prev_i = 0;

    // Globals for processAudioSample()
    processAudioState._audioChannelOne = 0;
    processAudioState._audioChannelTwo = 0;
    processAudioState.f_fml = new Filter(f_fmdeemp);
    processAudioState.f_fmr = new Filter(f_fmdeemp);
    processAudioState.audioOutputBufferPointer = 0;

    // Globals to do with the line processing functions
    // handlebadline() and processline()
    lineProcessingState.tline = 0;
    lineProcessingState.line = -2;
    lineProcessingState.phase = -1;
    lineProcessingState.first = true;
    lineProcessingState.prev_linelen = pal_ipline;
    lineProcessingState.prev_offset_begin = 0.0;
    lineProcessingState.prev_offset_end = 0.0;
    lineProcessingState.prev_begin = 0;
    lineProcessingState.prev_end = 0;
    lineProcessingState.prev_beginlen = 0;
    lineProcessingState.prev_endlen = 0;
    lineProcessingState.prev_lvl_adjust = 1.0;
    lineProcessingState.frameno = -1;
}

// Execute the time-based correction process
// Returns:
//       0 on success
//      -1 on failure
qint32 TbcPal::execute(void)
{
    // Show some info in the output
    qInfo() << "PAL laserdisc time-based correction (TBC)";
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
    qint32 videoBufferNumberOfElements = ((qint64)pal_iplinei * 1100);	// should be divisible evenly by 16
    qint32 audioBufferNumberOfElements = ((qint64)pal_iplinei * 1100) / 40;

    // Ensure that our buffer vectors are the correct length
    videoBuffer.resize(videoBufferNumberOfElements);
    audioBuffer.resize(audioBufferNumberOfElements);

    QFile* audioInputFileHandle;
    QFile* videoInputFileHandle;
    QFile* videoOutputFileHandle;
    bool processAudioData = false;

    // Set the expected video sync level to -30 IRE
    quint16 videoSyncLevel = ire_to_in(-30); // inbase + (inscale * 15);

    // Show the configured video input frequency in FSC (what does FSC stand for?)
    qDebug() << "Video input frequency (FSC) = " << (double)videoInputFrequencyInFsc;

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
                                                                                     audioBuffer, processAudioData, videoSyncLevel,
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
quint16 TbcPal::autoRange(QVector<quint16> videoBuffer)
{
    QVector<double_t> longSyncFilterResult(videoBuffer.size());
    qint32 checklen = (qint32)(videoInputFrequencyInFsc * 4);

    // Set the low and high default values which get modified
    // as we read through the data.  The input data is quint32
    // so the maximum and minimum possible values are 65535 and 0
    double_t low = 65535;
    double_t high = 0;

    qInfo() << "Performing auto-ranging";
    qInfo() << "Scale before auto-ranging is =" << (double)inputMinimumIreLevel << ":" << (double)inputMaximumIreLevel ;

    //	f_longsync.clear(0);

    // Phase 1:  Get the low (-40 IRE) and high (?? IRE) values
    for (qint32 currentVideoBufferElement = 0; currentVideoBufferElement < videoBuffer.size(); currentVideoBufferElement++) {
        // This feed a value into the filter (purpose unknown) and gets a result back
        longSyncFilterResult[currentVideoBufferElement] = longSyncFilter->feed(videoBuffer[currentVideoBufferElement]);

        // No idea what this logic is doing? But it finds the lowest value for 'low'
        if ((currentVideoBufferElement > (videoInputFrequencyInFsc * 256)) &&
                (longSyncFilterResult[currentVideoBufferElement] < low) &&
                (longSyncFilterResult[currentVideoBufferElement - checklen] < low)) {
            if (longSyncFilterResult[currentVideoBufferElement - checklen] > longSyncFilterResult[currentVideoBufferElement])
                low = longSyncFilterResult[currentVideoBufferElement - checklen];
            else
                low = longSyncFilterResult[currentVideoBufferElement];
        }

        // No idea what this logic is doing? But it finds the highest value for 'high'
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
    inputMaximumIreLevel = (high - low) / 140.0;
    inputMinimumIreLevel = low;	// Should be in the range of -40 IRE to -60 IRE

    // Range check the minimum IRE level
    // Note: at level 1 all the peak detection fails... not sure this is a sane enough sanity check...
    if (inputMinimumIreLevel < 1) inputMinimumIreLevel = 1;

    // Show the result
    qInfo() << "Scale after auto-ranging is =" << (double)inputMinimumIreLevel << ":" << (double)inputMaximumIreLevel;
    qInfo() << "low =" << (double)low << "high =" << (double)high;

    // Calculate the resulting video sync level
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
qint32 TbcPal::processVideoAndAudioBuffer(QVector<quint16> videoBuffer, qint32 videoBufferElementsToProcess,
                                          QVector<double_t> audioBuffer, bool processAudioData, quint16 videoSyncLevel,
                                          bool *isVideoFrameBufferReadyForWrite)
{
    // Set the write buffer flag to a default of false (do not write)
    *isVideoFrameBufferReadyForWrite = false;

    // The lineDetails vector is used to store the details of the analysed video lines
    // As new video lines are detected they are pushed into 'lineDetails' and the resulting
    // size of the vector is used to indicate the total number of detected video lines
    // therefore, lineDetails isn't assigned a size here.
    QVector<LineStruct> lineDetails;

    // Deemphasis filter buffer - a vector of the same number of elements as videoBuffer
    QVector<quint16> deempFilterBuffer(videoBufferElementsToProcess);

    // What is this for???
    QVector<double_t> psync(videoBufferElementsToProcess);

    // Clear the video frame buffer
    memset(frameBuffer, 0, sizeof(frameBuffer));

    // Clear the line length and sync filters
    f_linelen.clear(pal_ipline);
    f_syncid->clear(0);

    // Apply the video line filters to the video buffer
    // Here we pass the vector buffers by reference as the filter code is very memory-access intensive
    applyVideoLineFilters(videoBuffer.data(), deempFilterBuffer.data(), psync.data(),
                          videoBufferElementsToProcess, videoSyncLevel);

    // No idea what this is doing???
    // Could be trying to determine where the line starts in the buffer?
    qDebug() << "Searching for peaks";
    for (qint32 currentVideoBufferElement = 0;
         currentVideoBufferElement < videoBufferElementsToProcess - syncid_offset;
         currentVideoBufferElement++) {
        double_t level = psync[currentVideoBufferElement];

        if ((level > .05) && (level > psync[currentVideoBufferElement - 1]) &&
                (level > psync[currentVideoBufferElement + 1])) {
            LineStruct line;

            line.beginSync = currentVideoBufferElement;
            line.endSync = currentVideoBufferElement;
            line.center = currentVideoBufferElement;
            line.peak   = level;
            line.isBad = false;
            line.lineNumber = -1;

            // Append the line to the lineDetails vector
            lineDetails.append(line);
        }
    } 

    // Just in case...
    if (lineDetails.size() == 0) {
        qInfo() << "No peaks detected! Cannot continue to process video lines.";
        return 0;
    } else qInfo() << "Detected" << lineDetails.size() << "peaks in video buffer";

    // If the first line detected in the video buffer cannot possibly end in the current video buffer
    // we have to pass back the start of the first line (which will cause the calling procedure to
    // shift the buffer back (so it begins with the first line) and provide enough additional data to
    // complete the line, so processing can start
    if (lineDetails[0].center > (pal_ipline * 300)) {
        qDebug() << "Incomplete first line in current video buffer";
        return pal_ipline * 300;
    }

    // If the first line was found, and the whole line is in the current video buffer, look for the first
    // field index and return that as the start of the first line
    qint32 firstpeak = -1;
    qint32 firstline = -1;
    qint32 lastline = -1;
    for (qint32 i = 9; (i < (qint32)lineDetails.size() - 9) && (firstline == -1); i++) {
        if (lineDetails[i].peak > 1.0) {
            if (lineDetails[i].center < (pal_ipline * 8)) {
                qDebug() << "Find first field index - First line is pal_ipline * 400";
                return (pal_ipline * 400); // Why 400?
            } else {
                if ((firstpeak < 0) && (lineDetails[i].center > (pal_ipline * 300))) {
                    qDebug() << "Find first field index - First line is pal_ipline * 300";
                    return pal_ipline * 300; // Why 300?
                }

                firstpeak = i;
                firstline = -1; lastline = -1;

                qDebug() << "First peak" << firstpeak <<
                            (double)lineDetails[firstpeak].peak <<
                            (double)lineDetails[firstpeak].center;

                for (qint32 i = firstpeak - 1; (i > 0) && (lastline == -1); i--) {
                    if ((lineDetails[i].peak > 0.2) && (lineDetails[i].peak < 0.75)) lastline = i;
                }

                qint32 distance_prev = lineDetails[lastline + 1].center - lineDetails[lastline].center;
                qint32 synctype = (distance_prev > (videoInputFrequencyInFsc * 140)) ? 1 : 2;

                if (f_flip) {
                    synctype = (distance_prev > (videoInputFrequencyInFsc * 140)) ? 2 : 1;
                }

                qDebug() << "P1_" <<
                            lastline <<
                            synctype <<
                            ((double)videoInputFrequencyInFsc * 140) <<
                            distance_prev <<
                            (double)lineDetails[lastline + 1].center - (double)lineDetails[lastline].center;

                for (qint32 i = firstpeak + 1; (i < (qint32)lineDetails.size()) && (firstline == -1); i++) {
                    if ((lineDetails[i].peak > 0.2) && (lineDetails[i].peak < 0.75)) firstline = i;
                }

                qDebug() << firstline << (double)lineDetails[firstline].center - (double)lineDetails[firstline-1].center;
                qDebug() << synctype << writeOnField;

                if (synctype != writeOnField) {
                    firstline = firstpeak = -1;
                    i += 6;
                }
            }
        }
    }

    qDebug() << "Number of peaks =" << lineDetails.size();

    bool field2 = false;
    qint32 line = -10;

    // To-do:
    // There seems to be an exception happening around this point in the code where the debug
    // keeps outputing LONG followed by SHORT and the loop never ends.  Some error handling
    // code would be a good idea here as it causes an infinite loop sometimes...
    //
    // Seems to be caused by the fact that both the short and long handling code uses lineCounter
    // as the counter for the for loop, and both contain lineCounter--; which can cause the for
    // loop to never exit
    qint32 catchLoopingException = 0;

    // Process the lines to perform peak detection
    qInfo() << "Performing detection of video lines";
    for (qint32 lineCounter = firstline - 2;
         (lineCounter < (firstline + 650)) && (line < 623) && (lineCounter < (qint32)lineDetails.size());
         lineCounter++) {

        // Catch looping exception described in the comment above
        catchLoopingException++;
        if (catchLoopingException > 10000) {
            qFatal("processVideoAndAudioBuffer() is stuck - Aborting");
            exit(1);
        }

        bool canStartSync = false;
        if ((line < 0) || inRange(line, 310, 317) || inRange(line, 623, 630)) canStartSync = true;

        if (!canStartSync && ((lineDetails[lineCounter].center - lineDetails[lineCounter - 1].center) >
                              (400 * videoInputFrequencyInFsc)) && (lineDetails[lineCounter].center >
                                                                    lineDetails[lineCounter - 1].center)) {
            // Looks like we completely skipped a video line because of corruption - add a new one
            qDebug() << "LONG video line detected:" << lineCounter <<
                        (double)lineDetails[lineCounter].center <<
                        (double)lineDetails[lineCounter].center - (double)lineDetails[lineCounter - 1].center <<
                        lineDetails.size();

            LineStruct l;

            l.center = lineDetails[lineCounter - 1].center + 1820;
            l.peak   = lineDetails[lineCounter - 1].peak;
            l.isBad = true;
            l.lineNumber = -1;

            lineDetails.insert(lineDetails.begin()+lineCounter, l);

            lineCounter--;
            line--;
        } else if (!canStartSync && ((lineDetails[lineCounter].center - lineDetails[lineCounter - 1].center) <
                                     (207.5 * videoInputFrequencyInFsc)) &&
                   (lineDetails[lineCounter].center > lineDetails[lineCounter - 1].center)) {
            qDebug() << "SHORT video line detected:" << lineCounter <<
                        (double)lineDetails[lineCounter].center <<
                        (double)lineDetails[lineCounter].center - (double)lineDetails[lineCounter - 1].center <<
                        lineDetails.size();

            lineDetails.erase(lineDetails.begin()+lineCounter);
            lineCounter--;
            line--;
        } else if (inRange(lineDetails[lineCounter].peak, canStartSync ? 0.25 : 0.0, 0.5)) {
            qint32 cbeginsync = 0;
            qint32 cendsync = 0;
            qint32 center = lineDetails[lineCounter].center;

            if (line <= -1) {
                line = field2 ? 318 : 10;
                field2 = true;
            }

            lineDetails[lineCounter].beginSync = lineDetails[lineCounter].endSync = -1;
            for (qint32 x = 0;
                 x < 200 && inRange(lineDetails[lineCounter].peak, 0.20, 0.5) &&
                 ((lineDetails[lineCounter].beginSync == -1) || (lineDetails[lineCounter].endSync == -1));
                 x++) {
                cbeginsync++;
                cendsync++;

                if (videoBuffer[center - x] < ire_to_in(-17.0)) cbeginsync = 0;
                if (videoBuffer[center + x] < ire_to_in(-17.0)) cendsync = 0;

                if ((cbeginsync == 4) && (lineDetails[lineCounter].beginSync < 0))
                    lineDetails[lineCounter].beginSync = center - x + 4;
                if ((cendsync == 4) && (lineDetails[lineCounter].endSync < 0))
                    lineDetails[lineCounter].endSync = center + x - 4;
            }

            // This next comment seems to be refering to NTSC... but this is PAL code?
            // This is asymmetric since on an NTSC player playback is sped up to 1820 pixels/line
            double_t prev_linelen_cf = clamp(lineProcessingState.prev_linelen / videoInputFrequencyInFsc, 224.0, 232.0);

            // Subtract the begining of sync from the end of sync and see if the result is in the expected
            // frequency(?)/FSC(?) range
            lineDetails[lineCounter].isBad =
                    !inRangeF(lineDetails[lineCounter].endSync - lineDetails[lineCounter].beginSync, 14.5, 20.5);

            // If the previous video line was good do something else which I don't understand to
            // the current video line
            if (!lineDetails[lineCounter - 1].isBad) {
                lineDetails[lineCounter].isBad |= get_oline(line) > 22 &&
                    (!inRangeF(lineDetails[lineCounter].beginSync - lineDetails[lineCounter-1].beginSync,
                     prev_linelen_cf - f_tol, prev_linelen_cf + f_tol) ||
                    !inRangeF(lineDetails[lineCounter].endSync - lineDetails[lineCounter-1].endSync,
                        prev_linelen_cf - f_tol, prev_linelen_cf + f_tol));
            }

            lineDetails[lineCounter].lineNumber = line;

            // Show the details of the detected line in the debug output
            qDebug() << qSetRealNumberPrecision(10) << "P2_" <<
                        line <<
                        lineCounter <<
                        lineDetails[lineCounter].isBad <<
                        (double)lineDetails[lineCounter].peak <<
                        (double)lineDetails[lineCounter].center <<
                        (double)lineDetails[lineCounter].center - (double)lineDetails[lineCounter-1].center <<
                        (double)lineDetails[lineCounter].beginSync <<
                        (double)lineDetails[lineCounter].endSync <<
                        (double)lineDetails[lineCounter].endSync - (double)lineDetails[lineCounter].beginSync <<
                        (double)lineDetails[lineCounter].beginSync - (double)lineDetails[lineCounter-1].beginSync <<
                        (double)lineProcessingState.prev_linelen;

            // HACK! - Why is this a hack? - what should it be?
            if (line == 318) lineDetails[lineCounter].lineNumber = -1;

            // If we have a good line, feed it's length to the line LPF (low-pass filter).  The 8 line lag is insignificant
            // since it's a ~30hz oscillation - Why is a LPF used here??
            double_t linelen = lineDetails[lineCounter].beginSync - lineDetails[lineCounter-1].beginSync;
            if (!lineDetails[lineCounter].isBad && !lineDetails[lineCounter - 1].isBad && inRangeF(linelen, 227.5 - 4, 229 + 4)) {
//				qDebug() << "Feeding " << linelen ;
                lineProcessingState.prev_linelen = f_linelen.feed(linelen);
            }
        } else if (lineDetails[lineCounter].peak > .9) {
            qDebug() << "P2A_0 " << lineCounter << ' ' << (double)lineDetails[lineCounter].peak ;
            line = -10;
            lineDetails[lineCounter].lineNumber = -1;
        }
        line++;
    }

    // Here we look through the resulting 'lineDetails' vector looking for bad lines
    // and, if found, we send them to the handleBadLine function
    line = -1;
    for (qint32 peakCounter = firstline - 1;
         (peakCounter < (firstline + 650)) && (line < 623) && (peakCounter < (qint32)lineDetails.size());
         peakCounter++) {

        // Added additional check here as it was possible for peakCounter to be -1 when calling handleBadLine
        if ((lineDetails[peakCounter].lineNumber > 0) && lineDetails[peakCounter].isBad && peakCounter >= 0) {
            handleBadLine(&lineDetails, peakCounter);
        }
    }

    // By this point we have one or more good lines with a known position, so that the lines can
    // be passed one by one to both the video line and audio 'line' processing.  The result is termed
    // a 'frame' and the resulting frames are stored in the video frame buffer for output (global)
    line = -1;
    qInfo() << "Processing video lines into corrected frames";
    for (qint32 peakCounter = firstline - 1;
         (peakCounter < (firstline + 650)) && (line < 623) && (peakCounter < (qint32)lineDetails.size());
         peakCounter++) {

        // Added additional check here as it was possible for peakCounter to be -1 when calling
        // processVideoLineIntoFrame (causing an exception on the vector)
        if ((lineDetails[peakCounter].lineNumber > 0) && (lineDetails[peakCounter].lineNumber <= 625) &&
                peakCounter >= 0) {
            line = lineDetails[peakCounter].lineNumber;

            // Show debug for every line
            qDebug() << "Processing line:" << line << "of 623 :" <<
                        peakCounter <<
                        lineDetails[peakCounter].isBad <<
                        (double)lineDetails[peakCounter].peak <<
                        (double)lineDetails[peakCounter].center <<
                        (double)lineDetails[peakCounter].center - (double)lineDetails[peakCounter-1].center <<
                        (double)lineDetails[peakCounter].beginSync <<
                        (double)lineDetails[peakCounter].endSync <<
                        (double)lineDetails[peakCounter].endSync - (double)lineDetails[peakCounter].beginSync;

            // Process the video line into a corrected video frame
            // Due to the intensity of the memory accessing, using a vector here is extremely slow...
            // So, we pass the pointer to the data (and I'll add an exception handler to the called function)
            processVideoLineIntoFrame(videoBuffer.data(), &lineDetails, peakCounter, false);

            // Process audio?
            if (processAudioData) {
                qInfo() << "PAudio " <<
                           (line / 625.0) + lineProcessingState.frameno <<
                           v_read + (double)lineDetails[peakCounter].beginSync;
                processAudio((line / 625.0) + lineProcessingState.frameno,
                             v_read + lineDetails[peakCounter].beginSync, audioBuffer.data());
            }

            if (lineDetails[peakCounter].isBad) {
                qint32 oline = get_oline(line);

                frameBuffer[oline][2] = 65000;
                frameBuffer[oline][3] = 48000;
                frameBuffer[oline][4] = 65000;
                frameBuffer[oline][5] = 48000;
            }
        }
    }

    // What does this do?
    if (!freeze_frame && lineProcessingState.phase >= 0) lineProcessingState.phase = !lineProcessingState.phase;

    // Increment the frame number
    lineProcessingState.frameno++;

    // Flag that the video frame buffer is ready to be written to disk:
    *isVideoFrameBufferReadyForWrite = true;

    // Done
    return lineDetails[firstline + 500].center;
}

// Function to apply the video line processing filters to the video buffer
// Note: I think these filters are cleaning up the video signal to expose the sync
// to make detection of the frames easier... but I'm not 100%
//
// The two filters are very expensive in terms of processing though.  Could be optimised?
//
// Returns:
//      deempFilterBuffer (by reference)
//      psync (by reference)
void TbcPal::applyVideoLineFilters(quint16 *videoBuffer, quint16 *deempFilterBuffer, double_t *psync,
                                   qint32 videoBufferElementsToProcess, quint16 videoSyncLevel)
{
    // This feeds the values from videoBuffer into a deemp filter and populates the output from
    // the filter into filtbuf.  The first 16 values are fed into the filter, but not stored
    // in the results - What is this for?
    qInfo() << "Applying deemphasis filter";
    for (qint32 currentVideoBufferElement = 0;
         currentVideoBufferElement < videoBufferElementsToProcess;
         currentVideoBufferElement++) {
        // Note: f_psync8 is a pre-generated filter from deemp.h with an unknown purpose
        double_t val = f_psync8.feed((double)videoBuffer[currentVideoBufferElement]);
        if (currentVideoBufferElement > 16) deempFilterBuffer[currentVideoBufferElement - 16] = (quint16)val;
    }

    // No idea what this is doing??? - performs some kind of de-emphasis on the video buffer
    qInfo() << "Applying sync filter";
    for (qint32 currentVideoBufferElement = 0;
         currentVideoBufferElement < videoBufferElementsToProcess;
         currentVideoBufferElement++) {
        double_t val = f_syncid->feed(deempFilterBuffer[currentVideoBufferElement] &&
                                      (deempFilterBuffer[currentVideoBufferElement] < videoSyncLevel));
        if (currentVideoBufferElement > syncid_offset) {
            psync[currentVideoBufferElement - syncid_offset] = val;
        }
    }
}

// Process a line of video into a frame
// Note: isCalledByRecursion lets the function know it was called by recursion
// and prevents the function calling itself again, limiting recursion to one level only
//
// Returns:
//      adjusted length of the line (double_t)
//      lineDetails (bad true/false) - pass by reference
double_t TbcPal::processVideoLineIntoFrame(quint16 *videoBuffer, QVector<LineStruct> *lineDetails,
                                           qint32 lineToProcess, bool isCalledByRecursion)
{
    // This is to protect against exceptions in the code below; see the note below for an explaination.
    if (lineDetails->size() <= (lineToProcess + 1) || lineToProcess < 0) {
        qCritical() << "processVideoLineIntoFrame called illegally and would cause an exception if we continued..." << isCalledByRecursion;
        exit(1);
    }

    // Fixed length array tout size is 8192 for *some* reason...
    // probably based on the size of another buffer but no reference provided...
    double_t tout[8192];
    double_t adjustLength = pal_ipline;
    qint32 pass = 0;

    double_t begin_offset;
    double_t end_offset;

    double_t plevel1;
    double_t plevel2;
    double_t nphase1;
    double_t nphase2;

    double_t burstLevel = 0;
    double_t burstPhase = 0;

    qint32 lineNum = (*lineDetails)[lineToProcess].lineNumber;
    qint32 oline = get_oline(lineNum);
    if (oline < 0) return 0;

    // Use 1 uSec of pixels to pad begin and end syncs
    double_t pixels_per_usec = 28.625;
    double_t beginSync = (*lineDetails)[lineToProcess].beginSync - pixels_per_usec;
    double_t endSync = (*lineDetails)[lineToProcess+1].endSync + pixels_per_usec;

    // Store the original syncs including the padding we just added
    double_t originalBeginSync = beginSync;
    double_t originalEndSync = endSync;

    // What's a tgt nphase?
    double_t tgt_nphase = 0;

    // PPL = Previous process line?
    qDebug() << qSetRealNumberPrecision(10) << "PPL" << lineNum <<
                (double)(*lineDetails)[lineToProcess].beginSync << (double)(*lineDetails)[lineToProcess+1].endSync <<
                (double)(*lineDetails)[lineToProcess+1].endSync - (double)(*lineDetails)[lineToProcess].beginSync;

    // PL = Process line?
    qDebug() << qSetRealNumberPrecision(10) << "PL" << lineNum << (double)beginSync
                << (double)endSync << (*lineDetails)[lineToProcess].isBad << (double)endSync - (double)beginSync;

    // If the length of the line is less than the video input frequency * 200 (why 200?), return the line length
    if ((endSync - beginSync) < (videoInputFrequencyInFsc * 200)) {
        qDebug() << "Line length too short - giving up";
        return (endSync - beginSync);
    }

    qDebug() << qSetRealNumberPrecision(10) << "ProcessLine " << (double)beginSync << (double)endSync ;

    // Scale the line to scale15_len
    scale(videoBuffer, tout, beginSync, endSync, scale15_len);

    qDebug() << "first pilot:";
    bool isPilotValid = pilotDetect(tout, 0, plevel1, nphase1);
    qDebug() << "second pilot:";
    pilotDetect(tout, 240, plevel2, nphase2);

    qDebug() << "Beginning pilot levels" << (double)plevel1
             << (double)plevel2 << "valid" << isPilotValid ;

    // Valid pilot detected?
    if (!isPilotValid) {
        // Invalid pilot
        qDebug() << "Invalid first pilot";
        beginSync += lineProcessingState.prev_offset_begin;
        endSync += lineProcessingState.prev_offset_end;

        scale(videoBuffer, tout, beginSync, endSync, scale4fsc_len);
        // goto wrap-up
    } else {
        // Valid pilot
        qDebug() << "Valid first pilot";
        adjustLength = (endSync - beginSync) / (scale15_len / pal_opline);

        double_t nadj1 = nphase1;
        double_t nadj2 = nphase2;

        for (pass = 0; (pass < 12) && ((fabs(nadj1) + fabs(nadj2)) > .005); pass++) {
            if (!pass) nadj2 = 0;

            qDebug() << "adjusting" << (double)nadj1 << (double)nadj2 ;

            beginSync += nadj1;
            endSync += nadj2;

            scale(videoBuffer, tout, beginSync, endSync, scale15_len);
            qDebug() << "first burst";
            pilotDetect(tout, 0, plevel1, nphase1);
            qDebug() << "second burst";
            pilotDetect(tout, 240, plevel2, nphase2);

            nadj1 = nphase1;
            nadj2 = nphase2;

            adjustLength = (endSync - beginSync) / (scale15_len / pal_opline);
        }

        qDebug() << "End Pilot levels " << pass << (double)plevel1 <<
                    ':' << (double)nphase1 << (double)plevel2 << ':' << (double)nphase2 << "valid" << isPilotValid ;

        begin_offset = beginSync - originalBeginSync;
        end_offset = endSync - originalEndSync;
        qDebug() << "Offset" << oline << (double)begin_offset <<
                    (double)end_offset << (double)endSync - (double)beginSync <<
                    ((double)beginSync - (double)lineProcessingState.prev_begin) * (70.7 / 64.0);

        // Was the function called due to recursion?
        // Only do this if the function is called externally (and not by itself)
        if (!isCalledByRecursion) {
            double_t orig_len = originalEndSync - originalBeginSync;
            double_t new_len = endSync - beginSync;

            double_t beginlen = beginSync - lineProcessingState.prev_begin;
            double_t endlen = endSync - lineProcessingState.prev_end;

            qDebug() << "len " << lineProcessingState.frameno + 1 << ":" << oline <<
                        (double)orig_len << (double)new_len << ' ' << (double)originalBeginSync <<
                        (double)beginSync << (double)originalEndSync << (double)endSync ;

            if ((fabs(lineProcessingState.prev_endlen - endlen) > (outputFrequencyInFsc * f_tol)) ||
                    (fabs(lineProcessingState.prev_beginlen - beginlen) > (outputFrequencyInFsc * f_tol))) {
                qDebug() << "ERRP len" << lineProcessingState.frameno + 1 << ":" <<
                            oline << (double)lineProcessingState.prev_beginlen - (double)beginlen <<
                            (double)lineProcessingState.prev_endlen - (double)endlen;
                qDebug() << "ERRP gap" << lineProcessingState.frameno + 1 << ":" <<
                            oline << (double)beginSync - (double)lineProcessingState.prev_begin <<
                            (double)endSync - (double)lineProcessingState.prev_end;

                if (oline > 25) {
                    (*lineDetails)[lineToProcess].isBad = true;
                    handleBadLine(&(*lineDetails), lineToProcess);
                } else {
                    handleBadLine(&(*lineDetails), lineToProcess);
                }

                // Recurse
                return processVideoLineIntoFrame(videoBuffer, lineDetails, lineToProcess, true);
            }
        }

        qDebug() << "Final levels" << (double)plevel1 << (double)plevel2 ;
        beginSync += 4.0 * (burstFrequencyMhz / 3.75);
        endSync += 4.0 * (burstFrequencyMhz / 3.75);

        if (c32mhz) scale(videoBuffer, tout, beginSync - 8, endSync + 1, scale4fsc_len);
        else scale(videoBuffer, tout, beginSync, endSync, scale4fsc_len);

        burstDetect(tout, 120, 164, burstLevel, burstPhase);
        qDebug() << "BURST" << get_oline(lineNum) << lineNum <<
                    (double)burstLevel << (double)burstPhase ;
    }

    // Perform wrap-up
    // LD only: need to adjust output value for velocity, and remove defects as possible
    double_t lvl_adjust = 1.0;
    qint32 ldo = -128;

    if ((*lineDetails)[lineToProcess].isBad) {
        lvl_adjust = lineProcessingState.prev_lvl_adjust;
    } else {
        lineProcessingState.prev_lvl_adjust = lvl_adjust;
    }

    qDebug() << lineNum << "leveladj" << (*lineDetails)[lineToProcess].isBad << (double)lvl_adjust ;

    // Write the resulting line to the (time corrected)) video frame buffer
    double_t rotdetect = p_rotdetect * inputMaximumIreLevel;

    double_t diff[1052]; // Needs to be the same as the video frame buffer width?
    double_t prev_o = 0;
    for (qint32 h = 0; (oline > 2) && (h < 1052); h++) {
        double_t v = tout[h + 94 ];
        double_t ire = in_to_ire(v);
        double_t o;

        if (videoInputFrequencyInFsc != 4) {
            // PAL signal is 6757143Hz (0 IRE) to 7900000Hz (100 IRE)
            // Fixing this here seems to cause the comb filter to over expose the frames, but the settings
            // here are not according to the IEC specification for PAL laserdiscs...
            double_t freq = (ire * ((8000000 - 7100000) / 100)) + 7100000;
            freq *= lvl_adjust;
            ire = ((freq - 7100000) / 800000) * 100; // Note: the original value is 800,000 not 8,000,000 here...
            o = ire_to_out(ire);
        } else {
            o = ire_to_out(in_to_ire(v));
        }

        // Perform despackle?  Whatever that is...
        if (despackle && (h > (20 * outputFrequencyInFsc)) && ((fabs(o - prev_o) > rotdetect) || (ire < -25))) {
            qDebug() << "Performing video frame despackle";
            if ((h - ldo) > 16) {
                for (qint32 j = h - 4; j > 2 && j < h; j++) {
                    double_t to = (frameBuffer[oline - 2][j - 2] + frameBuffer[oline - 2][j + 2]) / 2;
                    frameBuffer[oline][j] = clamp(to, 0, 65535);
                }
            }
            ldo = h;
        }

        // No idea what this bit of code is doing
        if (((h - ldo) < 16) && (h > 4)) {
            o = (frameBuffer[oline - 2][h - 2] + frameBuffer[oline - 2][h + 2]) / 2;
        }

        frameBuffer[oline][h] = (quint16)clamp(o, 0, 65535);
        diff[h] = o - prev_o;
        prev_o = o;
    }

    // Do some more unspecified stuff...
    for (qint32 h = 0; f_diff && (oline > 2) && (h < 1052); h++) {
        frameBuffer[oline][h] = (quint16)clamp(diff[h], 0, 65535);
    }

        if (!pass) {
                frameBuffer[oline][2] = 32000;
                frameBuffer[oline][3] = 32000;
                frameBuffer[oline][4] = 32000;
                frameBuffer[oline][5] = 32000;
        qDebug() << "BURST ERROR" << lineNum << pass <<
                    (double)beginSync << ((double)beginSync + (double)adjustLength) << '/' << (double)endSync;
        } else {
        lineProcessingState.prev_offset_begin = beginSync - originalBeginSync;
        lineProcessingState.prev_offset_end = beginSync - originalBeginSync;
    }

    qDebug() << lineNum << get_oline(lineNum) << "FINAL" <<
                (double)lineProcessingState.prev_begin << (double)beginSync - (double)lineProcessingState.prev_begin <<
                (double)endSync - (double)lineProcessingState.prev_end << (double)beginSync << (double)endSync;

    frameBuffer[oline][0] = (quint16)((tgt_nphase != 0) ? 32768 : 16384);
    frameBuffer[oline][1] = (quint16)plevel1;

    beginSync -= 4.0 * (burstFrequencyMhz / 3.75);
    endSync -= 4.0 * (burstFrequencyMhz / 3.75);
    lineProcessingState.prev_beginlen = beginSync - lineProcessingState.prev_begin;
    lineProcessingState.prev_endlen = endSync - lineProcessingState.prev_end;

    lineProcessingState.prev_begin = beginSync;
    lineProcessingState.prev_end = endSync;

    return adjustLength;
}

// What is this function is for...
// Analyse a bad video line and attempt to correct based on an unspecified method?
// lg is 'last good' or something like that...
// Probably replaces the current bad line with the last seen good line?
// A type of drop-out detection?
void TbcPal::handleBadLine(QVector<LineStruct> *lineDetails, qint32 lineToProcess)
{
    qint32 line = (*lineDetails)[lineToProcess].lineNumber;

    // BAD
    qDebug() << "BAD " << lineToProcess << line <<
                (double)(*lineDetails)[lineToProcess].beginSync <<
                (double)(*lineDetails)[lineToProcess].center <<
                (double)(*lineDetails)[lineToProcess].endSync <<
                (double)(*lineDetails)[lineToProcess].endSync - (double)(*lineDetails)[lineToProcess].beginSync;

    qint32 lg = 1;

    for (lg = 2;
         lg < 8 && ((lineToProcess - lg) >= 0) && ((lineToProcess + lg) < (qint32)(*lineDetails).size()) &&
         ((*lineDetails)[lineToProcess - lg].isBad || (*lineDetails)[lineToProcess + lg].isBad);
         lg++);

    qDebug() << (double)(*lineDetails)[lineToProcess-lg].beginSync <<
                (double)(*lineDetails)[lineToProcess-lg].center <<
                (double)(*lineDetails)[lineToProcess-lg].endSync <<
                (double)(*lineDetails)[lineToProcess-lg].endSync - (double)(*lineDetails)[lineToProcess-lg].beginSync;

    // BADLG
    double_t gap = ((*lineDetails)[lineToProcess + lg].beginSync - (*lineDetails)[lineToProcess - lg].beginSync) / (lg * 2);

    (*lineDetails)[lineToProcess].beginSync = (*lineDetails)[lineToProcess - lg].beginSync + (gap * lg);
    (*lineDetails)[lineToProcess].center = (*lineDetails)[lineToProcess - lg].center + (gap * lg);
    (*lineDetails)[lineToProcess].endSync = (*lineDetails)[lineToProcess - lg].endSync + (gap * lg);

    qDebug() << "BADLG " << lg <<
                (double)(*lineDetails)[lineToProcess].beginSync <<
                (double)(*lineDetails)[lineToProcess].center <<
                (double)(*lineDetails)[lineToProcess].endSync <<
                (double)(*lineDetails)[lineToProcess].endSync - (double)(*lineDetails)[lineToProcess].beginSync;
    qDebug() << (double)(*lineDetails)[lineToProcess+lg].beginSync <<
                (double)(*lineDetails)[lineToProcess+lg].center <<
                (double)(*lineDetails)[lineToProcess+lg].endSync <<
                (double)(*lineDetails)[lineToProcess+lg].endSync - (double)(*lineDetails)[lineToProcess+lg].beginSync;
}

// Process a video frame's worth of audio
void TbcPal::processAudio(double_t frame, qint64 loc, double_t *audioBuffer)
{
    qDebug() << "Processing audio frame";
    double_t time = frame / (30000.0 / 1001.0);

    if (processAudioState.prev_time >= 0) {
        while (processAudioState.next_audsample < time) {
            double_t i1 =
                    (processAudioState.next_audsample - processAudioState.prev_time) / (time - processAudioState.prev_time);
            qint64 i = (i1 * (loc - processAudioState.prev_loc)) + processAudioState.prev_loc;

            if (i < v_read) {
                processAudioSample(processAudioState.f_fml->filterValue(), processAudioState.f_fmr->filterValue());
            } else {
                qint64 index = (i / va_ratio) - a_read;
                if (index >= (qint64)(sizeof(audioBuffer) / sizeof(double_t))) {
                    qDebug() << "Audio error" <<
                                (double)frame <<
                                (double)time <<
                                (double)i1 <<
                                i <<
                                index <<
                                (sizeof(audioBuffer) / sizeof(double_t));

                    index = (sizeof(audioBuffer) / sizeof(double_t)) - 1;
                }

                float_t left = audioBuffer[index * 2], right = audioBuffer[(index * 2) + 1];
                qDebug() << "A" <<
                            (double)frame <<
                            loc <<
                            (double)i1 <<
                            i <<
                            i - processAudioState.prev_i <<
                            index <<
                            index - processAudioState.prev_index <<
                            (float)left <<
                            (float)right;

                processAudioState.prev_index = index;
                processAudioState.prev_i = i;
                processAudioSample(left, right);
            }

            processAudioState.next_audsample += 1.0 / processAudioState.afreq;
        }
    }

    processAudioState.prev_time = time;
    processAudioState.prev_loc = loc;
}

// Process a sample of audio (from what to what?)
void TbcPal::processAudioSample(double_t channelOne, double_t channelTwo)
{
    channelOne *= (65535.0 / 300000.0);
    channelOne = processAudioState.f_fml->feed(channelOne);
    channelOne += 32768;

    channelTwo *= (65535.0 / 300000.0);
    channelTwo = processAudioState.f_fmr->feed(channelTwo);
    channelTwo += 32768;

    processAudioState._audioChannelOne = channelOne;
    processAudioState._audioChannelTwo = channelTwo;

    processAudioState.audioOutputBuffer[processAudioState.audioOutputBufferPointer * 2] =
            clamp(channelOne, 0, 65535);
    processAudioState.audioOutputBuffer[(processAudioState.audioOutputBufferPointer * 2) + 1] =
            clamp(channelTwo, 0, 65535);

    processAudioState.audioOutputBufferPointer++;
    if (processAudioState.audioOutputBufferPointer == 256) {
        //qint32 rv =
        qWarning() << "Writing audio is not currently implemented!";
        //write(audio_only ? 1 : 3, aout, sizeof(aout));

        processAudioState.audioOutputBufferPointer = 0;
    }
}

// If value is less than lowValue, function returns lowValue
// If value is greated than highValue, function returns highValue
// otherwise function returns value
inline double_t TbcPal::clamp(double_t value, double_t lowValue, double_t highValue)
{
        if (value < lowValue) return lowValue;
        else if (value > highValue) return highValue;
        else return value;
}

// Convert from input scale to IRE
inline double_t TbcPal::in_to_ire(quint16 level)
{
    if (level == 0) return -100;

    return ((double_t)(level - inputMinimumIreLevel) / inputMaximumIreLevel);
}

// Convert from IRE to input scale
inline quint16 TbcPal::ire_to_in(double_t ire)
{
    if (ire <= -95) return 0;

    return clamp((ire * inputMaximumIreLevel) + inputMinimumIreLevel, 1, 65535);
}

// Convert from IRE to output scale
inline quint16 TbcPal::ire_to_out(double_t ire)
{
    if (ire <= -60) return 0;

    return clamp(((ire + 60) * 327.68) + 1, 1, 65535);
}

// No idea what this function is for
inline double_t TbcPal::peakdetect_quad(double_t *y)
{
    return (2 * (y[2] - y[0]) / (2 * (2 * y[1] - y[0] - y[2])));
}

// Note: Processing performance could probably be improved by changing
// the interpolate to act directly on the data (rather than one element
// at a time)...

// Perform bicubic interpolation of the passed values
// taken from http://www.paulinternet.nl/?page=bicubic
inline double_t TbcPal::cubicInterpolate(quint16 *y, double_t x)
{
    double_t p[4];
    p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

    return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
}

// This function takes a video line that is the wrong length
// and interpolates the line to the correct (predicted) length
inline void TbcPal::scale(quint16 *videoBuffer, double_t *outbuf, double_t start, double_t end, double_t outlen)
{
    double_t inlen = end - start;
    double_t perpel = inlen / outlen;

    qDebug() << "Scale " << (double)start << ' ' << (double)end << ' ' << (double)outlen ;

    double_t p1 = start;
    for (qint32 i = 0; i < outlen; i++) {
        qint32 index = (qint32)p1;
        if (index < 1) index = 1;

        outbuf[i] = clamp(cubicInterpolate(&videoBuffer[index - 1], p1 - index), 0, 65535);

        p1 += perpel;
    }
}

// Function returns true if v is within the range of l to h
inline bool TbcPal::inRange(double_t v, double_t l, double_t h)
{
    return ((v >= l) && (v <= h));
}

// Function returns true if v is within the range of l to h
// Note: l and h are scaled according to the video input frequency in FSC
inline bool TbcPal::inRangeF(double_t v, double_t l, double_t h)
{
    l *= videoInputFrequencyInFsc;
    h *= videoInputFrequencyInFsc;
    return ((v >= l) && (v <= h));
}

// Function to detect the pilot signal within a line of video
// Could do with a description of how it works?
bool TbcPal::pilotDetect(double_t *line, double_t loc, double_t &plevel, double_t &pphase)
{
    qint32 len = (12 * videoInputFrequencyInFsc);
    qint32 count = 0;
    double_t ptot = 0;
    double_t tpeak = 0;
    double_t phase = 0;
    loc *= 4;

    double_t lowmin = 5000; // Why 5000?
    double_t lowmax = 13000; // Why 13000?

    for (qint32 i = 28 + loc; i < len + loc; i++) {
        if ((line[i] > lowmin) && (line[i] < lowmax) && (line[i] < line[i - 1]) && (line[i] < line[i + 1])) {
            double_t c = round(((i + peakdetect_quad(&line[i - 1])) / 4)) * 4;

            phase = (i + peakdetect_quad(&line[i - 1])) - c;
            ptot += phase;

            tpeak += line[i];
            count++;
        }
    }

    plevel = ((tpeak / count) /*- (tmin / cmin)*/) / 2.25;
    pphase = (ptot / count) * 1;

    return (count >= 2);
}

// Function to detect the burst signal in a line of video
// Could do with a description of how it works?
bool TbcPal::burstDetect(double_t *line, qint32 start, qint32 end, double_t &plevel, double_t &pphase)
{
    qint32 count = 0, cmin = 0;
    double_t ptot = 0, tpeak = 0, tmin = 0;

    double_t phase = 0;

    double_t highmin = 35500; // Why 35500?
    double_t highmax = 39000; // Why 39000?

    for (qint32 i = start; i < end; i++) {
        if ((line[i] > highmin) && (line[i] < highmax) && (line[i] > line[i - 1]) && (line[i] > line[i + 1])) {
            double_t c = round(((i + peakdetect_quad(&line[i - 1])) / 4) ) * 4;

            phase = (i + peakdetect_quad(&line[i - 1])) - c;
            ptot += phase;
            tpeak += line[i];
            count++;
        }
        else if ((line[i] < line[i - 1]) && (line[i] < line[i + 1])) {
            cmin++;
            tmin += line[i];
        }
    }

    plevel = (tpeak / count) / 4.2; // ?
    pphase = (ptot / count) * 1;

    return (count >= 3);
}

// No idea what this function is for
inline qint32 TbcPal::get_oline(double_t line)
{
    qint32 l = (qint32)line;
    qint32 rv = -1;

    if (l < 11) rv = -1;
    else if (l < 314) rv = ((l - 10) * 2) + 0;
    else if (l < 320) rv = -1;
    else if (l < 625) rv = ((l - 318) * 2) + 1;

    if (rv > 609) rv = -1;

    return rv;
}

// This function checks if the value P (in an array) is higher
// than it's surrounding elements.
//
// To-do:
// Doesn't know the extents of the array it's checking so the pointers
// could easily be invalid and cause an exception...
inline bool TbcPal::isPeak(double_t *p, qint32 i)
{
    return (p[i] >= p[i - 1]) && (p[i] >= p[i + 1]);
}

// Configuration parameter handling functions -----------------------------------------

// Set f_diff
void TbcPal::setShowDifferenceBetweenPixels(bool setting)
{
    // Doesn't appear to do anything useful...  Should this be removed?
    f_diff = setting;
}

// Set writeonfield
void TbcPal::setMagneticVideoMode(bool setting)
{
    if (setting) qInfo() << "Magnetic video mode is selected";
    if (setting) writeOnField = 1;
    else writeOnField = 2; // VERIFY!!!!!!
}

// Set f_flip
void TbcPal::setFlipFields(bool setting)
{
    if (setting) qInfo() << "Flip fields is selected";
    f_flip = setting;
}

// Set audio_only
void TbcPal::setAudioOnly(bool setting)
{
    if (setting) qInfo() << "Audio only is selected";
    audio_only = setting;
}

// Toggle do_autoset
void TbcPal::setPerformAutoSet(bool setting)
{
    if (setting) qInfo() << "Audio ranging is selected";
    if (setting) performAutoRanging = !performAutoRanging;
}

// Set despackle
void TbcPal::setPerformDespackle(bool setting)
{
    if (setting) qInfo() << "Despackle is selected";
    despackle = setting; // Seems to be always forced to false?
}

// Set freeze_frame
void TbcPal::setPerformFreezeFrame(bool setting)
{
    if (setting) qInfo() << "Perform freeze frame is selected";
    freeze_frame = setting;
}

// Set seven_five
void TbcPal::setPerformSevenFive(bool setting)
{
    if (setting) qInfo() << "Perform seven-five is selected";
    seven_five = setting;
}

// Toggle f_highburst
void TbcPal::setPerformHighBurst(bool setting)
{
    if (setting) qInfo() << "Perform high-burst is selected";
    if (setting) f_highburst = !f_highburst;
}

// Set the source video file's file name
void TbcPal::setSourceVideoFile(QString stringValue)
{
    sourceVideoFileName = stringValue;
}

// Set the source audio file's file name
void TbcPal::setSourceAudioFile(QString stringValue)
{
    sourceAudioFileName = stringValue;
}

// Set the target video file's file name
void TbcPal::setTargetVideoFile(QString stringValue)
{
    targetVideoFileName = stringValue;
}

// Set f_tol
void TbcPal::setTol(double_t value)
{
    f_tol = value;
}

// Set p_rotdetect
void TbcPal::setRot(double_t value)
{
    p_rotdetect = value;
}

// Set skip frames
void TbcPal::setSkipFrames(qint32 value)
{
    qInfo() << "setSkipFrames is not supported by the PAL TBC" << value;
    //p_skipframes = value;
}

// Set maximum frames
void TbcPal::setMaximumFrames(qint32 value)
{
    qInfo() << "setMaximumFrames is not supported by the PAL TBC" << value;
    //p_maxframes = value;
}
