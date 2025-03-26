/************************************************************************

    writer_wav_metadata.cpp

    efm-decoder-audio - EFM Data24 to Audio decoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    This application is free software: you can redistribute it and/or
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

#include "writer_wav_metadata.h"

// This writer class writes metadata about audio data to a file
// This is used when the output is stereo audio data

WriterWavMetadata::WriterWavMetadata() :
    m_inErrorRange(false),
    m_inConcealedRange(false),
    m_haveStartTime(false),
    m_noAudioConcealment(false),
    m_absoluteSectionTime(0, 0, 0),
    m_sectionTime(0, 0, 0),
    m_prevAbsoluteSectionTime(0, 0, 0),
    m_prevSectionTime(0, 0, 0)
{}

WriterWavMetadata::~WriterWavMetadata()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool WriterWavMetadata::open(const QString &filename, bool noAudioConcealment)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::WriteOnly)) {
        qCritical() << "WriterWavMetadata::open() - Could not open file" << filename << "for writing";
        return false;
    }
    qDebug() << "WriterWavMetadata::open() - Opened file" << filename << "for data writing";

    // If we're not concealing audio, we use "error" metadata instead of "silenced"
    m_noAudioConcealment = noAudioConcealment;

    return true;
}

void WriterWavMetadata::write(const AudioSection &audioSection)
{
    if (!m_file.isOpen()) {
        qCritical() << "WriterWavMetadata::write() - File is not open for writing";
        return;
    }

    SectionMetadata metadata = audioSection.metadata;
    m_absoluteSectionTime = metadata.absoluteSectionTime();
    m_sectionTime = metadata.sectionTime();

    // Do we have the start time already?
    if (!m_haveStartTime) {
        m_startTime = m_absoluteSectionTime;
        m_haveStartTime = true;
    }

    // Get the relative time from the start time
    SectionTime relativeSectionTime = m_absoluteSectionTime - m_startTime;

    // Do we have a new track?
    if (!m_trackNumbers.contains(metadata.trackNumber())) {
        // Check that the new track number is greater than the previous track numbers
        if (!m_trackNumbers.isEmpty() && metadata.trackNumber() < m_trackNumbers.last()) {
            qWarning() << "WriterWavMetadata::write() - Track number decreased from" << m_trackNumbers.last() << "to" << metadata.trackNumber() << "- ignoring";
        } else {
            // Append the new track to the statistics
            if (metadata.trackNumber() != 0 && metadata.trackNumber() != 0xAA) {
                m_trackNumbers.append(metadata.trackNumber());
                
                m_trackAbsStartTimes.append(m_absoluteSectionTime);
                m_trackStartTimes.append(m_sectionTime);

                if (m_trackAbsStartTimes.size() == 1) {
                    // This is the first track, so we don't have an end time yet
                } else {
                    // Set the end time of the previous track
                    m_trackAbsEndTimes.append(m_prevAbsoluteSectionTime);
                    m_trackEndTimes.append(m_prevSectionTime);
                }
            }
    
            qDebug() << "WriterWavMetadata::write() - New track" << metadata.trackNumber()
                << "detected with disc start time" << m_absoluteSectionTime.toString() << "and track start time" << m_sectionTime.toString();
        }
    }

    // Output metadata about errors
    for (int subSection = 0; subSection < 98; ++subSection) {
        Audio audio = audioSection.frame(subSection);
        QVector<qint16> audioData = audio.data();
        QVector<bool> errors = audio.errorData();
        QVector<bool> concealed = audio.concealedData();
        
        for (int sampleOffset = 0; sampleOffset < 12; sampleOffset += 2) {
            // Errors/Silenced
            bool hasError = errors.at(sampleOffset) || errors.at(sampleOffset+1);
            
            if (hasError && !m_inErrorRange) {
                // Start of new error range
                m_errorRangeStart = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                    relativeSectionTime.frameNumber(), subSection, sampleOffset);
                m_inErrorRange = true;
            } else if (!hasError && m_inErrorRange) {
                // End of error range
                QString rangeEnd;
                if (sampleOffset == 0) {
                    // Handle wrap to previous subsection
                    if (subSection > 0) {
                        rangeEnd = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                            relativeSectionTime.frameNumber(), subSection - 1, 11);
                    } else {
                        // If we're at the first subsection, just use the current position
                        rangeEnd = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                            relativeSectionTime.frameNumber(), subSection, sampleOffset);
                    }
                } else {
                    rangeEnd = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                        relativeSectionTime.frameNumber(), subSection, sampleOffset - 1);
                }

                QString sampleTimeStamp = QString("%1").arg(m_absoluteSectionTime.toString());
                QString outputString = m_errorRangeStart + "\t" + rangeEnd + "\tError: " + sampleTimeStamp + "\n";
                if (!m_noAudioConcealment) outputString = m_errorRangeStart + "\t" + rangeEnd + "\tSilenced: " + sampleTimeStamp + "\n";

                m_file.write(outputString.toUtf8());
                m_inErrorRange = false;
            }

            // Concealed
            bool hasConcealed = concealed.at(sampleOffset) || concealed.at(sampleOffset+1);
            
            if (hasConcealed && !m_inConcealedRange) {
                // Start of new error range
                m_concealedRangeStart = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                    relativeSectionTime.frameNumber(), subSection, sampleOffset);
                    m_inConcealedRange = true;
            } else if (!hasConcealed && m_inConcealedRange) {
                // End of error range
                QString rangeEnd;
                if (sampleOffset == 0) {
                    // Handle wrap to previous subsection
                    if (subSection > 0) {
                        rangeEnd = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                            relativeSectionTime.frameNumber(), subSection - 1, 11);
                    } else {
                        // If we're at the first subsection, just use the current position
                        rangeEnd = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                            relativeSectionTime.frameNumber(), subSection, sampleOffset);
                    }
                } else {
                    rangeEnd = convertToAudacityTimestamp(relativeSectionTime.minutes(), relativeSectionTime.seconds(),
                        relativeSectionTime.frameNumber(), subSection, sampleOffset - 1);
                }

                QString sampleTimeStamp = QString("%1").arg(m_absoluteSectionTime.toString());
                QString outputString = m_concealedRangeStart + "\t" + rangeEnd + "\tConcealed: " + sampleTimeStamp + "\n";
                m_file.write(outputString.toUtf8());
                m_inConcealedRange = false;
            }
        }
    }

    if (metadata.trackNumber() != 0 && metadata.trackNumber() != 0xAA) {
        // Update the previous times
        m_prevAbsoluteSectionTime = m_absoluteSectionTime;
        m_prevSectionTime = m_sectionTime;
    }
}

void WriterWavMetadata::flush()
{
    if (!m_file.isOpen()) {
        return;
    }

    // Note: For track 1 the track time metadata might be wrong.  On some discs the first track includes unmarked lead-in.
    // Basically, at absolute disc time of 00:00:00 the track time might be positive (e.g 00:01:74 or 2 seconds) and then
    // it will count down to 00:00:00 - at which point the track starts and time starts counting up again.
    //
    // This isn't handled by the metadata writer, so the first track might have an incorrect track start time (but the
    // absolute time will be correct). 

    // Set the end time of the previous track
    m_trackAbsEndTimes.append(m_prevAbsoluteSectionTime);
    m_trackEndTimes.append(m_prevSectionTime);

    // Only write the metadata if we have more than one track
    if (m_trackNumbers.size() > 1) {
        // Write the track metadata
        for (int i = 0; i < m_trackNumbers.size(); ++i) {
            QString trackAbsStartTime = convertToAudacityTimestamp(m_trackAbsStartTimes[i].minutes(), m_trackAbsStartTimes[i].seconds(),
                m_trackAbsStartTimes[i].frameNumber(), 0, 0);

            QString trackAbsEndTime = convertToAudacityTimestamp(m_trackAbsEndTimes[i].minutes(), m_trackAbsEndTimes[i].seconds(),
                m_trackAbsEndTimes[i].frameNumber(), 0, 0);

            QString trackNumber = QString("%1").arg(m_trackNumbers.at(i), 2, 10, QChar('0'));
            QString trackTime = "[" + m_trackStartTimes[i].toString() + "-" + m_trackEndTimes[i].toString() + "]";

            QString outputString = trackAbsStartTime + "\t" + trackAbsEndTime + "\tTrack: " + trackNumber + " " + trackTime + "\n";
            m_file.write(outputString.toUtf8());

            QString debugString = m_trackAbsStartTimes[i].toString() + " " + m_trackAbsEndTimes[i].toString() + " Track: " + trackNumber + " " + trackTime;
            qDebug() << "WriterWavMetadata::flush(): Wrote track metadata:" << debugString;
        }
    } else {
        qDebug() << "WriterWavMetadata::flush(): Only 1 track present - not writing track metadata";
    }
}

void WriterWavMetadata::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    // Finish writing the metadata
    flush();

    // If we're still in an error range when closing, write the final range
    if (m_inErrorRange) {
        QString outputString = m_errorRangeStart + "\t" + m_errorRangeStart + "\tError: Incomplete range\n";
        m_file.write(outputString.toUtf8());
    }

    m_file.close();
    qDebug() << "WriterWavMetadata::close(): Closed the WAV metadata file" << m_file.fileName();
}

qint64 WriterWavMetadata::size() const
{
    if (m_file.isOpen()) {
        return m_file.size();
    }

    return 0;
}

QString WriterWavMetadata::convertToAudacityTimestamp(qint32 minutes, qint32 seconds, qint32 frames,
    qint32 subsection, qint32 sample)
{
    // Constants for calculations
    constexpr double FRAME_RATE = 75.0;      // 75 frames per second
    constexpr double SUBSECTIONS_PER_FRAME = 98.0; // 98 subsections per frame
    constexpr double SAMPLES_PER_SUBSECTION = 6.0; // 6 stereo samples per subsection

    // Convert minutes and seconds to total seconds
    double total_seconds = (minutes * 60.0) + seconds;
    
    // Convert frames to seconds
    total_seconds += (frames) / FRAME_RATE;
    
    // Convert subsection to fractional time
    total_seconds += subsection / (FRAME_RATE * SUBSECTIONS_PER_FRAME);
    
    // Convert sample to fractional time
    total_seconds += (sample/2) / (FRAME_RATE * SUBSECTIONS_PER_FRAME * SAMPLES_PER_SUBSECTION);

    // Format the output string with 6 decimal places
    return QString::asprintf("%.6f", total_seconds);
}