/************************************************************************

    opticalflow.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

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

#include "opticalflow.h"

OpticalFlow::OpticalFlow()
{
    framesProcessed = 0;
}

// Feed a new frame to the optical flow map processing
// Input is a vector of 16-bit Y values for the NTSC frame (910x525)
void OpticalFlow::feedFrameY(YiqBuffer yiqBuffer)
{
    // Convert the buffer of Y values into an OpenCV n-dimensional dense array (cv::Mat)
    cv::Mat currentFrame = convertYtoMat(yiqBuffer.yValues());

    // Do we have an initial flowmap?
    qint32 flowOptions = cv::OPTFLOW_USE_INITIAL_FLOW;
    if (framesProcessed == 0) {
        flowOptions = 0;
        previousFrame = currentFrame.clone();
    }

    // Perform the OpenCV compute dense optical flow (Gunnar Farneback’s algorithm)
    if (framesProcessed > 1) {
        calcOpticalFlowFarneback(currentFrame, previousFrame, flowMap, 0.5, 4, 60, 3, 7, 1.5, flowOptions);
    }

    // Copy the current frame to the previous frame
    previousFrame = currentFrame.clone();

    framesProcessed++;
    qDebug() << "OpticalFlow::feedFrameY(): Processed" << framesProcessed << "optical flow frames";
}

// Method to get the pixel K values (motion) for the frame
QVector<qreal> OpticalFlow::motionK(void)
{
    // Do we have any flow map data yet?
    if (framesProcessed < 3) {
        qDebug() << "OpticalFlow::motionK(): Called, but the flow map is not initialised!";
        return QVector<qreal>();
    }

    qDebug() << "OpticalFlow::motionK(): Called";

    QVector<qreal> kValues;
    kValues.resize(910 * 525);

    for (qint32 y = 0; y < 525; y++) {
        for (qint32 x = 0; x < 910; x++) {
            // Get the value of the current point (cv::Point2f is a floating-point cv::Point_)
            const cv::Point2f& flowpoint = flowMap.at<cv::Point2f>(y, x);

            // Get the point value, invert it and clamp it between 0.0 and 1.0
            kValues[(910 * y) + x] = 1 - clamp(convertCPointToReal(static_cast<qreal>(flowpoint.y), static_cast<qreal>(flowpoint.x)), 0, 1);
        }
    }

    return kValues;
}

// Method to get the ready status of the flow map (true = initialised)
bool OpticalFlow::isInitialised(void)
{
    if (framesProcessed < 3) return false;

    return true;
}

// Method to convert a qreal vector frame of Y values to an OpenCV n-dimensional dense array (cv::Mat)
cv::Mat OpticalFlow::convertYtoMat(QVector<qreal> yBuffer)
{
    quint16 frame[910 * 525];
    memset(frame, 0, sizeof(frame));

    // Check the size of the input buffer
    if (yBuffer.size() != (910 * 525)) {
        qDebug() << "OpticalFlow::convertYtoMat(): yBuffer size is" << yBuffer.size() << "- expected" << (910 * 525) << "!";
    }

    // Firstly we have to convert the Y vector of real numbers into quint16 values for OpenCV
    for (qint32 pixel = 0; pixel < yBuffer.size(); pixel++) {
        frame[pixel] = static_cast<quint16>(yBuffer[pixel]);
    }

    // Return a Mat y * x in CV_16UC1 format
    return cv::Mat(525, 910, CV_16UC1, frame);
}

// Method to clamp a value within a low and high range
qreal OpticalFlow::clamp(qreal v, qreal low, qreal high)
{
        if (v < low) return low;
        else if (v > high) return high;
        else return v;
}

// Method to convert a C point to a qreal value (more explaination required!)
qreal OpticalFlow::convertCPointToReal(qreal y, qreal x)
{
    return sqrt((y * y) + (x * x));
}
