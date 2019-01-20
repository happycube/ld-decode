/************************************************************************

    comb.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
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
    // Define the filters
    f_hpy = new Filter(f_nr);
    f_hpi = new Filter(f_nrc);
    f_hpq = new Filter(f_nrc);

    // Set default configuration
    configuration.blackAndWhite = false;
    configuration.use3D = false;
    configuration.whitePoint100 = false;

    configuration.colorlpf = true; // Use as default
    configuration.colorlpf_hq = true; // Use as default

    // These are the overall dimensions of the input frame
    configuration.fieldWidth = 910;
    configuration.fieldHeight = 263;

    // These are the start and end points for the active video line
    configuration.activeVideoStart = 40;
    configuration.activeVideoEnd = 840;

    // This sets the first visible frame line
    configuration.firstVisibleFrameLine = 43;

    // Set the 16-bit IRE levels
    configuration.blackIre = 15360;
    configuration.whiteIre = 51200;

    postConfigurationTasks();
}

// Get the comb filter configuration parameters
Comb::Configuration Comb::getConfiguration(void)
{
    return configuration;
}

// Set the comb filter configuration parameters
void Comb::setConfiguration(Comb::Configuration configurationParam)
{
    // Range check the frame dimensions
    if (configuration.fieldWidth > max_x) qCritical() << "Comb::Comb(): Frame width exceeds allowed maximum!";
    if (((configuration.fieldHeight * 2) - 1) > max_x) qCritical() << "Comb::Comb(): Frame height exceeds allowed maximum!";

    // Range check the video start
    if (configurationParam.activeVideoStart < 16) qCritical() << "Comb::Comb(): activeVideoStart must be > 16!";

    configuration = configurationParam;
    postConfigurationTasks();
}

// Process the input buffer into the RGB output buffer
QByteArray Comb::process(QByteArray firstFieldInputBuffer, QByteArray secondFieldInputBuffer, qreal burstMedianIre,
                         qint32 firstFieldPhaseID, qint32 secondFieldPhaseID)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    QVector<yiqLine_t> tempYiqBuffer;
    tempYiqBuffer.resize(frameHeight);

    if (configuration.use3D) {
        // Shift the frames in the buffer (0 = newest frame, 2 = oldest)
        frameBuffer[2] = frameBuffer[1];
        frameBuffer[1] = frameBuffer[0];
    }

    // Interlace the input fields and place in the frame[0]'s raw buffer
    qint32 fieldLine = 0;
    frameBuffer[0].rawbuffer.clear();
    for (qint32 frameLine = 0; frameLine < (configuration.fieldHeight * 2); frameLine += 2) {
        frameBuffer[0].rawbuffer.append(firstFieldInputBuffer.mid(fieldLine * configuration.fieldWidth * 2, configuration.fieldWidth * 2));
        if (frameLine < frameHeight) frameBuffer[0].rawbuffer.append(secondFieldInputBuffer.mid(fieldLine * configuration.fieldWidth * 2, configuration.fieldWidth * 2));
        fieldLine++;
    }

    // Set the frames burst median (IRE) - This is used by yiqToRgbFrame to tweak the colour
    // saturation levels (compensating for MTF issues)
    frameBuffer[0].burstLevel = burstMedianIre;

    // Set the phase IDs for the frame
    frameBuffer[0].firstFieldPhaseID = firstFieldPhaseID;
    frameBuffer[0].secondFieldPhaseID = secondFieldPhaseID;

    // Define an output buffer
    QByteArray rgbOutputBuffer;

    // Process using 2D or 3D?
    if (!configuration.use3D) {
        // Perform 1D processing
        split1D(0);

        // Perform 2D processing
        split2D(0);

        // Split the IQ values
        splitIQ(0);

        // Copy the current frame to a temporary buffer, so operations on the frame do not
        // alter the original data
        tempYiqBuffer = frameBuffer[0].yiqBuffer;

        // Process the copy of the current frame
        adjustY(0, tempYiqBuffer);
        if (configuration.colorlpf) filterIQ(tempYiqBuffer);
        doYNR(tempYiqBuffer);
        doCNR(tempYiqBuffer);

        // Convert the YIQ result to RGB
        rgbOutputBuffer = yiqToRgbFrame(0, tempYiqBuffer);
    } else {
        // Perform 1D processing on the current frame
        split1D(0);

        // Perform 2D processing on the current frame
        split2D(0);

        // Split the IQ values of the current frame
        splitIQ(0);

        // Ensure we have at least 2 frames before performing optical flow
        if (frameCounter > 0) {
            // Make a copy of the current frame
            tempYiqBuffer = frameBuffer[0].yiqBuffer;

            // Process the copy of the current frame
            adjustY(0, tempYiqBuffer);
            if (configuration.colorlpf) filterIQ(tempYiqBuffer);
            doYNR(tempYiqBuffer);
            doCNR(tempYiqBuffer);

            // Perform the optical flow method on the copy of the current frame (0)
            // This method writes back the result to frame buffer [1]
            opticalFlow3D(tempYiqBuffer, frameCounter);
        }

        // If we don't yet have 3 frames, then we cannot 3D filter
        if (frameCounter < 2) {
            // 2D filter
            qDebug() << "Comb::process(): 2D fallback for initial frame" << frameCounter;
            tempYiqBuffer = frameBuffer[0].yiqBuffer;

            // Process the copy of the current frame
            adjustY(0, tempYiqBuffer);
            if (configuration.colorlpf) filterIQ(tempYiqBuffer);
            doYNR(tempYiqBuffer);
            doCNR(tempYiqBuffer);

            // Convert the YIQ result to RGB
            rgbOutputBuffer = yiqToRgbFrame(0, tempYiqBuffer);
        } else {
            // 3D filter
            split3D();  // Split 3D on frame buffer [1]
            splitIQ(1); // Split QI on frame buffer [1]

            // Make a copy of frame buffer 1
            tempYiqBuffer = frameBuffer[1].yiqBuffer;

            // Process the copy of the frame buffer; note: we have to pass the frame buffer number too
            // for the frame's parameters as they are not copied into the tempYiqBuffer
            adjustY(1, tempYiqBuffer);
            if (configuration.colorlpf) filterIQ(tempYiqBuffer);
            doYNR(tempYiqBuffer);
            doCNR(tempYiqBuffer);

            // Convert the YIQ result to RGB
            rgbOutputBuffer = yiqToRgbFrame(1, tempYiqBuffer);
        }
    }

    // Return the output frame
    frameCounter++;
    return rgbOutputBuffer;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Tasks to be performed if the configuration changes
void Comb::postConfigurationTasks(void)
{

    // Set the IRE scale
    irescale = (configuration.whiteIre - configuration.blackIre) / 100;
    qDebug() << "Comb::postConfigurationTasks(): irescale is" << irescale;

    nr_c = 0.0;
    nr_y = 1.0;
    nr_c *= irescale; // Always 0?
    nr_y *= irescale;

    // Calculate some 2D/3D processing configuration parameters
    p_3dcore = 0; // no optical flow = 1.25
    p_3drange = 0.5; // no optical flow = 5.5
    p_2drange = 10 * irescale;

    // Allocate the frame buffers
    if (configuration.use3D) frameBuffer.resize(3); // 3 buffers required for 3D processing
    else frameBuffer.resize(1);

    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    if (configuration.use3D) {
        frameBuffer[0].yiqBuffer.resize(frameHeight);
        frameBuffer[1].yiqBuffer.resize(frameHeight);
        frameBuffer[2].yiqBuffer.resize(frameHeight);
    } else frameBuffer[0].yiqBuffer.resize(frameHeight);

    // Reset the frame counter
    frameCounter = 0;
}

// Filter the IQ from the input YIQ line
void Comb::filterIQ(QVector<yiqLine_t> &yiqBuffer)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        Filter f_i(configuration.colorlpf_hq ? f_colorlpi : f_colorlpi);
        Filter f_q(configuration.colorlpf_hq ? f_colorlpi : f_colorlpq);

        qint32 qoffset = 2; // f_colorlpf_hq ? f_colorlpi_offset : f_colorlpq_offset;

        qreal filti = 0, filtq = 0;

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qint32 phase = h % 4;

            switch (phase) {
                case 0: filti = f_i.feed(yiqBuffer[lineNumber].pixel[h].i); break;
                case 1: filtq = f_q.feed(yiqBuffer[lineNumber].pixel[h].q); break;
                case 2: filti = f_i.feed(yiqBuffer[lineNumber].pixel[h].i); break;
                case 3: filtq = f_q.feed(yiqBuffer[lineNumber].pixel[h].q); break;
                default: break;
            }

            yiqBuffer[lineNumber].pixel[h - qoffset].i = filti;
            yiqBuffer[lineNumber].pixel[h - qoffset].q = filtq;
        }
    }
}

// This could do with an explaination of what it is doing...
void Comb::split1D(qint32 currentFrameBuffer)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    bool topInvertphase = false;
    bool bottomInvertphase = false;
    bool invertphase = false;

    if (frameBuffer[currentFrameBuffer].firstFieldPhaseID == 2 || frameBuffer[currentFrameBuffer].firstFieldPhaseID == 3)
        topInvertphase = true;

    if (frameBuffer[currentFrameBuffer].secondFieldPhaseID == 1 || frameBuffer[currentFrameBuffer].secondFieldPhaseID == 4)
        bottomInvertphase = true;

    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        // Get a pointer to the line's data
        quint16 *line = reinterpret_cast<quint16 *>(frameBuffer[currentFrameBuffer].rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);

        // Determine if the line phase should be inverted
        if ((lineNumber % 2) == 0) {
            topInvertphase = !topInvertphase;
            invertphase = topInvertphase;
        } else {
            bottomInvertphase = !bottomInvertphase;
            invertphase = bottomInvertphase;
        }

        Filter f_1di(f_colorlpi);
        Filter f_1dq(f_colorlpq);

        // This offset is only applied if 1D processing is selected,
        // no idea why thought... but it causes an underflow since if
        // the activeVideoStart is less than f_toffset...
        //qint32 f_toffset = 16;

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qint32 phase = h % 4;
            qreal tc1 = (((line[h + 2] + line[h - 2]) / 2) - line[h]);
            qreal tc1f = 0, tsi = 0, tsq = 0;

            if (!invertphase) tc1 = -tc1;

            switch (phase) {
                case 0: tsi = tc1; tc1f = f_1di.feed(tsi); break;
                case 1: tsq = -tc1; tc1f = -f_1dq.feed(tsq); break;
                case 2: tsi = -tc1; tc1f = -f_1di.feed(tsi); break;
                case 3: tsq = tc1; tc1f = f_1dq.feed(tsq); break;
                default: break;
            }

            if (!invertphase) {
                tc1 = -tc1;
                tc1f = -tc1f;
            }

            frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber][h] = tc1;
            //if (configuration.filterDepth == 1) frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber][h - f_toffset] = tc1f;

            frameBuffer[currentFrameBuffer].combk[0][lineNumber][h] = 1;
        }
    }
}

// This could do with an explaination of what it is doing...
void Comb::split2D(qint32 currentFrameBuffer)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        qreal *p1line = frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber - 2];
        qreal *c1line = frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber];
        qreal *n1line = frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber + 2];

        // 2D filtering.  can't do top or bottom line - calculated between
        // 1d and 3d because this is filtered
        if ((lineNumber >= 4) && (lineNumber < (frameHeight - 1))) {
            for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
                qreal tc1;

                qreal kp, kn;

                kp  = fabs(fabs(c1line[h]) - fabs(p1line[h])); // - fabs(c1line[h] * .20);
                kp += fabs(fabs(c1line[h - 1]) - fabs(p1line[h - 1]));
                kp -= (fabs(c1line[h]) + fabs(c1line[h - 1])) * .10;
                kn  = fabs(fabs(c1line[h]) - fabs(n1line[h])); // - fabs(c1line[h] * .20);
                kn += fabs(fabs(c1line[h - 1]) - fabs(n1line[h - 1]));
                kn -= (fabs(c1line[h]) + fabs(n1line[h - 1])) * .10;

                kp /= 2;
                kn /= 2;

                p_2drange = 45 * irescale;
                kp = clamp(1 - (kp / p_2drange), 0, 1);
                kn = clamp(1 - (kn / p_2drange), 0, 1);

                qreal sc = 1.0;

                if ((kn > 0) || (kp > 0)) {
                    if (kn > (3 * kp)) kp = 0;
                    else if (kp > (3 * kn)) kn = 0;

                    sc = (2.0 / (kn + kp));// * max(kn * kn, kp * kp);
                    if (sc < 1.0) sc = 1.0;
                } else {
                    if ((fabs(fabs(p1line[h]) - fabs(n1line[h])) - fabs((n1line[h] + p1line[h]) * .2)) <= 0) {
                        kn = kp = 1;
                    }
                }


                tc1  = ((frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber][h] - p1line[h]) * kp * sc);
                tc1 += ((frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber][h] - n1line[h]) * kn * sc);
                tc1 /= (2 * 2);

                frameBuffer[currentFrameBuffer].clpbuffer[1][lineNumber][h] = tc1;
                frameBuffer[currentFrameBuffer].combk[1][lineNumber][h] = 1.0; // (sc * (kn + kp)) / 2.0;
            }
        }

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            if ((lineNumber >= 2) && (lineNumber <= (frameHeight - 2))) {
                frameBuffer[currentFrameBuffer].combk[1][lineNumber][h] *= 1 - frameBuffer[currentFrameBuffer].combk[2][lineNumber][h];
            }

            // 1D
            frameBuffer[currentFrameBuffer].combk[0][lineNumber][h] = 1 - frameBuffer[currentFrameBuffer].combk[2][lineNumber][h] - frameBuffer[currentFrameBuffer].combk[1][lineNumber][h];
        }
    }
}

// This could do with an explaination of what it is doing...
// Removed the passed currentField as this always has to be 1, so it's not required
// This method always writes back the result to frameBuffer[1]
void Comb::split3D(void)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        // Line points to the line in the current frame
        quint16 *line = reinterpret_cast<quint16 *>(frameBuffer[1].rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);

        // shortcuts for previous/next 1D/pixel frame lines
        quint16 *p3line = reinterpret_cast<quint16 *>(frameBuffer[0].rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);
        //quint16 *n3line = reinterpret_cast<quint16 *>(frameBuffer[2].rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);

//        Filter lp_3d({0.005719569452904, 0.009426612841315, 0.019748592575455, 0.036822680065252, 0.058983880135427, 0.082947830292278, 0.104489989820068,
//                      0.119454688318951, 0.124812312996699, 0.119454688318952, 0.104489989820068, 0.082947830292278, 0.058983880135427, 0.036822680065252,
//                      0.019748592575455, 0.009426612841315, 0.005719569452904}, {1.0});

        // This code doesn't seem to do anything now the f_opticalflow config is removed?
//        // need to prefilter K using a LPF
//        qreal _k[max_x];
//        for (qint32 h = configuration.activeVideoStart; (configuration.use3D) && (h < configuration.activeVideoEnd); h++) {
//            qint32 adr = (lineNumber * configuration.fieldWidth) + h;

//            // Since the underlying raw buffer is a QByteArray we have to map the data points to quint16
//            quint16 *f0 = reinterpret_cast<quint16 *>(frameBuffer[0].rawbuffer.data() + (adr * 2));
//            quint16 *f1 = reinterpret_cast<quint16 *>(frameBuffer[1].rawbuffer.data() + (adr * 2));
//            quint16 *f2 = reinterpret_cast<quint16 *>(frameBuffer[2].rawbuffer.data() + (adr * 2));

//            qreal __k = abs(f0[0] - f2[0]);
//            __k += abs((f1[0] - f2[0]) - (f1[0] - f0[0]));

//            if (h > 12) _k[h - 8] = lp_3d.feed(__k);
//            if (h >= 836) _k[h] = __k;
//        }

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            // Something to do with the optical flow detection...
            frameBuffer[1].clpbuffer[2][lineNumber][h] = (p3line[h] - line[h]);

            if ((lineNumber >= 2) && (lineNumber <= (frameHeight - 2))) {
                frameBuffer[1].combk[1][lineNumber][h] = 1 - frameBuffer[1].combk[2][lineNumber][h];
            }

            // 1D
            frameBuffer[1].combk[0][lineNumber][h] = 1 - frameBuffer[1].combk[2][lineNumber][h] - frameBuffer[1].combk[1][lineNumber][h];
        }
    }
}

// Spilt the I and Q
void Comb::splitIQ(qint32 currentFrameBuffer)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    bool topInvertphase = false;
    bool bottomInvertphase = false;
    bool invertphase = false;

    if (frameBuffer[currentFrameBuffer].firstFieldPhaseID == 2 || frameBuffer[currentFrameBuffer].firstFieldPhaseID == 3)
        topInvertphase = true;

    if (frameBuffer[currentFrameBuffer].secondFieldPhaseID == 1 || frameBuffer[currentFrameBuffer].secondFieldPhaseID == 4)
        bottomInvertphase = true;

    // Clear the target frame YIQ buffer
    frameBuffer[currentFrameBuffer].yiqBuffer.clear();
    frameBuffer[currentFrameBuffer].yiqBuffer.resize(frameHeight);

    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        // Get a pointer to the line's data
        quint16 *line = reinterpret_cast<quint16 *>(frameBuffer[currentFrameBuffer].rawbuffer.data() + (lineNumber * configuration.fieldWidth) * 2);

        // Determine if the line phase should be inverted
        if ((lineNumber % 2) == 0) {
            topInvertphase = !topInvertphase;
            invertphase = topInvertphase;
        } else {
            bottomInvertphase = !bottomInvertphase;
            invertphase = bottomInvertphase;
        }

        qreal si = 0, sq = 0;
        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qint32 phase = h % 4;
            qreal cavg = 0;

            cavg += (frameBuffer[currentFrameBuffer].clpbuffer[2][lineNumber][h] * frameBuffer[currentFrameBuffer].combk[2][lineNumber][h]);
            cavg += (frameBuffer[currentFrameBuffer].clpbuffer[1][lineNumber][h] * frameBuffer[currentFrameBuffer].combk[1][lineNumber][h]);
            cavg += (frameBuffer[currentFrameBuffer].clpbuffer[0][lineNumber][h] * frameBuffer[currentFrameBuffer].combk[0][lineNumber][h]);

            cavg /= 2;

            if (!invertphase) cavg = -cavg;

            switch (phase) {
                case 0: sq = cavg; break;
                case 1: si = -cavg; break;
                case 2: sq = -cavg; break;
                case 3: si = cavg; break;
                default: break;
            }

            frameBuffer[currentFrameBuffer].yiqBuffer[lineNumber].pixel[h].y = line[h];
            frameBuffer[currentFrameBuffer].yiqBuffer[lineNumber].pixel[h].i = si;
            frameBuffer[currentFrameBuffer].yiqBuffer[lineNumber].pixel[h].q = sq;
        }
    }
}

// Some kind of noise reduction filter on the C?
void Comb::doCNR(QVector<yiqLine_t> &yiqBuffer, qreal min)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    if (nr_c < min) nr_c = min;
    if (nr_c <= 0) return;

    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        YIQ hplinef[max_x + 32];

        for (qint32 h = configuration.activeVideoStart; h <= configuration.activeVideoEnd; h++) {
            hplinef[h].i = f_hpi->feed(yiqBuffer[lineNumber].pixel[h].i);
            hplinef[h].q = f_hpq->feed(yiqBuffer[lineNumber].pixel[h].q);
        }

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qreal ai = hplinef[h + 12].i;
            qreal aq = hplinef[h + 12].q;

            if (fabs(ai) > nr_c) {
                ai = (ai > 0) ? nr_c : -nr_c;
            }

            if (fabs(aq) > nr_c) {
                aq = (aq > 0) ? nr_c : -nr_c;
            }

            yiqBuffer[lineNumber].pixel[h].i -= ai;
            yiqBuffer[lineNumber].pixel[h].q -= aq;
        }
    }
}

// Some kind of noise reduction filter on the Y?
void Comb::doYNR(QVector<yiqLine_t> &yiqBuffer, qreal min)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    if (nr_y < min) nr_y = min;
    if (nr_y <= 0) return;

    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        YIQ hplinef[max_x + 32];

        for (qint32 h = configuration.activeVideoStart; h <= configuration.activeVideoEnd; h++) {
            hplinef[h].y = f_hpy->feed(yiqBuffer[lineNumber].pixel[h].y);
        }

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qreal a = hplinef[h + 12].y;

            if (fabs(a) > nr_y) {
                a = (a > 0) ? nr_y : -nr_y;
            }

            yiqBuffer[lineNumber].pixel[h].y -= a;
        }
    }
}

// Convert frame from YIQ to RGB
QByteArray Comb::yiqToRgbFrame(qint32 currentFrameBuffer, QVector<yiqLine_t> yiqBuffer)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    QByteArray rgbOutputFrame;
    rgbOutputFrame.resize((configuration.fieldWidth * frameHeight * 3) * 2); // * 3 for RGB 16-16-16)

    // Initialise the output frame
    rgbOutputFrame.fill(0);

    // Perform YIQ to RGB conversion
    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        // Map the QByteArray data to an unsigned 16 bit pointer
        quint16 *line_output = reinterpret_cast<quint16 *>(rgbOutputFrame.data() + ((configuration.fieldWidth * 3 * lineNumber) * 2));

        // Offset the output by the activeVideoStart to keep the output frame
        // in the same x position as the input video frame (the +6 realigns the output
        // to the source frame; not sure where the 2 pixel offset is coming from, but
        // it's really not important)
        qint32 o = (configuration.activeVideoStart * 3) + 6;

        // Fill the output frame with the RGB values
        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            RGB r(configuration.whiteIre, configuration.blackIre, configuration.whitePoint100, configuration.blackAndWhite);
            YIQ yiq = yiqBuffer[lineNumber].pixel[h];

            cline = lineNumber;
            r.conv(yiq, frameBuffer[currentFrameBuffer].burstLevel);

            line_output[o++] = static_cast<quint16>(r.r);
            line_output[o++] = static_cast<quint16>(r.g);
            line_output[o++] = static_cast<quint16>(r.b);
        }
    }

    // Return the RGB frame data
    return rgbOutputFrame;
}

// Perform optical flow detection
// Seems to be writing back the result into frame buffer [1]...
void Comb::opticalFlow3D(QVector<yiqLine_t> yiqBuffer, qint32 frameCounter)
{
    const qint32 cysize = 252; // Field height extent?
    const qint32 cxsize = max_x - 70; // Field width extent?

    quint16 fieldbuf[max_x * cysize];
    //quint16 flowmap[max_y][cxsize];

    // Note: No check on the unmanaged memsets below; probably should add some (or remove the memsets)
    memset(fieldbuf, 0, sizeof(fieldbuf));

    qint32 y;
    cv::Mat pic;

    for (qint32 field = 0; field < 2; field++) {
        // Split the frame back into two fields for optical flow detection
        for (y = 0; y < cysize; y++) {
            for (qint32 x = 0; x < cxsize; x++) {
                // Note: this was overflowing to line 525 in the original code...
                qint32 cbufLine = 23 + field + (y * 2);
                if (cbufLine < yiqBuffer.size()) fieldbuf[(y * cxsize) + x] = static_cast<quint16>(yiqBuffer[cbufLine].pixel[70 + x].y);
            }
        }

        pic = cv::Mat(252, cxsize, CV_16UC1, fieldbuf);
        if (frameCounter > 1) {
            calcOpticalFlowFarneback(pic, prev[field], flow[field], 0.5, 4, 60, 3, 7, 1.5, (frameCounter > 2) ? cv::OPTFLOW_USE_INITIAL_FLOW : 0);
        }
        prev[field] = pic.clone();
    }

    qreal min = p_3dcore;  // 0.0
    qreal max = p_3drange; // 0.5

    if (frameCounter > 1) {
        for (y = 0; y < cysize; y++) {
            for (qint32 x = 0; x < cxsize; x++) {
                const cv::Point2f& flowpoint1 = flow[0].at<cv::Point2f>(y, x);
                const cv::Point2f& flowpoint2 = flow[1].at<cv::Point2f>(y, x);

                qreal c1 = 1 - clamp((ctor(static_cast<double>(flowpoint1.y),
                                            static_cast<double>(flowpoint1.x) * 2) - min) / max, 0, 1);
                qreal c2 = 1 - clamp((ctor(static_cast<double>(flowpoint2.y),
                                            static_cast<double>(flowpoint2.x) * 2) - min) / max, 0, 1);
                qreal c = (c1 < c2) ? c1 : c2;

                // Place the resulting data into the 2nd frame buffer's combk[2]
                frameBuffer[1].combk[2][(y * 2)][70 + x] = c;
                frameBuffer[1].combk[2][(y * 2) + 1][70 + x] = c;
            }
        }
    }
}

// Remove the colour data from the baseband (Y)
void Comb::adjustY(qint32 currentFrameBuffer, QVector<yiqLine_t> &yiqBuffer)
{
    qint32 frameHeight = ((configuration.fieldHeight * 2) - 1);

    bool topInvertphase = false;
    bool bottomInvertphase = false;
    bool invertphase = false;

    if (frameBuffer[currentFrameBuffer].firstFieldPhaseID == 2 || frameBuffer[currentFrameBuffer].firstFieldPhaseID == 3)
        topInvertphase = true;

    if (frameBuffer[currentFrameBuffer].secondFieldPhaseID == 1 || frameBuffer[currentFrameBuffer].secondFieldPhaseID == 4)
        bottomInvertphase = true;

    // remove color data from baseband (Y)
    //for (qint32 lineNumber = 0; lineNumber < frameHeight; lineNumber++) {
    for (qint32 lineNumber = configuration.firstVisibleFrameLine; lineNumber < frameHeight; lineNumber++) {
        // Determine if the line phase should be inverted
        if ((lineNumber % 2) == 0) {
            topInvertphase = !topInvertphase;
            invertphase = topInvertphase;
        } else {
            bottomInvertphase = !bottomInvertphase;
            invertphase = bottomInvertphase;
        }

        for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
            qreal comp = 0;
            qint32 phase = h % 4;

            YIQ y = yiqBuffer[lineNumber].pixel[h + 2];

            switch (phase) {
                case 0: comp = y.q; break;
                case 1: comp = -y.i; break;
                case 2: comp = -y.q; break;
                case 3: comp = y.i; break;
                default: break;
            }

            if (invertphase) comp = -comp;
            y.y += comp;

            yiqBuffer[lineNumber].pixel[h + 0] = y;
        }
    }
}

qreal Comb::clamp(qreal v, qreal low, qreal high)
{
        if (v < low) return low;
        else if (v > high) return high;
        else return v;
}

qreal Comb::atan2deg(qreal y, qreal x)
{
    qreal rv = static_cast<double>(atan2(static_cast<long double>(y), x) * (180 / M_PIl));
    if (rv < 0) rv += 360;
    return rv;
}

qreal Comb::ctor(qreal r, qreal i)
{
    return sqrt((r * r) + (i * i));
}
