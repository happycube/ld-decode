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
    qint32 flowOptions = 0;
    if (framesProcessed == 0) {
        // No, so use the initial flow option
        flowOptions = cv::OPTFLOW_USE_INITIAL_FLOW;
    }

    // Perform the OpenCV compute dense optical flow (Gunnar Farneback’s algorithm)
    if (framesProcessed > 1) {
        // prev – first 8-bit single-channel input image.
        // next – second input image of the same size and the same type as prev.
        // flow – computed flow image that has the same size as prev and type CV_32FC2.
        // pyr_scale – parameter, specifying the image scale (<1) to build pyramids for each image;
        //             pyr_scale=0.5 means a classical pyramid, where each next layer is twice smaller than the previous one.
        // levels – number of pyramid layers including the initial image; levels=1 means that no extra layers are created and
        //          only the original images are used.
        // winsize – averaging window size; larger values increase the algorithm robustness to image noise and give more chances
        //           for fast motion detection, but yield more blurred motion field.
        // iterations – number of iterations the algorithm does at each pyramid level.
        // poly_n – size of the pixel neighborhood used to find polynomial expansion in each pixel; larger values mean that the
        //          image will be approximated with smoother surfaces, yielding more robust algorithm and more blurred motion
        //          field, typically poly_n =5 or 7.
        // poly_sigma – standard deviation of the Gaussian that is used to smooth derivatives used as a basis for the polynomial
        //              expansion; for poly_n=5, you can set poly_sigma=1.1, for poly_n=7, a good value would be poly_sigma=1.5.
        // flags - OPTFLOW_USE_INITIAL_FLOW or OPTFLOW_FARNEBACK_GAUSSIAN

        calcOpticalFlowFarneback(currentFrame, previousFrame, flowMap, 0.5, 4, 60, 3, 7, 1.5, flowOptions);
    }

    // Copy the current frame to the previous frame
    previousFrame = currentFrame.clone();

    framesProcessed++;
    qDebug() << "OpticalFlow::feedFrameY(): Processed" << framesProcessed << "optical flow frames";
}

// This method examines the flow map of the frame and decides (for each pixel) if it
// is either in motion or stationary (providing a boolean result map)
void OpticalFlow::motionK(QVector<qreal> &kValues)
{
    // Do we have any flow map data yet?
    // Note: the openCV optical flow will not return a valid Mat unless we have run it against
    // at least the 'levels' parameter of the flow processing
    if (framesProcessed < 3) {
        qDebug() << "OpticalFlow::motionK(): Called, but the flow map is not initialised!";
        return;
    }

    kValues.resize(910 * 525);

    for (qint32 y = 0; y < 525; y++) {
        for (qint32 x = 0; x < 910; x++) {
            // Get the value of the current point (cv::Point2f is a floating-point cv::Point_)
            const cv::Point2f& flowpoint = flowMap.at<cv::Point2f>(y, x);

            // Get the point's displacement value (how many pixels the point moved (pixel velocity) since the last frame)
            // Note: flowpoint.x is the x displacement and flowpoint.y is the y displacement
            //
            // Since a lot of video motion is panning, we double the sensitivty in the x direction (by
            // doubling the x distance)
            qreal pointValue = calculateDistance(static_cast<qreal>(flowpoint.y), static_cast<qreal>(flowpoint.x) * 2);

            // 0.3 sets the sensitivity of the motion decision (more than 0.3 pixels displacement = in motion)
            if (pointValue > 0.1) kValues[(910 * y) + x] = clamp(pointValue - 0.1, 0, 1); // Pixel moved
            else kValues[(910 * y) + x] = 0; // Pixel didn't move
        }
    }
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

// This method calculates the distance between points where x is the difference between the x-coordinates
// and y is the difference between the y coordinates
qreal OpticalFlow::calculateDistance(qreal yDifference, qreal xDifference)
{
    return sqrt((yDifference * yDifference) + (xDifference * xDifference));
}
