/******************************************************************************
 * oscilloscopedialog.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "oscilloscopedialog.h"
#include "ui_oscilloscopedialog.h"
#include "tbc/logging.h"

#include <cassert>

OscilloscopeDialog::OscilloscopeDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::OscilloscopeDialog)
{
    ui->setupUi(this);
    setWindowFlags(Qt::Window);

    maximumX = 1135;
    maximumY = 625;
    lastScopeX = 0;
    lastScopeY = 0;
    scopeWidth = 0;
    fieldWidth = 0;
    hasCachedData = false;
    bothSourcesMode = false;

    // Configure the GUI
    ui->xCoordSpinBox->setMinimum(0);
    ui->xCoordSpinBox->setMaximum(maximumX - 1);
    ui->yCoordSpinBox->setMinimum(0);
    ui->yCoordSpinBox->setMaximum(maximumY - 1);

    ui->previousPushButton->setAutoRepeat(true);
    ui->previousPushButton->setAutoRepeatInterval(50);

    ui->nextPushButton->setAutoRepeat(true);
    ui->nextPushButton->setAutoRepeatInterval(50);

    ui->previousPushButton->setFocusPolicy(Qt::NoFocus);
    ui->nextPushButton->setFocusPolicy(Qt::NoFocus);
}

OscilloscopeDialog::~OscilloscopeDialog()
{
    delete ui;
}

void OscilloscopeDialog::showTraceImage(TbcSource::ScanLineData scanLineData, qint32 xCoord, qint32 yCoord, qint32 frameWidth, qint32 frameHeight, bool bothSources)
{
    tbcDebugStream() << "OscilloscopeDialog::showTraceImage(): Called with xCoord =" << xCoord << "and yCoord =" << yCoord;

    // Validate scan line data before doing anything
    if (scanLineData.fieldWidth < 1 || scanLineData.composite.empty()) {
        tbcDebugStream() << "OscilloscopeDialog::showTraceImage(): Invalid scan line data, skipping - fieldWidth:" << scanLineData.fieldWidth;
        return;
    }

    // Calculate optimal scope dimensions based on widget size (use widget size or reasonable defaults)
    qint32 widgetHeight = ui->scopeLabel->height();
    qint32 widgetWidth = ui->scopeLabel->width();
    qint32 targetHeight = (widgetHeight > 100) ? widgetHeight : 512;
    qint32 targetWidth = (widgetWidth > 100) ? widgetWidth : 910;
    // Clamp to reasonable bounds
    targetHeight = qBound(256, targetHeight, 2048);
    targetWidth = qBound(256, targetWidth, 4096);
    
    // Validate dimensions before creating the image
    if (targetHeight < 1 || targetWidth < 1) {
        tbcDebugStream() << "OscilloscopeDialog::showTraceImage(): Invalid dimensions, skipping - width:" << targetWidth << "height:" << targetHeight;
        return;
    }
    
    // Store coordinates (only after validation passes)
    maximumX = frameWidth;
    maximumY = frameHeight;
    lastScopeX = xCoord;
    lastScopeY = yCoord;
    
    // Cache the scan line data for resize events (only after validation passes)
    cachedScanLineData = scanLineData;
    hasCachedData = true;
    bothSourcesMode = bothSources;

    // Get the raw field data for the selected line
    QImage traceImage = getFieldLineTraceImage(scanLineData, lastScopeX, bothSources, targetHeight, targetWidth);

    // Add the QImage to the QLabel in the dialogue
    ui->scopeLabel->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    ui->scopeLabel->setAlignment(Qt::AlignCenter);
    ui->scopeLabel->setScaledContents(false);
    ui->scopeLabel->setPixmap(QPixmap::fromImage(traceImage));
    ui->scopeLabel->update(); // Force Qt to redraw the widget

    // Update the X coordinate spinbox
    ui->xCoordSpinBox->setMaximum(maximumX - 1);
    ui->xCoordSpinBox->setValue(lastScopeX);

    // Update the Y coordinate spinbox
    ui->yCoordSpinBox->setMaximum(maximumY - 1);
    ui->yCoordSpinBox->setValue(lastScopeY);

    // Update the line number displays
    ui->standardLineLabel->setText(QString("%1 line %2")
                                   .arg(scanLineData.systemDescription)
                                   .arg(scanLineData.lineNumber.standard()));
    ui->fieldLineLabel->setText(QString("Field %1 line %2")
                                        .arg(scanLineData.lineNumber.isFirstField() ? "1" : "2")
                                        .arg(scanLineData.lineNumber.field1()));

    // QT Bug workaround for some macOS versions
    #if defined(Q_OS_MACOS)
    	repaint();
    #endif
}

QImage OscilloscopeDialog::getFieldLineTraceImage(TbcSource::ScanLineData scanLineData, qint32 pictureDot, bool bothSources, qint32 scopeHeight, qint32 scopeWidth)
{
    // Validate dimensions before creating any images
    if (scopeWidth < 1 || scopeHeight < 1 || scanLineData.fieldWidth < 1) {
        qWarning() << "OscilloscopeDialog::getFieldLineTraceImage(): Invalid dimensions - scopeWidth:" << scopeWidth 
                   << "scopeHeight:" << scopeHeight << "fieldWidth:" << scanLineData.fieldWidth;
        // Return a minimal valid blank image
        QImage blankImage(256, 256, QImage::Format_RGB888);
        blankImage.fill(Qt::black);
        return blankImage;
    }
    
    // Ensure we have valid data
    if (scanLineData.composite.empty()) {
        qWarning() << "Did not get valid data for the requested field!";
        // Return blank image with correct size
        QImage blankImage(scopeWidth, scopeHeight, QImage::Format_RGB888);
        blankImage.fill(Qt::black);
        return blankImage;
    }
    
    // Get the display settings from the UI
    bool showYC = ui->YCcheckBox->isChecked();
    bool showY = ui->YcheckBox->isChecked();
    bool showC = ui->CcheckBox->isChecked();
    bool showDropouts = ui->dropoutsCheckBox->isChecked();

    // Calculate x-axis scale factor to fit the widget width
    double xScale = static_cast<double>(scopeWidth) / static_cast<double>(scanLineData.fieldWidth);
    this->scopeWidth = scopeWidth; // Store for mouse coordinate calculations
    this->fieldWidth = scanLineData.fieldWidth; // Store original field width for mouse coordinate conversion

    qint32 scopeScale = 65536 / scopeHeight;

    // Define image with width, height and format
    QImage scopeImage(scopeWidth, scopeHeight, QImage::Format_RGB888);
    QPainter scopePainter;
    assert(scanLineData.composite.size() == scanLineData.fieldWidth);
    assert(scanLineData.luma.size() == scanLineData.fieldWidth);

    // Set the background to black
    scopeImage.fill(Qt::black);

    // Attach the scope image to the painter
    scopePainter.begin(&scopeImage);

    // Add the black and white levels
    // Note: For PAL this should be black at 64 and white at 211

    // Scale to 512 pixel height
    qint32 blackIre = scopeHeight - (scanLineData.blackIre / scopeScale);
    qint32 whiteIre = scopeHeight - (scanLineData.whiteIre / scopeScale);
    qint32 midPointIre = scanLineData.blackIre + ((scanLineData.whiteIre - scanLineData.blackIre) / 2);
    midPointIre = scopeHeight - (midPointIre / scopeScale);

    scopePainter.setPen(Qt::white);
    scopePainter.drawLine(0, blackIre, scopeWidth, blackIre);
    scopePainter.drawLine(0, whiteIre, scopeWidth, whiteIre);

    // If showing C - draw the IRE mid-point
    if (showC) {
        scopePainter.setPen(Qt::gray);
        scopePainter.drawLine(0, midPointIre, scopeWidth, midPointIre);
    }

    // Draw the indicator lines (scaled to image width)
    scopePainter.setPen(Qt::blue);
    scopePainter.drawLine(scanLineData.colourBurstStart * xScale, 0, scanLineData.colourBurstStart * xScale, scopeHeight);
    scopePainter.drawLine(scanLineData.colourBurstEnd * xScale, 0, scanLineData.colourBurstEnd * xScale, scopeHeight);
    scopePainter.setPen(Qt::cyan);
    scopePainter.drawLine(scanLineData.activeVideoStart * xScale, 0, scanLineData.activeVideoStart * xScale, scopeHeight);
    scopePainter.drawLine(scanLineData.activeVideoEnd * xScale, 0, scanLineData.activeVideoEnd * xScale, scopeHeight);

    // Get the signal data
    const QVector<qint32> &signalDataYC = scanLineData.composite; // Composite - luma (Y) and chroma (C) combined
    const QVector<bool> &dropOutYC = scanLineData.isDropout; // Drop out locations within YC data
    const QVector<qint32> &signalDataY = scanLineData.luma; // Luma (Y) only
    QVector<qint32> signalDataC(scanLineData.fieldWidth); // Chroma (C) only

    if (showC) {
        if (!bothSources) {
            for (qint32 i = 0; i < scanLineData.fieldWidth; i++) {
                signalDataC[i] = signalDataYC[i] - signalDataY[i];
            }
        } else {
            signalDataC = scanLineData.chroma;
        }
    }

    // Draw the scope image
    qint32 lastSignalLevelYC = 0;
    qint32 lastXPositionScaled = 0;
    if (showYC) {
        for (qint32 xPosition = 0; xPosition < scanLineData.fieldWidth; xPosition++) {
            qint32 xPositionScaled = xPosition * xScale;
            // Scale (to 0-scopeHeight) and invert
            qint32 signalLevelYC = scopeHeight - (signalDataYC[xPosition] / scopeScale);

            if (xPosition != 0) {
                // Non-active video area YC is yellow, active is white
                if (!showY && !showC) scopePainter.setPen(Qt::white); else scopePainter.setPen(Qt::darkGray);
                if (xPosition < scanLineData.colourBurstEnd || xPosition > scanLineData.activeVideoEnd) scopePainter.setPen(Qt::yellow);

                // Highlight dropouts
                if (dropOutYC[xPosition] && showDropouts) scopePainter.setPen(Qt::red);

                // Draw a line from the last YC signal to the current one
                scopePainter.drawLine(lastXPositionScaled, lastSignalLevelYC, xPositionScaled, signalLevelYC);
            }

            // Remember the current signal's level and position
            lastSignalLevelYC = signalLevelYC;
            lastXPositionScaled = xPositionScaled;
        }
    }

    // Draw the Y/C traces, for the active region only
    qint32 lastSignalLevelY = 0;
    qint32 lastSignalLevelC = 0;
    qint32 lastXPosScaled = scanLineData.activeVideoStart * xScale;
    if (scanLineData.isActiveLine) {
        for (qint32 xPosition = scanLineData.activeVideoStart; xPosition < scanLineData.activeVideoEnd; xPosition++) {
            qint32 xPosScaled = xPosition * xScale;
            
            if (showC) {
                // Scale (to 0-scopeHeight) and invert
                qint32 signalLevelC = (scopeHeight - (signalDataC[xPosition] / scopeScale)) - (scopeHeight - midPointIre);

                if (xPosition != scanLineData.activeVideoStart) {
                    // Draw a line from the last Y signal to the current one (signal green, out of range in yellow)
                    if (signalLevelC > blackIre || signalLevelC < whiteIre) scopePainter.setPen(Qt::yellow);
                    else scopePainter.setPen(Qt::green);
                    scopePainter.drawLine(lastXPosScaled, lastSignalLevelC, xPosScaled, signalLevelC);
                }

                // Remember the current signal's level
                lastSignalLevelC = signalLevelC;
            }

            if (showY) {
                // Scale (to 0-scopeHeight) and invert
                qint32 signalLevelY = scopeHeight - (signalDataY[xPosition] / scopeScale);

                if (xPosition != scanLineData.activeVideoStart) {
                    // Draw a line from the last Y signal to the current one (signal white, out of range in red)
                    if (signalLevelY > blackIre || signalLevelY < whiteIre) scopePainter.setPen(Qt::red);
                    else scopePainter.setPen(Qt::white);
                    scopePainter.drawLine(lastXPosScaled, lastSignalLevelY, xPosScaled, signalLevelY);
                }

                // Remember the current signal's level
                lastSignalLevelY = signalLevelY;
            }
            
            lastXPosScaled = xPosScaled;
        }
    }

    // Draw the picture dot position line (scaled to image width)
    scopePainter.setPen(QColor(0, 255, 0, 127));
    qint32 pictureDotScaled = pictureDot * xScale;
    scopePainter.drawLine(pictureDotScaled, 0, pictureDotScaled, scopeHeight);

    // Return the QImage
    scopePainter.end();
    return scopeImage;
}

// GUI signal handlers ------------------------------------------------------------------------------------------------

void OscilloscopeDialog::on_previousPushButton_clicked()
{
    if (ui->yCoordSpinBox->value() != 0) {
        emit scopeCoordsChanged(lastScopeX, ui->yCoordSpinBox->value() - 1);
    }
}

void OscilloscopeDialog::on_nextPushButton_clicked()
{
    if (ui->yCoordSpinBox->value() < maximumY - 1) {
        emit scopeCoordsChanged(lastScopeX, ui->yCoordSpinBox->value() + 1);
    }
}

void OscilloscopeDialog::on_xCoordSpinBox_valueChanged(int arg1)
{
    (void)arg1;
    if (ui->xCoordSpinBox->value() != lastScopeX)
        emit scopeCoordsChanged(ui->xCoordSpinBox->value(), lastScopeY);
}

void OscilloscopeDialog::on_yCoordSpinBox_valueChanged(int arg1)
{
    (void)arg1;
    if (ui->yCoordSpinBox->value() != lastScopeY)
        emit scopeCoordsChanged(lastScopeX, ui->yCoordSpinBox->value() );
}

void OscilloscopeDialog::on_YCcheckBox_clicked()
{
    emit scopeCoordsChanged(lastScopeX, lastScopeY);
}

void OscilloscopeDialog::on_YcheckBox_clicked()
{
    emit scopeCoordsChanged(lastScopeX, lastScopeY);
}

void OscilloscopeDialog::on_CcheckBox_clicked()
{
    emit scopeCoordsChanged(lastScopeX, lastScopeY);
}

void OscilloscopeDialog::on_dropoutsCheckBox_clicked()
{
    emit scopeCoordsChanged(lastScopeX, lastScopeY);
}

// Mouse press event handler
void OscilloscopeDialog::mousePressEvent(QMouseEvent *event)
{
    // Get the mouse position relative to our scene
    QPoint origin = ui->scopeLabel->mapFromGlobal(QCursor::pos());

    // Check that the mouse click is within bounds of the current picture
    qint32 oX = origin.x();
    qint32 oY = origin.y();

    if (oX + 1 >= 0 &&
            oY >= 0 &&
            oX + 1 <= ui->scopeLabel->width() &&
            oY <= ui->scopeLabel->height()) {

        // Is shift held down?
        if (event->modifiers().testFlag(Qt::ShiftModifier)) {
            mouseLevelSelect(oY);
        } else {
            mousePictureDotSelect(oX);
        }
        event->accept();
    }
}

// Mouse drag event handler
void OscilloscopeDialog::mouseMoveEvent(QMouseEvent *event)
{
    // Handle this the same way as a click
    mousePressEvent(event);
}

// Handle a click on the scope with shift held down, to select a level
void OscilloscopeDialog::mouseLevelSelect(qint32 oY)
{
    double unscaledYR = (65536.0 / static_cast<double>(ui->scopeLabel->height())) * static_cast<double>(oY);

    qint32 level = qBound(0, 65535 - static_cast<qint32>(unscaledYR), 65535);
    emit scopeLevelSelect(level);
}

// Handle a click on the scope without shift held down, to select a sample
void OscilloscopeDialog::mousePictureDotSelect(qint32 oX)
{
    // Convert from widget pixel coordinates to image pixel coordinates
    // Since setScaledContents is false, this is 1:1 when image fits, but might differ if centered
    double imageX = oX;
    
    // Convert from image pixel coordinates to field sample coordinates
    // The image width (scopeWidth) represents the full field width (fieldWidth)
    double unscaledXR = (static_cast<double>(fieldWidth) / static_cast<double>(scopeWidth)) * imageX;

    qint32 unscaledX = static_cast<qint32>(unscaledXR);
    if (unscaledX > fieldWidth - 1) unscaledX = fieldWidth - 1;
    if (unscaledX < 0) unscaledX = 0;

    // Remember the last dot selected
    lastScopeX = unscaledX;

    emit scopeCoordsChanged(lastScopeX, lastScopeY);
}

// Resize event handler - regenerate the scope image when dialog is resized
void OscilloscopeDialog::resizeEvent(QResizeEvent *event)
{
    QDialog::resizeEvent(event);
    
    // Regenerate the scope image with the new size if we have cached data
    // Also verify that the cached data has valid dimensions before regenerating
    if (hasCachedData && cachedScanLineData.fieldWidth > 0 && !cachedScanLineData.composite.empty()) {
        showTraceImage(cachedScanLineData, lastScopeX, lastScopeY, maximumX, maximumY, bothSourcesMode);
    }
}
