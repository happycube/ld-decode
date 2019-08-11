/************************************************************************

    comb.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

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

#include "../../deemp.h"

// Public methods -----------------------------------------------------------------------------------------------------

Comb::Comb() {
    // Set default configuration
    configuration.blackAndWhite = false;
    configuration.whitePoint100 = false;

    configuration.colorlpf = true; // Use as default
    configuration.colorlpf_hq = true; // Use as default
    
    configuration.cNRLevel = 0.0;
    configuration.yNRLevel = 1.0;

    // These are the overall dimensions of the input frame
    configuration.fieldWidth = 910;
    configuration.fieldHeight = 263;

    // These are the start and end points for the active video line
    configuration.activeVideoStart = 40;
    configuration.activeVideoEnd = 840;

    // This sets the first active frame line
    configuration.firstActiveLine = 43;

    // Set the 16-bit IRE levels
    configuration.blackIre = 15360;
    configuration.whiteIre = 51200;

    // Set the filter type
    configuration.use3D = false;
    configuration.showOpticalFlowMap = false;

    postConfigurationTasks();
}

// Get the comb filter configuration parameters
Comb::Configuration Comb::getConfiguration()
{
    return configuration;
}

// Set the comb filter configuration parameters
void Comb::setConfiguration(const Comb::Configuration &_configuration)
{
    // Range check the frame dimensions
    if (_configuration.fieldWidth > 910) qCritical() << "Comb::Comb(): Frame width exceeds allowed maximum!";
    if (((_configuration.fieldHeight * 2) - 1) > 525) qCritical() << "Comb::Comb(): Frame height exceeds allowed maximum!";

    // Range check the video start
    if (_configuration.activeVideoStart < 16) qCritical() << "Comb::Comb(): activeVideoStart must be > 16!";

    configuration = _configuration;
    postConfigurationTasks();
}

// Process the input buffer into the RGB output buffer
QByteArray Comb::process(QByteArray firstFieldInputBuffer, QByteArray secondFieldInputBuffer, qreal burstMedianIre,
                         qint32 firstFieldPhaseID, qint32 secondFieldPhaseID)
{
    // Allocate the frame buffer
    FrameBuffer currentFrameBuffer;
    currentFrameBuffer.clpbuffer.resize(3);

    // Allocate the temporary YIQ buffer
    YiqBuffer tempYiqBuffer;

    // Allocate RGB output buffer
    QByteArray rgbOutputBuffer;
    QByteArray bgrBuffer;

    // Interlace the input fields and place in the frame[0]'s raw buffer
    qint32 fieldLine = 0;
    currentFrameBuffer.rawbuffer.clear();
    for (qint32 frameLine = 0; frameLine < frameHeight; frameLine += 2) {
        currentFrameBuffer.rawbuffer.append(firstFieldInputBuffer.mid(fieldLine * configuration.fieldWidth * 2, configuration.fieldWidth * 2));
        currentFrameBuffer.rawbuffer.append(secondFieldInputBuffer.mid(fieldLine * configuration.fieldWidth * 2, configuration.fieldWidth * 2));
        fieldLine++;
    }

    // Set the frames burst median (IRE) - This is used by yiqToRgbFrame to tweak the colour
    // saturation levels (compensating for MTF issues)
    currentFrameBuffer.burstLevel = burstMedianIre;

    // Set the phase IDs for the frame
    currentFrameBuffer.firstFieldPhaseID = firstFieldPhaseID;
    currentFrameBuffer.secondFieldPhaseID = secondFieldPhaseID;

    // 2D or 3D comb filter processing?
    if (!configuration.use3D) {
        // 2D comb filter processing

        // Perform 1D processing
        split1D(&currentFrameBuffer);

        // Perform 2D processing
        split2D(&currentFrameBuffer);

        // Split the IQ values
        splitIQ(&currentFrameBuffer);

        // Copy the current frame to a temporary buffer, so operations on the frame do not
        // alter the original data
        tempYiqBuffer = currentFrameBuffer.yiqBuffer;

        // Process the copy of the current frame
        adjustY(&currentFrameBuffer, tempYiqBuffer);
        if (configuration.colorlpf) filterIQ(currentFrameBuffer.yiqBuffer);
        doYNR(tempYiqBuffer);
        doCNR(tempYiqBuffer);

        // Convert the YIQ result to RGB
        rgbOutputBuffer = yiqToRgbFrame(tempYiqBuffer, currentFrameBuffer.burstLevel);
    } else {
        // 3D comb filter processing

        // Perform 1D processing
        split1D(&currentFrameBuffer);

        // Perform 2D processing
        split2D(&currentFrameBuffer);

        // Split the IQ values (populates Y)
        splitIQ(&currentFrameBuffer);

        tempYiqBuffer = currentFrameBuffer.yiqBuffer;

        // Process the copy of the current frame (needed for the Y image used by the optical flow)
        adjustY(&currentFrameBuffer, tempYiqBuffer);
        if (configuration.colorlpf) filterIQ(currentFrameBuffer.yiqBuffer);
        doYNR(tempYiqBuffer);
        doCNR(tempYiqBuffer);

        opticalFlow.denseOpticalFlow(currentFrameBuffer.yiqBuffer, currentFrameBuffer.kValues);

        // Perform 3D processing
        split3D(&currentFrameBuffer, &previousFrameBuffer);

        // Split the IQ values
        splitIQ(&currentFrameBuffer);

        tempYiqBuffer = currentFrameBuffer.yiqBuffer;

        // Process the copy of the current frame (for final output now flow detection has been performed)
        adjustY(&currentFrameBuffer, tempYiqBuffer);
        if (configuration.colorlpf) filterIQ(currentFrameBuffer.yiqBuffer);
        doYNR(tempYiqBuffer);
        doCNR(tempYiqBuffer);

        // Convert the YIQ result to RGB
        rgbOutputBuffer = yiqToRgbFrame(tempYiqBuffer, currentFrameBuffer.burstLevel);

        // Overlay the optical flow map if required
        if (configuration.showOpticalFlowMap) overlayOpticalFlowMap(currentFrameBuffer, rgbOutputBuffer);

        // Store the current frame
        previousFrameBuffer = currentFrameBuffer;
    }

    // Return the output frame
    return rgbOutputBuffer;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Tasks to be performed if the configuration changes
void Comb::postConfigurationTasks()
{
    // Set the IRE scale
    irescale = (configuration.whiteIre - configuration.blackIre) / 100;

    // Set the frame height
    frameHeight = ((configuration.fieldHeight * 2) - 1);
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
 * GetLinePhase returns true if the color burst is rising at the leading edge.
 */

inline qint32 Comb::GetFieldID(FrameBuffer *frameBuffer, qint32 lineNumber)
{
    bool isFirstField = ((lineNumber % 2) == 0);
    
    return isFirstField ? frameBuffer->firstFieldPhaseID : frameBuffer->secondFieldPhaseID;
}

// NOTE:  lineNumber is presumed to be starting at 1.  (This lines up with how splitIQ calls it)
inline bool Comb::GetLinePhase(FrameBuffer *frameBuffer, qint32 lineNumber)
{
    qint32 fieldID = GetFieldID(frameBuffer, lineNumber);
    bool isPositivePhaseOnEvenLines = (fieldID == 1) || (fieldID == 4);    

    int fieldLine = (lineNumber / 2);
    bool isEvenLine = (fieldLine % 2) == 0;
    
    return isEvenLine ? isPositivePhaseOnEvenLines : !isPositivePhaseOnEvenLines;
}

void Comb::split1D(FrameBuffer *frameBuffer)
{
    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        // Get a pointer to the line's data
        quint16 *line = reinterpret_cast<quint16 *>(frameBuffer->rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qreal tc1 = (((line[h + 2] + line[h - 2]) / 2) - line[h]);

            // Record the 1D C value
            frameBuffer->clpbuffer[0].pixel[lineNumber][h] = tc1;
        }
    }
}

// This could do with an explaination of what it is doing...
void Comb::split2D(FrameBuffer *frameBuffer)
{
    // Dummy black line.
    static constexpr qreal blackLine[911] = {0};

    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        // Get pointers to the surrounding lines.
        // If a line we need is outside the active area, use blackLine instead.
        const qreal *previousLine = blackLine;
        if (lineNumber - 2 >= configuration.firstActiveLine) {
            previousLine = frameBuffer->clpbuffer[0].pixel[lineNumber - 2];
        }
        const qreal *currentLine = frameBuffer->clpbuffer[0].pixel[lineNumber];
        const qreal *nextLine = blackLine;
        if (lineNumber + 2 < frameHeight) {
            nextLine = frameBuffer->clpbuffer[0].pixel[lineNumber + 2];
        }

        // 2D filtering.
        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qreal tc1;

            qreal kp, kn;

            kp  = fabs(fabs(currentLine[h]) - fabs(previousLine[h])); // - fabs(c1line[h] * .20);
            kp += fabs(fabs(currentLine[h - 1]) - fabs(previousLine[h - 1]));
            kp -= (fabs(currentLine[h]) + fabs(currentLine[h - 1])) * .10;
            kn  = fabs(fabs(currentLine[h]) - fabs(nextLine[h])); // - fabs(c1line[h] * .20);
            kn += fabs(fabs(currentLine[h - 1]) - fabs(nextLine[h - 1]));
            kn -= (fabs(currentLine[h]) + fabs(nextLine[h - 1])) * .10;

            kp /= 2;
            kn /= 2;

            qreal p_2drange = 45 * irescale;
            kp = qBound(0.0, 1 - (kp / p_2drange), 1.0);
            kn = qBound(0.0, 1 - (kn / p_2drange), 1.0);

            qreal sc = 1.0;

            if ((kn > 0) || (kp > 0)) {
                if (kn > (3 * kp)) kp = 0;
                else if (kp > (3 * kn)) kn = 0;

                sc = (2.0 / (kn + kp));// * max(kn * kn, kp * kp);
                if (sc < 1.0) sc = 1.0;
            } else {
                if ((fabs(fabs(previousLine[h]) - fabs(nextLine[h])) - fabs((nextLine[h] + previousLine[h]) * .2)) <= 0) {
                    kn = kp = 1;
                }
            }

            tc1  = ((frameBuffer->clpbuffer[0].pixel[lineNumber][h] - previousLine[h]) * kp * sc);
            tc1 += ((frameBuffer->clpbuffer[0].pixel[lineNumber][h] - nextLine[h]) * kn * sc);
            tc1 /= 8; //(2 * 2);

            // Record the 2D C value
            frameBuffer->clpbuffer[1].pixel[lineNumber][h] = tc1;
        }
    }
}

// This could do with an explaination of what it is doing...
// Only apply 3D processing to stationary pixels
void Comb::split3D(FrameBuffer *currentFrame, FrameBuffer *previousFrame)
{
    // If there is no previous frame data (i.e. this is the first frame), use the current frame.
    if (previousFrame->rawbuffer.size() == 0) {
        previousFrame = currentFrame;
    }

    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {

        quint16 *currentLine = reinterpret_cast<quint16 *>(currentFrame->rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);
        quint16 *previousLine = reinterpret_cast<quint16 *>(previousFrame->rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            currentFrame->clpbuffer[2].pixel[lineNumber][h] = (previousLine[h] - currentLine[h]) / 2;
        }
    }
}

// Spilt the I and Q
void Comb::splitIQ(FrameBuffer *frameBuffer)
{
    // Clear the target frame YIQ buffer
    frameBuffer->yiqBuffer.clear();

    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        // Get a pointer to the line's data
        quint16 *line = reinterpret_cast<quint16 *>(frameBuffer->rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);
        bool linePhase = GetLinePhase(frameBuffer, lineNumber);

        qreal si = 0, sq = 0;
        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qint32 phase = h % 4;

            // Take the 2D C
            qreal cavg = frameBuffer->clpbuffer[1].pixel[lineNumber][h]; // 2D C average

            if (configuration.use3D && frameBuffer->kValues.size() != 0) {
                // The motionK map returns K (0 for stationary pixels to 1 for moving pixels)
                cavg  = frameBuffer->clpbuffer[1].pixel[lineNumber][h] * frameBuffer->kValues[(lineNumber * 910) + h]; // 2D mix
                cavg += frameBuffer->clpbuffer[2].pixel[lineNumber][h] * (1 - frameBuffer->kValues[(lineNumber * 910) + h]); // 3D mix

                // Use only 3D (for testing!)
                //cavg = frameBuffer->clpbuffer[2].pixel[lineNumber][h];
            }

            if (!linePhase) cavg = -cavg;

            switch (phase) {
                case 0: sq = cavg; break;
                case 1: si = -cavg; break;
                case 2: sq = -cavg; break;
                case 3: si = cavg; break;
                default: break;
            }

            frameBuffer->yiqBuffer[lineNumber][h].y = line[h];
            frameBuffer->yiqBuffer[lineNumber][h].i = si;
            frameBuffer->yiqBuffer[lineNumber][h].q = sq;
        }
    }
}

// Filter the IQ from the input YIQ buffer
void Comb::filterIQ(YiqBuffer &yiqBuffer)
{
    auto iFilter(f_colorlpi);
    auto qFilter(configuration.colorlpf_hq ? f_colorlpi : f_colorlpq);

    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        iFilter.clear();
        qFilter.clear();

        qint32 qoffset = 2; // f_colorlpf_hq ? f_colorlpi_offset : f_colorlpq_offset;

        qreal filti = 0, filtq = 0;

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
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

/*
 * This applies an FIR coring filter to both I and Q color channels.  It's a simple (crude?) NR technique used
 * by LD players, but effective especially on the Y/luma channel.
 *
 * A coring filter removes high frequency components (.4mhz chroma, 2.8mhz luma) of a signal up to a certain point,
 * which removes small high frequency noise.
 */

void Comb::doCNR(YiqBuffer &yiqBuffer)
{
    if (configuration.cNRLevel == 0) return;

    // High-pass filters for I/Q
    auto iFilter(f_nrc);
    auto qFilter(f_nrc);

    // nr_c is the coring level
    qreal nr_c = configuration.cNRLevel * irescale;

    QVector<YIQ> hplinef;
    hplinef.resize(configuration.fieldWidth + 32);

    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        // Filters not cleared from previous line

        for (qint32 h = configuration.activeVideoStart; h <= configuration.activeVideoEnd; h++) {
            hplinef[h].i = iFilter.feed(yiqBuffer[lineNumber][h].i);
            hplinef[h].q = qFilter.feed(yiqBuffer[lineNumber][h].q);
        }

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            // Offset by 12 to cover the filter delay
            qreal ai = hplinef[h + 12].i;
            qreal aq = hplinef[h + 12].q;

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

void Comb::doYNR(YiqBuffer &yiqBuffer)
{
    if (configuration.yNRLevel == 0) return;

    // High-pass filter for Y
    auto yFilter(f_nr);

    // nr_y is the coring level
    qreal nr_y = configuration.yNRLevel * irescale;

    QVector<YIQ> hplinef;
    hplinef.resize(configuration.fieldWidth + 32);

    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        // Filter not cleared from previous line

        for (qint32 h = configuration.activeVideoStart; h <= configuration.activeVideoEnd; h++) {
            hplinef[h].y = yFilter.feed(yiqBuffer[lineNumber][h].y);
        }

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qreal a = hplinef[h + 12].y;

            if (fabs(a) > nr_y) {
                a = (a > 0) ? nr_y : -nr_y;
            }

            yiqBuffer[lineNumber][h].y -= a;
        }
    }
}

// Convert buffer from YIQ to RGB 16-16-16
QByteArray Comb::yiqToRgbFrame(const YiqBuffer &yiqBuffer, qreal burstLevel)
{
    QByteArray rgbOutputFrame;
    rgbOutputFrame.resize((configuration.fieldWidth * frameHeight * 3) * 2); // * 3 * 2 for RGB 16-16-16)

    // Initialise the output frame
    rgbOutputFrame.fill(0);

    // Initialise YIQ to RGB converter
    RGB rgb(configuration.whiteIre, configuration.blackIre, configuration.whitePoint100, configuration.blackAndWhite, burstLevel);

    // Perform YIQ to RGB conversion
    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        // Map the QByteArray data to an unsigned 16 bit pointer
        quint16 *linePointer = reinterpret_cast<quint16 *>(rgbOutputFrame.data() + ((configuration.fieldWidth * 3 * lineNumber) * 2));

        // Offset the output by the activeVideoStart to keep the output frame
        // in the same x position as the input video frame (the +6 realigns the output
        // to the source frame; not sure where the 2 pixel offset is coming from, but
        // it's really not important)
        qint32 o = (configuration.activeVideoStart * 3) + 6;

        // Fill the output line with the RGB values
        rgb.convertLine(&yiqBuffer[lineNumber][configuration.activeVideoStart],
                        &yiqBuffer[lineNumber][configuration.activeVideoEnd],
                        &linePointer[o]);
    }

    // Return the RGB frame data
    return rgbOutputFrame;
}

// Convert buffer from YIQ to RGB
void Comb::overlayOpticalFlowMap(const FrameBuffer &frameBuffer, QByteArray &rgbFrame)
{
    qDebug() << "Comb::overlayOpticalFlowMap(): Overlaying optical flow map onto RGB output";
//    QVector<qreal> motionKMap;
//    opticalFlow.motionK(motionKMap);

    // Overlay the optical flow map on the output RGB
    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        // Map the QByteArray data to an unsigned 16 bit pointer
        quint16 *linePointer = reinterpret_cast<quint16 *>(rgbFrame.data() + ((configuration.fieldWidth * 3 * lineNumber) * 2));

        // Fill the output frame with the RGB values
        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qint32 intensity = static_cast<qint32>(frameBuffer.kValues[(lineNumber * 910) + h] * 65535);
            // Make the RGB more purple to show where motion was detected
            qint32 red = linePointer[(h * 3)] + intensity;
            qint32 green = linePointer[(h * 3) + 2];
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

// Remove the colour data from the baseband (Y)
void Comb::adjustY(FrameBuffer *frameBuffer, YiqBuffer &yiqBuffer)
{
    // remove color data from baseband (Y)
    for (qint32 lineNumber = configuration.firstActiveLine; lineNumber < frameHeight; lineNumber++) {
        bool linePhase = GetLinePhase(frameBuffer, lineNumber);

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qreal comp = 0;
            qint32 phase = h % 4;

            YIQ y = yiqBuffer[lineNumber][h + 2];

            switch (phase) {
                case 0: comp = y.q; break;
                case 1: comp = -y.i; break;
                case 2: comp = -y.q; break;
                case 3: comp = y.i; break;
                default: break;
            }

            if (linePhase) comp = -comp;
            y.y += comp;

            yiqBuffer[lineNumber][h + 0] = y;
        }
    }
}
