/************************************************************************

    dec_audiocorrection.cpp

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

#include "dec_audiocorrection.h"

AudioCorrection::AudioCorrection() :
    m_silencedSamplesCount(0),
    m_validSamplesCount(0),
    m_concealedSamplesCount(0),
    m_firstSectionFlag(true)
{}

void AudioCorrection::pushSection(const AudioSection &audioSection)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(audioSection);

    // Process the queue
    processQueue();
}

AudioSection AudioCorrection::popSection()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

bool AudioCorrection::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

void AudioCorrection::processQueue()
{
    // TODO: this will never correct the very first and last sections

    // Pop a section from the input buffer
    m_correctionBuffer.append(m_inputBuffer.dequeue());

    // Perform correction on the section in the middle of the correction buffer
    if (m_correctionBuffer.size() == 3) {
        AudioSection correctedSection;

        // Process all 98 frames in the section
        for (int subSection = 0; subSection < 98; ++subSection) {
            Audio correctedFrame;

            // Get the preceding, correcting and following frames
            Audio precedingFrame, correctingFrame, followingFrame;
            if (subSection == 0) {
                // If this is the first frame, use the first frame in the section as the preceding frame
                precedingFrame = m_correctionBuffer.at(0).frame(97);
            } else {
                precedingFrame = m_correctionBuffer.at(1).frame(subSection - 1);
            }

            correctingFrame = m_correctionBuffer.at(1).frame(subSection);

            if (correctingFrame.countErrors() == 0) {
                // No errors in this frame - just copy it
                correctedSection.pushFrame(correctingFrame);
                continue;
            }

            if (subSection == 97) {
                // If this is the last frame, use the last frame in the section as the following frame
                followingFrame = m_correctionBuffer.at(2).frame(0);
            } else {
                followingFrame = m_correctionBuffer.at(1).frame(subSection + 1);
            }

            // Sample correction
            QVector<qint16> correctedLeftSamples;
            QVector<bool> correctedLeftErrorSamples;
            QVector<bool> correctedLeftPaddedSamples;
            QVector<qint16> correctedRightSamples;
            QVector<bool> correctedRightErrorSamples;
            QVector<bool> correctedRightPaddedSamples;

            for (int sampleOffset = 0; sampleOffset < 6; ++sampleOffset) {
                // Left channel
                // Get the preceding, correcting and following left samples
                qint16 precedingLeftSample, correctingLeftSample, followingLeftSample;
                qint16 precedingLeftSampleError, correctingLeftSampleError, followingLeftSampleError;

                if (sampleOffset == 0) {
                    precedingLeftSample = precedingFrame.dataLeft().at(5);
                    precedingLeftSampleError = precedingFrame.errorDataLeft().at(5);
                } else {
                    precedingLeftSample = correctingFrame.dataLeft().at(sampleOffset - 1);
                    precedingLeftSampleError = correctingFrame.errorDataLeft().at(sampleOffset - 1);
                }

                correctingLeftSample = correctingFrame.dataLeft().at(sampleOffset);
                correctingLeftSampleError = correctingFrame.errorDataLeft().at(sampleOffset);

                if (sampleOffset == 5) {
                    followingLeftSample = followingFrame.dataLeft().at(0);
                    followingLeftSampleError = followingFrame.errorDataLeft().at(0);
                } else {
                    followingLeftSample = correctingFrame.dataLeft().at(sampleOffset + 1);
                    followingLeftSampleError = correctingFrame.errorDataLeft().at(sampleOffset + 1);
                }

                if (correctingLeftSampleError != 0) {
                    // Do we have a valid preceding and following sample?
                    if (precedingLeftSampleError || followingLeftSampleError) {
                        // Silence the sample
                        qDebug().noquote().nospace() << "AudioCorrection::processQueue() -  Left  Silencing: "
                            << "Section address " << m_correctionBuffer.at(1).metadata.absoluteSectionTime().toString()
                            << " - Frame " << subSection << ", sample " << sampleOffset;
                        correctedLeftSamples.append(0);
                        correctedLeftErrorSamples.append(true);
                        correctedLeftPaddedSamples.append(false);
                        ++m_silencedSamplesCount;
                    } else {
                        // Conceal the sample
                        qDebug().noquote().nospace() << "AudioCorrection::processQueue() -  Left Concealing: "
                            << "Section address " << m_correctionBuffer.at(1).metadata.absoluteSectionTime().toString()
                            << " - Frame " << subSection << ", sample " << sampleOffset
                            << " - Preceding = " << precedingLeftSample << ", Following = " << followingLeftSample
                            << ", Average = " << (precedingLeftSample + followingLeftSample) / 2;
                        correctedLeftSamples.append((precedingLeftSample + followingLeftSample) / 2);
                        correctedLeftErrorSamples.append(false);
                        correctedLeftPaddedSamples.append(true);
                        ++m_concealedSamplesCount;
                    }
                } else {
                    // The sample is valid - just copy it
                    correctedLeftSamples.append(correctingLeftSample);
                    correctedLeftErrorSamples.append(false);
                    correctedLeftPaddedSamples.append(false);
                    ++m_validSamplesCount;
                }

                // Right channel
                // Get the preceding, correcting and following right samples
                qint16 precedingRightSample, correctingRightSample, followingRightSample;
                qint16 precedingRightSampleError, correctingRightSampleError, followingRightSampleError;

                if (sampleOffset == 0) {
                    precedingRightSample = precedingFrame.dataRight().at(5);
                    precedingRightSampleError = precedingFrame.errorDataRight().at(5);
                } else {
                    precedingRightSample = correctingFrame.dataRight().at(sampleOffset - 1);
                    precedingRightSampleError = correctingFrame.errorDataRight().at(sampleOffset - 1);
                }

                correctingRightSample = correctingFrame.dataRight().at(sampleOffset);
                correctingRightSampleError = correctingFrame.errorDataRight().at(sampleOffset);

                if (sampleOffset == 5) {
                    followingRightSample = followingFrame.dataRight().at(0);
                    followingRightSampleError = followingFrame.errorDataRight().at(0);
                } else {
                    followingRightSample = correctingFrame.dataRight().at(sampleOffset + 1);
                    followingRightSampleError = correctingFrame.errorDataRight().at(sampleOffset + 1);
                }

                if (correctingRightSampleError != 0) {
                    // Do we have a valid preceding and following sample?
                    if (precedingRightSampleError || followingRightSampleError) {
                        // Silence the sample
                        qDebug().noquote().nospace() << "AudioCorrection::processQueue() - Right  Silencing: "
                            << "Section address " << m_correctionBuffer.at(1).metadata.absoluteSectionTime().toString()
                            << " - Frame " << subSection << ", sample " << sampleOffset;
                        correctedRightSamples.append(0);
                        correctedRightErrorSamples.append(true);
                        correctedRightPaddedSamples.append(false);
                        ++m_silencedSamplesCount;
                    } else {
                        // Conceal the sample
                        qDebug().noquote().nospace() << "AudioCorrection::processQueue() - Right Concealing: "
                            << "Section address " << m_correctionBuffer.at(1).metadata.absoluteSectionTime().toString()
                            << " - Frame " << subSection << ", sample " << sampleOffset
                            << " - Preceding = " << precedingRightSample << ", Following = " << followingRightSample
                            << ", Average = " << (precedingRightSample + followingRightSample) / 2;
                        correctedRightSamples.append((precedingRightSample + followingRightSample) / 2);
                        correctedRightErrorSamples.append(false);
                        correctedRightPaddedSamples.append(true);
                        ++m_concealedSamplesCount;
                    }
                } else {
                    // The sample is valid - just copy it
                    correctedRightSamples.append(correctingRightSample);
                    correctedRightErrorSamples.append(false);
                    correctedRightPaddedSamples.append(false);
                    ++m_validSamplesCount;
                }
            }

            // Combine the left and right channel data (and error data)
            QVector<qint16> correctedSamples;
            QVector<bool> correctedErrorSamples;
            QVector<bool> correctedPaddedSamples;

            for (int i = 0; i < 6; ++i) {
                correctedSamples.append(correctedLeftSamples.at(i));
                correctedSamples.append(correctedRightSamples.at(i));
                correctedErrorSamples.append(correctedLeftErrorSamples.at(i));
                correctedErrorSamples.append(correctedRightErrorSamples.at(i));
                correctedPaddedSamples.append(correctedLeftPaddedSamples.at(i));
                correctedPaddedSamples.append(correctedRightPaddedSamples.at(i));
            }

            // Write the channel data back to the correction buffer's frame
            correctedFrame.setData(correctedSamples);
            correctedFrame.setErrorData(correctedErrorSamples);
            correctedFrame.setConcealedData(correctedPaddedSamples);

            correctedSection.pushFrame(correctedFrame);
        }

        correctedSection.metadata = m_correctionBuffer.at(1).metadata;
        m_correctionBuffer[1] = correctedSection;

        // Write the first section in the correction buffer to the output buffer
        m_outputBuffer.enqueue(m_correctionBuffer.at(0));
        m_correctionBuffer.removeFirst();
    }
}

void AudioCorrection::showStatistics()
{
    qInfo().nospace() << "Audio correction statistics:";
    qInfo().nospace() << "  Total mono samples: "
                      << m_validSamplesCount + m_concealedSamplesCount + m_silencedSamplesCount;
    qInfo().nospace() << "  Valid mono samples: " << m_validSamplesCount;
    qInfo().nospace() << "  Concealed mono samples: " << m_concealedSamplesCount;
    qInfo().nospace() << "  Silenced mono samples: " << m_silencedSamplesCount;
}