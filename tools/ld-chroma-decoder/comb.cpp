/************************************************************************

    comb.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns
    Copyright (C) 2020 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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

#include "comb.h"

#include "deemp.h"

#include <QScopedPointer>

// Definitions of static constexpr data members, for compatibility with
// pre-C++17 compilers
constexpr qint32 Comb::MAX_WIDTH;
constexpr qint32 Comb::MAX_HEIGHT;

// Public methods -----------------------------------------------------------------------------------------------------

Comb::Comb()
    : configurationSet(false)
{
}

qint32 Comb::Configuration::getLookBehind() const {
    if (use3D) {
        // In 3D mode, we need to see the previous frame
        return 1;
    }

    return 0;
}

qint32 Comb::Configuration::getLookAhead() const {
    return 0;
}

// Return the current configuration
const Comb::Configuration &Comb::getConfiguration() const {
    return configuration;
}

// Set the comb filter configuration parameters
void Comb::updateConfiguration(const LdDecodeMetaData::VideoParameters &_videoParameters, const Comb::Configuration &_configuration)
{
    // Copy the configuration parameters
    videoParameters = _videoParameters;
    configuration = _configuration;

    // Range check the frame dimensions
    if (videoParameters.fieldWidth > MAX_WIDTH) qCritical() << "Comb::Comb(): Frame width exceeds allowed maximum!";
    if (((videoParameters.fieldHeight * 2) - 1) > MAX_HEIGHT) qCritical() << "Comb::Comb(): Frame height exceeds allowed maximum!";

    // Range check the video start
    if (videoParameters.activeVideoStart < 16) qCritical() << "Comb::Comb(): activeVideoStart must be > 16!";

    configurationSet = true;
}

void Comb::decodeFrames(const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                        QVector<RGBFrame> &outputFrames)
{
    assert(configurationSet);
    assert((outputFrames.size() * 2) == (endIndex - startIndex));

    // Buffers for the current and previous frame.
    // Because we only need two of these, we allocate them upfront then rotate
    // the pointers below.
    QScopedPointer<FrameBuffer> currentFrameBuffer, previousFrameBuffer;
    currentFrameBuffer.reset(new FrameBuffer(videoParameters, configuration));
    previousFrameBuffer.reset(new FrameBuffer(videoParameters, configuration));

    // Decode each pair of fields into a frame
    for (qint32 fieldIndex = 0; fieldIndex < endIndex; fieldIndex += 2) {
        const qint32 frameIndex = (fieldIndex - startIndex) / 2;

        // Rotate the buffers
        previousFrameBuffer.swap(currentFrameBuffer);

        // Load fields into the buffer
        currentFrameBuffer->loadFields(inputFields[fieldIndex], inputFields[fieldIndex + 1]);

        if (fieldIndex < startIndex) {
            // This is a look-behind frame; no further decoding needed.
            continue;
        }

        // Extract chroma using 1D filter
        currentFrameBuffer->split1D();

        // Extract chroma using 2D filter
        currentFrameBuffer->split2D();

        if (configuration.use3D) {
            // 3D comb filter processing

#if 1
            // XXX - At present we don't have an implementation of motion detection,
            // which makes this a non-adaptive 3D decoder: it'll give good results
            // for still images but garbage for moving images.
#else
            // With motion detection, it would look like this...

            // Demodulate chroma giving I/Q
            currentFrameBuffer->splitIQ();

            // Extract Y from baseband and I/Q
            currentFrameBuffer->adjustY();

            // Post-filter I/Q
            if (configuration.colorlpf) currentFrameBuffer->filterIQ();

            // Apply noise reduction
            currentFrameBuffer->doYNR();
            currentFrameBuffer->doCNR();

            opticalFlow.denseOpticalFlow(currentFrameBuffer->yiqBuffer, currentFrameBuffer->kValues);
#endif

            // Extract chroma using 3D filter
            currentFrameBuffer->split3D(*previousFrameBuffer);
        }

        // Demodulate chroma giving I/Q
        currentFrameBuffer->splitIQ();

        // Extract Y from baseband and I/Q
        currentFrameBuffer->adjustY();

        // Post-filter I/Q
        if (configuration.colorlpf) currentFrameBuffer->filterIQ();

        // Apply noise reduction
        currentFrameBuffer->doYNR();
        currentFrameBuffer->doCNR();

        // Convert the YIQ result to RGB
        outputFrames[frameIndex] = currentFrameBuffer->yiqToRgbFrame();

        // Overlay the optical flow map if required
        if (configuration.showOpticalFlowMap) currentFrameBuffer->overlayOpticalFlowMap(outputFrames[frameIndex]);
    }
}

// Private methods ----------------------------------------------------------------------------------------------------

Comb::FrameBuffer::FrameBuffer(const LdDecodeMetaData::VideoParameters &videoParameters_,
                               const Configuration &configuration_)
    : videoParameters(videoParameters_), configuration(configuration_)
{
    // Set the frame height
    frameHeight = ((videoParameters.fieldHeight * 2) - 1);

    // Set the IRE scale
    irescale = (videoParameters.white16bIre - videoParameters.black16bIre) / 100;

    // Allocate kValues and fill with 0 (no motion detected yet)
    kValues.resize(MAX_WIDTH * MAX_HEIGHT);
    kValues.fill(0.0);
}

/* 
 * The color burst frequency is 227.5 cycles per line, so it flips 180 degrees for each line.
 * 
 * The color burst *signal* is at 180 degrees, which is a greenish yellow.
 *
 * When SCH phase is 0 (properly aligned) the color burst is in phase with the leading edge of the HSYNC pulse.
 *
 * Per RS-170 note 6, Fields 1 and 4 have positive/rising burst phase at that point on even (1-based!) lines.
 * The color burst signal should begin exactly 19 cycles later.
 *
 * getLinePhase returns true if the color burst is rising at the leading edge.
 */

inline qint32 Comb::FrameBuffer::getFieldID(qint32 lineNumber) const
{
    bool isFirstField = ((lineNumber % 2) == 0);
    
    return isFirstField ? firstFieldPhaseID : secondFieldPhaseID;
}

// NOTE:  lineNumber is presumed to be starting at 1.  (This lines up with how splitIQ calls it)
inline bool Comb::FrameBuffer::getLinePhase(qint32 lineNumber) const
{
    qint32 fieldID = getFieldID(lineNumber);
    bool isPositivePhaseOnEvenLines = (fieldID == 1) || (fieldID == 4);    

    int fieldLine = (lineNumber / 2);
    bool isEvenLine = (fieldLine % 2) == 0;
    
    return isEvenLine ? isPositivePhaseOnEvenLines : !isPositivePhaseOnEvenLines;
}

// Interlace two source fields into the framebuffer.
void Comb::FrameBuffer::loadFields(const SourceField &firstField, const SourceField &secondField)
{
    // Interlace the input fields and place in the frame buffer
    qint32 fieldLine = 0;
    rawbuffer.clear();
    for (qint32 frameLine = 0; frameLine < frameHeight; frameLine += 2) {
        rawbuffer.append(firstField.data.mid(fieldLine * videoParameters.fieldWidth, videoParameters.fieldWidth));
        rawbuffer.append(secondField.data.mid(fieldLine * videoParameters.fieldWidth, videoParameters.fieldWidth));
        fieldLine++;
    }

    // Set the phase IDs for the frame
    firstFieldPhaseID = firstField.field.fieldPhaseID;
    secondFieldPhaseID = secondField.field.fieldPhaseID;
}

// Extract chroma into clpbuffer[0] using a 1D bandpass filter.
//
// The filter is [-0.25, 0, 0.5, 0, -0.25], a gentle bandpass centred on fSC.
// So the output will contain all of the chroma signal, but also whatever luma
// components ended up in the same frequency range.
//
// This also acts as an alias removal pre-filter for the quadrature detector in
// splitIQ, so we use its result for split2D rather than the raw signal.
void Comb::FrameBuffer::split1D()
{
    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        // Get a pointer to the line's data
        const quint16 *line = rawbuffer.data() + (lineNumber * videoParameters.fieldWidth);

        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            double tc1 = (line[h] - ((line[h - 2] + line[h + 2]) / 2.0)) / 2.0;

            // Record the 1D C value
            clpbuffer[0].pixel[lineNumber][h] = tc1;
        }
    }
}

// Extract chroma into clpbuffer[1] using a 2D 3-line adaptive filter.
//
// Because the phase of the chroma signal changes by 180 degrees from line to
// line, subtracting two adjacent lines that contain the same information will
// give you just the chroma signal. But real images don't necessarily contain
// the same information on every line.
//
// The "3-line adaptive" part means that we look at both surrounding lines to
// estimate how similar they are to this one. We can then compute the 2D chroma
// value as a blend of the two differences, weighted by similarity.
void Comb::FrameBuffer::split2D()
{
    // Dummy black line
    static constexpr double blackLine[MAX_WIDTH] = {0};

    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        // Get pointers to the surrounding lines of 1D chroma.
        // If a line we need is outside the active area, use blackLine instead.
        const double *previousLine = blackLine;
        if (lineNumber - 2 >= videoParameters.firstActiveFrameLine) {
            previousLine = clpbuffer[0].pixel[lineNumber - 2];
        }
        const double *currentLine = clpbuffer[0].pixel[lineNumber];
        const double *nextLine = blackLine;
        if (lineNumber + 2 < videoParameters.lastActiveFrameLine) {
            nextLine = clpbuffer[0].pixel[lineNumber + 2];
        }

        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            double kp, kn;

            // Summing the differences of the *absolute* values of the 1D chroma samples
            // will give us a low value if the two lines are nearly in phase (strong Y)
            // or nearly 180 degrees out of phase (strong C) -- i.e. the two cases where
            // the 2D filter is probably usable. Also give a small bonus if
            // there's a large signal (we think).
            kp  = fabs(fabs(currentLine[h]) - fabs(previousLine[h]));
            kp += fabs(fabs(currentLine[h - 1]) - fabs(previousLine[h - 1]));
            kp -= (fabs(currentLine[h]) + fabs(previousLine[h - 1])) * .10;
            kn  = fabs(fabs(currentLine[h]) - fabs(nextLine[h]));
            kn += fabs(fabs(currentLine[h - 1]) - fabs(nextLine[h - 1]));
            kn -= (fabs(currentLine[h]) + fabs(nextLine[h - 1])) * .10;

            // Map the difference into a weighting 0-1.
            // 1 means in phase or unknown; 0 means out of phase (more than kRange difference).
            const double kRange = 45 * irescale;
            kp = qBound(0.0, 1 - (kp / kRange), 1.0);
            kn = qBound(0.0, 1 - (kn / kRange), 1.0);

            double sc = 1.0;

            if ((kn > 0) || (kp > 0)) {
                // At least one of the next/previous lines has a good phase relationship.

                // If one of them is much better than the other, only use that one
                if (kn > (3 * kp)) kp = 0;
                else if (kp > (3 * kn)) kn = 0;

                sc = (2.0 / (kn + kp));
                if (sc < 1.0) sc = 1.0;
            } else {
                // Neither line has a good phase relationship.

                // But are they similar to each other? If so, we can use both of them!
                if ((fabs(fabs(previousLine[h]) - fabs(nextLine[h])) - fabs((nextLine[h] + previousLine[h]) * .2)) <= 0) {
                    kn = kp = 1;
                }

                // Else kn = kp = 0, so we won't extract any chroma for this sample.
                // (Some NTSC decoders fall back to the 1D chroma in this situation.)
            }

            // Compute the weighted sum of differences, giving the 2D chroma value
            double tc1;
            tc1  = ((currentLine[h] - previousLine[h]) * kp * sc);
            tc1 += ((currentLine[h] - nextLine[h]) * kn * sc);
            tc1 /= 4;

            clpbuffer[1].pixel[lineNumber][h] = tc1;
        }
    }
}

// Extract chroma into clpbuffer[2] using a 3D filter.
//
// This is like the 2D filtering above, except now we're looking at the
// same sample in the previous *frame* -- and since there are an odd number of
// lines in an NTSC frame, the subcarrier phase is also 180 degrees different
// from the current sample. So if the previous frame carried the same
// information in this sample, subtracting the two samples will give us just
// the chroma again.
//
// And as with 2D filtering, real video can have differences between frames, so
// we need to make an adaptive choice whether to use this or drop back to the
// 2D result (which is done in splitIQ below).
void Comb::FrameBuffer::split3D(const FrameBuffer &previousFrame)
{
    if (previousFrame.rawbuffer.size() == 0) {
        // There was no previous frame data (i.e. this is the first frame). Return all 0s.

        for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
            for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
                clpbuffer[2].pixel[lineNumber][h] = 0;
            }
        }

        return;
    }

    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        const quint16 *currentLine = rawbuffer.data() + (lineNumber * videoParameters.fieldWidth);
        const quint16 *previousLine = previousFrame.rawbuffer.data() + (lineNumber * videoParameters.fieldWidth);

        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            clpbuffer[2].pixel[lineNumber][h] = (previousLine[h] - currentLine[h]) / 2;
        }
    }
}

// Spilt the I and Q
void Comb::FrameBuffer::splitIQ()
{
    // Clear the target frame YIQ buffer
    yiqBuffer.clear();

    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        // Get a pointer to the line's data
        const quint16 *line = rawbuffer.data() + (lineNumber * videoParameters.fieldWidth);
        bool linePhase = getLinePhase(lineNumber);

        double si = 0, sq = 0;
        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            qint32 phase = h % 4;

            // Take the 2D C
            double cavg = clpbuffer[1].pixel[lineNumber][h]; // 2D C average

            if (configuration.use3D && kValues.size() != 0) {
                // 3D mode -- compute a weighted sum of the 2D and 3D chroma values

                // The motionK map returns K (0 for stationary pixels to 1 for moving pixels)
                cavg  = clpbuffer[1].pixel[lineNumber][h] * kValues[(lineNumber * MAX_WIDTH) + h]; // 2D mix
                cavg += clpbuffer[2].pixel[lineNumber][h] * (1 - kValues[(lineNumber * MAX_WIDTH) + h]); // 3D mix

                // Use only 3D (for testing!)
                //cavg = clpbuffer[2].pixel[lineNumber][h];
            }

            if (linePhase) cavg = -cavg;

            switch (phase) {
                case 0: sq = cavg; break;
                case 1: si = -cavg; break;
                case 2: sq = -cavg; break;
                case 3: si = cavg; break;
                default: break;
            }

            yiqBuffer[lineNumber][h].y = line[h];
            yiqBuffer[lineNumber][h].i = si;
            yiqBuffer[lineNumber][h].q = sq;
        }
    }
}

// Filter the IQ from the input YIQ buffer
void Comb::FrameBuffer::filterIQ()
{
    auto iFilter(f_colorlpi);
    auto qFilter(configuration.colorlpf_hq ? f_colorlpi : f_colorlpq);

    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        iFilter.clear();
        qFilter.clear();

        qint32 qoffset = configuration.colorlpf_hq ? f_colorlpi_offset : f_colorlpq_offset;

        double filti = 0, filtq = 0;

        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            qint32 phase = h % 4;

            switch (phase) {
                case 0: filti = iFilter.feed(yiqBuffer[lineNumber][h].i); break;
                case 1: filtq = qFilter.feed(yiqBuffer[lineNumber][h].q); break;
                case 2: filti = iFilter.feed(yiqBuffer[lineNumber][h].i); break;
                case 3: filtq = qFilter.feed(yiqBuffer[lineNumber][h].q); break;
                default: break;
            }

            yiqBuffer[lineNumber][h - qoffset].i = filti;
            yiqBuffer[lineNumber][h - qoffset].q = filtq;
        }
    }
}

// Remove the colour data from the baseband (Y)
void Comb::FrameBuffer::adjustY()
{
    // remove color data from baseband (Y)
    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        bool linePhase = getLinePhase(lineNumber);

        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            double comp = 0;
            qint32 phase = h % 4;

            YIQ y = yiqBuffer[lineNumber][h];

            switch (phase) {
                case 0: comp = -y.q; break;
                case 1: comp = y.i; break;
                case 2: comp = y.q; break;
                case 3: comp = -y.i; break;
                default: break;
            }

            if (!linePhase) comp = -comp;
            y.y -= comp;

            yiqBuffer[lineNumber][h] = y;
        }
    }
}

/*
 * This applies an FIR coring filter to both I and Q color channels.  It's a simple (crude?) NR technique used
 * by LD players, but effective especially on the Y/luma channel.
 *
 * A coring filter removes high frequency components (.4mhz chroma, 2.8mhz luma) of a signal up to a certain point,
 * which removes small high frequency noise.
 */

void Comb::FrameBuffer::doCNR()
{
    if (configuration.cNRLevel == 0) return;

    // High-pass filters for I/Q
    auto iFilter(f_nrc);
    auto qFilter(f_nrc);

    // nr_c is the coring level
    double nr_c = configuration.cNRLevel * irescale;

    QVector<YIQ> hplinef;
    hplinef.resize(videoParameters.fieldWidth + 32);

    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        // Filters not cleared from previous line

        for (qint32 h = videoParameters.activeVideoStart; h <= videoParameters.activeVideoEnd; h++) {
            hplinef[h].i = iFilter.feed(yiqBuffer[lineNumber][h].i);
            hplinef[h].q = qFilter.feed(yiqBuffer[lineNumber][h].q);
        }

        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            // Offset by 12 to cover the filter delay
            double ai = hplinef[h + 12].i;
            double aq = hplinef[h + 12].q;

            if (fabs(ai) > nr_c) {
                ai = (ai > 0) ? nr_c : -nr_c;
            }

            if (fabs(aq) > nr_c) {
                aq = (aq > 0) ? nr_c : -nr_c;
            }

            yiqBuffer[lineNumber][h].i -= ai;
            yiqBuffer[lineNumber][h].q -= aq;
        }
    }
}

void Comb::FrameBuffer::doYNR()
{
    if (configuration.yNRLevel == 0) return;

    // High-pass filter for Y
    auto yFilter(f_nr);

    // nr_y is the coring level
    double nr_y = configuration.yNRLevel * irescale;

    QVector<YIQ> hplinef;
    hplinef.resize(videoParameters.fieldWidth + 32);

    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        // Filter not cleared from previous line

        for (qint32 h = videoParameters.activeVideoStart; h <= videoParameters.activeVideoEnd; h++) {
            hplinef[h].y = yFilter.feed(yiqBuffer[lineNumber][h].y);
        }

        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            double a = hplinef[h + 12].y;

            if (fabs(a) > nr_y) {
                a = (a > 0) ? nr_y : -nr_y;
            }

            yiqBuffer[lineNumber][h].y -= a;
        }
    }
}

// Convert buffer from YIQ to RGB 16-16-16
RGBFrame Comb::FrameBuffer::yiqToRgbFrame()
{
    RGBFrame rgbOutputFrame;
    rgbOutputFrame.resize(videoParameters.fieldWidth * frameHeight * 3); // for RGB 16-16-16

    // Initialise the output frame
    rgbOutputFrame.fill(0);

    // Initialise YIQ to RGB converter
    RGB rgb(videoParameters.white16bIre, videoParameters.black16bIre, configuration.whitePoint75, configuration.chromaGain);

    // Perform YIQ to RGB conversion
    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        // Get a pointer to the line
        quint16 *linePointer = rgbOutputFrame.data() + (videoParameters.fieldWidth * 3 * lineNumber);

        // Offset the output by the activeVideoStart to keep the output frame
        // in the same x position as the input video frame
        qint32 o = (videoParameters.activeVideoStart * 3);

        // Fill the output line with the RGB values
        rgb.convertLine(&yiqBuffer[lineNumber][videoParameters.activeVideoStart],
                        &yiqBuffer[lineNumber][videoParameters.activeVideoEnd],
                        &linePointer[o]);
    }

    // Return the RGB frame data
    return rgbOutputFrame;
}

// Convert buffer from YIQ to RGB
void Comb::FrameBuffer::overlayOpticalFlowMap(RGBFrame &rgbFrame)
{
    qDebug() << "Comb::FrameBuffer::overlayOpticalFlowMap(): Overlaying optical flow map onto RGB output";

    // Overlay the optical flow map on the output RGB
    for (qint32 lineNumber = videoParameters.firstActiveFrameLine; lineNumber < videoParameters.lastActiveFrameLine; lineNumber++) {
        // Get a pointer to the line
        quint16 *linePointer = rgbFrame.data() + (videoParameters.fieldWidth * 3 * lineNumber);

        // Fill the output frame with the RGB values
        for (qint32 h = videoParameters.activeVideoStart; h < videoParameters.activeVideoEnd; h++) {
            qint32 intensity = static_cast<qint32>(kValues[(lineNumber * MAX_WIDTH) + h] * 65535);
            // Make the RGB more purple to show where motion was detected
            qint32 red = linePointer[(h * 3)] + intensity;
            qint32 green = linePointer[(h * 3) + 1];
            qint32 blue = linePointer[(h * 3) + 2] + intensity;

            if (red > 65535) red = 65535;
            if (green > 65535) green = 65535;
            if (blue > 65535) blue = 65535;

            linePointer[(h * 3)] = static_cast<quint16>(red);
            linePointer[(h * 3) + 1] = static_cast<quint16>(green);
            linePointer[(h * 3) + 2] = static_cast<quint16>(blue);
        }
    }
}
