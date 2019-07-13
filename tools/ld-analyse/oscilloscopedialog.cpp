/************************************************************************

    oscilloscopedialog.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-analyse is free software: you can redistribute it and/or
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

#include "oscilloscopedialog.h"
#include "ui_oscilloscopedialog.h"

OscilloscopeDialog::OscilloscopeDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::OscilloscopeDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    maximumScanLines = 625;

    // Configure the GUI
    ui->scanLineSpinBox->setMinimum(1);
    ui->scanLineSpinBox->setMaximum(625);

    ui->previousPushButton->setAutoRepeat(true);
    ui->previousPushButton->setAutoRepeatInterval(100);

    ui->nextPushButton->setAutoRepeat(true);
    ui->nextPushButton->setAutoRepeatInterval(100);

    ui->previousPushButton->setFocusPolicy(Qt::NoFocus);
    ui->nextPushButton->setFocusPolicy(Qt::NoFocus);
}

OscilloscopeDialog::~OscilloscopeDialog()
{
    delete ui;
}

void OscilloscopeDialog::showTraceImage(QByteArray firstFieldData, QByteArray secondFieldData, LdDecodeMetaData *ldDecodeMetaData, qint32 scanLine,
                                        qint32 firstField, qint32 secondField)
{
    qDebug() << "OscilloscopeDialog::showTraceImage(): Called for scan-line" << scanLine;

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData->getVideoParameters();

    // Convert the scan line into field and field line
    bool isFieldTop = true;
    qint32 fieldLine = 0;

    if (scanLine % 2 == 0) isFieldTop = false;
    else isFieldTop = true;

    if (isFieldTop) {
        fieldLine = (scanLine / 2) + 1;
    } else {
        fieldLine = (scanLine / 2);
    }

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Set the dialogue title based on the scan-line
    QString windowTitle;
    if (isFieldTop) {
        windowTitle = "Oscilloscope trace for scan-line #" + QString::number(scanLine) + " (First field line #" + QString::number(fieldLine) + ")";
    } else {
        windowTitle = "Oscilloscope trace for scan-line #" + QString::number(scanLine) + " (Second field line #" + QString::number(fieldLine) + ")";
    }

    this->setWindowTitle(windowTitle);

    // Get the raw field data for the selected line
    QImage traceImage;
    if (isFieldTop) traceImage = getFieldLineTraceImage(firstFieldData, videoParameters, fieldLine, ldDecodeMetaData->getField(firstField).dropOuts);
    else traceImage = getFieldLineTraceImage(secondFieldData, videoParameters, fieldLine, ldDecodeMetaData->getField(secondField).dropOuts);

    // Add the QImage to the QLabel in the dialogue
    ui->scopeLabel->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    ui->scopeLabel->setAlignment(Qt::AlignCenter);
    ui->scopeLabel->setMinimumSize(traceImage.width() / 4, traceImage.height() / 4); // Minimum size 1/4
    ui->scopeLabel->setMaximumSize(traceImage.width(), traceImage.height());
    ui->scopeLabel->setScaledContents(true);
    ui->scopeLabel->setPixmap(QPixmap::fromImage(traceImage));

    // Set the window's maximum size according to its contents
    this->setMaximumSize(sizeHint());

    // Update the scan-line spinbox
    ui->scanLineSpinBox->setMaximum(frameHeight);
    ui->scanLineSpinBox->setValue(scanLine);

    // Update the maximum scan-lines limit
    maximumScanLines = frameHeight;
}

QImage OscilloscopeDialog::getFieldLineTraceImage(QByteArray fieldLineData, LdDecodeMetaData::VideoParameters videoParameters, qint32 fieldLine, LdDecodeMetaData::DropOuts dropouts)
{
    qDebug() << "OscilloscopeDialog::getFieldLineTraceImage(): Called for field line" << fieldLine;

    // Range-check the scan line
    if (fieldLine > videoParameters.fieldHeight || fieldLine < 1) {
        qWarning() << "Cannot generate line trace, field line number is out of bounds!";
        return QImage();
    }

    // Get the display settings from the UI
    bool showYC = ui->YCcheckBox->isChecked();
    bool showY = ui->YcheckBox->isChecked();
    bool showC = ui->CcheckBox->isChecked();
    bool showDropouts = ui->dropoutsCheckBox->isChecked();

    // These are fixed, but may be changed to options later
    qint32 scopeHeight = 512;

    // Define image with width, height and format
    QImage scopeImage(videoParameters.fieldWidth, scopeHeight, QImage::Format_RGB888);
    QPainter scopePainter;

    // Ensure we have valid data
    if (fieldLineData.isEmpty()) {
        qWarning() << "Did not get valid RGB data for the requested field!";
        return scopeImage;
    }

    // Set the background to black
    scopeImage.fill(Qt::black);

    // Attach the scope image to the painter
    scopePainter.begin(&scopeImage);

    // Add the black and white levels
    // Note: For PAL this should be black at 64 and white at 211

    // Scale to 512 pixel height
    qint32 blackIre = 512 - (videoParameters.black16bIre / 128);
    qint32 whiteIre = 512 - (videoParameters.white16bIre / 128);
    qint32 midPointIre = videoParameters.black16bIre + ((videoParameters.white16bIre - videoParameters.black16bIre) / 2);
    midPointIre = 512 - (midPointIre / 128);

    scopePainter.setPen(Qt::white);
    scopePainter.drawLine(0, blackIre, videoParameters.fieldWidth, blackIre);
    scopePainter.drawLine(0, whiteIre, videoParameters.fieldWidth, whiteIre);

    // If showing C - draw the IRE mid-point
    if (showC) {
        scopePainter.setPen(Qt::gray);
        scopePainter.drawLine(0, midPointIre, videoParameters.fieldWidth, midPointIre);
    }

    // Draw the indicator lines
    scopePainter.setPen(Qt::blue);
    scopePainter.drawLine(videoParameters.colourBurstStart, 0, videoParameters.colourBurstStart, scopeHeight);
    scopePainter.drawLine(videoParameters.colourBurstEnd, 0, videoParameters.colourBurstEnd, scopeHeight);
    scopePainter.setPen(Qt::cyan);
    scopePainter.drawLine(videoParameters.activeVideoStart, 0, videoParameters.activeVideoStart, scopeHeight);
    scopePainter.drawLine(videoParameters.activeVideoEnd, 0, videoParameters.activeVideoEnd, scopeHeight);

    // Get the signal data
    QVector<qint32> signalDataYC; // Luminance (Y) and Chrominance (C) combined
    QVector<bool> dropOutYC; // Drop out locations within YC data
    QVector<qint32> signalDataY; // Luminance (Y) only
    QVector<qint32> signalDataC; // Chrominance (C) only
    signalDataYC.resize(videoParameters.fieldWidth);
    dropOutYC.resize(videoParameters.fieldWidth);
    signalDataY.resize(videoParameters.fieldWidth);
    signalDataC.resize(videoParameters.fieldWidth);

    // To extract Y from PAL, a LPF of 3.8MHz is required
    // To extract Y from NTSC, a LPF of 3.0MHz is required
    // To extract C from PAL, a HPF of 3.8MHz is required
    // To extract C from NTSC, a HPF of 3.0MHz is required

    // Get the YC data
    for (qint32 xPosition = 0; xPosition < videoParameters.fieldWidth; xPosition++) {
        // Get the 16-bit YC value for the current pixel (frame data is numbered 0-624 or 0-524)
        uchar *pixelPointer =  reinterpret_cast<uchar*>(fieldLineData.data()) + ((fieldLine - 1) * videoParameters.fieldWidth * 2) + (xPosition * 2);
        signalDataYC[xPosition] = (pixelPointer[1] * 256) + pixelPointer[0];

        dropOutYC[xPosition] = false;
        for (qint32 doCount = 0; doCount < dropouts.startx.size(); doCount++) {
            if (dropouts.fieldLine[doCount] == fieldLine) {
                if (xPosition >= dropouts.startx[doCount] && xPosition <= dropouts.endx[doCount]) dropOutYC[xPosition] = true;
            }
        }
    }

    if (showY) {
        // Filter out the Y data (with a simple LPF)
        qreal cutOffFrequency;
        if (videoParameters.isSourcePal) cutOffFrequency = 380000; // 3.8MHz for PAL
        else cutOffFrequency = 300000; // 3.0MHz for NTSC
        qreal sampleRate = 17734476; // details.sampleRate = 17734476;
        qreal rc = 1.0 / (cutOffFrequency * 2.0 * 3.1415927);
        qreal dt = 1.0 / sampleRate; // Sample rate
        qreal alpha = dt / (rc + dt);
        signalDataY[0] = signalDataYC[0];
        for(qint32 i = 1; i < signalDataYC.size(); i++) {
            qreal result = signalDataY[i-1] + (alpha * (signalDataYC[i] - signalDataY[i - 1]));
            signalDataY[i] = static_cast<qint32>(result);
        }
    }

    if (showC) {
        // Filter out the C data (with a simple HPF)
        qreal cutOffFrequency;
        if (videoParameters.isSourcePal) cutOffFrequency = 380000; // 3.8MHz for PAL
        else cutOffFrequency = 300000; // 3.0MHz for NTSC
        qreal sampleRate = 17734476; // details.sampleRate = 17734476;
        qreal rc = 1.0 / (cutOffFrequency * 2.0 * 3.1415927);
        qreal dt = 1.0 / sampleRate; // Sample rate
        qreal alpha = rc / (rc + dt);
        signalDataC[0] = signalDataYC[0];
        for(qint32 i = 1; i < signalDataYC.size(); i++) {
            qreal result = alpha * (signalDataC[i-1] + signalDataYC[i] - signalDataYC[i-1]);
            signalDataC[i] = static_cast<qint32>(result);
        }
    }

    // Draw the scope image
    scopePainter.setPen(Qt::yellow);
    qint32 lastSignalLevelYC = 0;
    qint32 lastSignalLevelY = 0;
    qint32 lastSignalLevelC = 0;
    for (qint32 xPosition = 0; xPosition < videoParameters.fieldWidth; xPosition++) {
        if (showYC) {
            // Scale (to 0-512) and invert
            qint32 signalLevelYC = scopeHeight - (signalDataYC[xPosition] / 128);

            if (xPosition != 0) {
                // Non-active video area YC is yellow, active is white
                if (!showY && !showC) scopePainter.setPen(Qt::white); else scopePainter.setPen(Qt::darkGray);
                if (xPosition < videoParameters.colourBurstEnd || xPosition > videoParameters.activeVideoEnd) scopePainter.setPen(Qt::yellow);

                // Highlight dropouts
                if (dropOutYC[xPosition] && showDropouts) scopePainter.setPen(Qt::red);

                // Draw a line from the last YC signal to the current one
                scopePainter.drawLine(xPosition - 1, lastSignalLevelYC, xPosition, signalLevelYC);
            }

            // Remember the current signal's level
            lastSignalLevelYC = signalLevelYC;
        }

        if (showC) {
            // Scale (to 0-512) and invert
            qint32 signalLevelC = (scopeHeight - (signalDataC[xPosition] / 128)) - (scopeHeight - midPointIre);

            if (xPosition != 0) {
                // Draw a line from the last Y signal to the current one (signal green, out of range in yellow)
                if (xPosition > videoParameters.colourBurstEnd && xPosition < videoParameters.activeVideoEnd) {
                    if (signalLevelC > blackIre || signalLevelC < whiteIre) scopePainter.setPen(Qt::yellow);
                    else scopePainter.setPen(Qt::green);
                    scopePainter.drawLine(xPosition - 1, lastSignalLevelC, xPosition, signalLevelC);
                }
            }

            // Remember the current signal's level
            lastSignalLevelC = signalLevelC;
        }

        if (showY) {
            // Scale (to 0-512) and invert
            qint32 signalLevelY = scopeHeight - (signalDataY[xPosition] / 128);

            if (xPosition != 0) {
                // Draw a line from the last Y signal to the current one (signal white, out of range in red)
                if (xPosition > videoParameters.colourBurstEnd && xPosition < videoParameters.activeVideoEnd) {
                    if (signalLevelY > blackIre || signalLevelY < whiteIre) scopePainter.setPen(Qt::red);
                    else scopePainter.setPen(Qt::white);
                    scopePainter.drawLine(xPosition - 1, lastSignalLevelY, xPosition, signalLevelY);
                }
            }

            // Remember the current signal's level
            lastSignalLevelY = signalLevelY;
        }
    }

    // Return the QImage
    scopePainter.end();
    return scopeImage;
}

// GUI signal handlers ------------------------------------------------------------------------------------------------

void OscilloscopeDialog::on_previousPushButton_clicked()
{
    if (ui->scanLineSpinBox->value() != 1) {
        emit scanLineChanged(ui->scanLineSpinBox->value() - 1);
    }
}

void OscilloscopeDialog::on_nextPushButton_clicked()
{
    if (ui->scanLineSpinBox->value() < maximumScanLines) {
        emit scanLineChanged(ui->scanLineSpinBox->value() + 1);
    }
}

void OscilloscopeDialog::on_scanLineSpinBox_valueChanged(int arg1)
{
    (void)arg1;
    emit scanLineChanged(ui->scanLineSpinBox->value());
}

void OscilloscopeDialog::on_YCcheckBox_clicked()
{
    emit scanLineChanged(ui->scanLineSpinBox->value());
}

void OscilloscopeDialog::on_YcheckBox_clicked()
{
    emit scanLineChanged(ui->scanLineSpinBox->value());
}

void OscilloscopeDialog::on_CcheckBox_clicked()
{
    emit scanLineChanged(ui->scanLineSpinBox->value());
}

void OscilloscopeDialog::on_dropoutsCheckBox_clicked()
{
    emit scanLineChanged(ui->scanLineSpinBox->value());
}
