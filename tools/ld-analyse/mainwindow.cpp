/************************************************************************

    mainwindow.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
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

#include "mainwindow.h"
#include "ui_mainwindow.h"

MainWindow::MainWindow(QString inputFilenameParam, QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::MainWindow)
{
    ui->setupUi(this);

    // Load the application's configuration
    configuration = new Configuration();

    // Add a status bar to show the state of the source video file
    ui->statusBar->addWidget(&sourceVideoStatus);
    sourceVideoStatus.setText(tr("No source video file loaded"));

    // Set the initial frame number
    currentFrameNumber = 1;
    isFileOpen = false;

    // Add an event filter to the frame viewer label to catch mouse events
    ui->frameViewerLabel->installEventFilter(ui->frameViewerLabel);

    // Set up the oscilloscope dialogue
    oscilloscopeDialog = new OscilloscopeDialog(this);

    // Connect to the scan line changed signal from the oscilloscope dialogue
    connect(oscilloscopeDialog, &OscilloscopeDialog::scanLineChanged, this, &MainWindow::scanLineChangedSignalHandler);
    lastScopeLine = 1;

    // Set up the about dialogue
    aboutDialog = new AboutDialog(this);

    // Set up the VBI dialogue
    vbiDialog = new VbiDialog(this);

    // Set up the NTSC dialogue
    ntscDialog = new NtscDialog(this);

    // Load the window geometry from the configuration
    restoreGeometry(configuration->getMainWindowGeometry());
    vbiDialog->restoreGeometry(configuration->getVbiDialogGeometry());
    ntscDialog->restoreGeometry(configuration->getNtscDialogGeometry());
    oscilloscopeDialog->restoreGeometry(configuration->getOscilloscopeDialogGeometry());

    // Set up the GUI
    updateGuiUnloaded();

    // Was a filename specified on the command line?
    if (!inputFilenameParam.isEmpty()) {
        loadTbcFile(inputFilenameParam);
    }
}

MainWindow::~MainWindow()
{
    // Save the window geometry to the configuration
    configuration->setMainWindowGeometry(saveGeometry());
    configuration->setVbiDialogGeometry(vbiDialog->saveGeometry());
    configuration->setNtscDialogGeometry(ntscDialog->saveGeometry());
    configuration->setOscilloscopeDialogGeometry(oscilloscopeDialog->saveGeometry());
    configuration->writeConfiguration();

    // Close the source video if open
    sourceVideo.close();
    delete ui;
}

// Method to update the GUI when a file is loaded
void MainWindow::updateGuiLoaded(void)
{
    // Enable the frame controls
    ui->frameNumberSpinBox->setEnabled(true);
    ui->previousPushButton->setEnabled(true);
    ui->nextPushButton->setEnabled(true);
    ui->frameHorizontalSlider->setEnabled(true);
    ui->combFilterPushButton->setEnabled(true);
    ui->sourcePushButton->setEnabled(true);

    // Disable the option check boxes
    ui->highlightDropOutsCheckBox->setEnabled(true);
    ui->showActiveVideoCheckBox->setEnabled(true);

    // Update the current frame number
    currentFrameNumber = 1;
    ui->frameNumberSpinBox->setMinimum(1);
    ui->frameNumberSpinBox->setMaximum(getAvailableNumberOfFrames());
    ui->frameNumberSpinBox->setValue(currentFrameNumber);
    ui->frameHorizontalSlider->setMinimum(1);
    ui->frameHorizontalSlider->setMaximum(getAvailableNumberOfFrames());
    ui->frameHorizontalSlider->setPageStep(getAvailableNumberOfFrames() / 100);
    ui->frameHorizontalSlider->setValue(currentFrameNumber);

    // Enable the VBI data groupbox
    ui->vbiGroupBox->setEnabled(true);

    // Enable the frame info group box
    ui->frameGroupBox->setEnabled(true);

    // Enable menu options
    ui->actionLine_scope->setEnabled(true);
    ui->actionVBI->setEnabled(true);
    ui->actionNTSC->setEnabled(true);

    // Show the current frame
    showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());

    isFileOpen = true;
}

// Method to update the GUI when a file is unloaded
void MainWindow::updateGuiUnloaded(void)
{
    // Disable the frame controls
    ui->frameNumberSpinBox->setEnabled(false);
    ui->previousPushButton->setEnabled(false);
    ui->nextPushButton->setEnabled(false);
    ui->frameHorizontalSlider->setEnabled(false);
    ui->combFilterPushButton->setEnabled(false);
    ui->sourcePushButton->setEnabled(false);

    // Disable the option check boxes
    ui->highlightDropOutsCheckBox->setEnabled(false);
    ui->showActiveVideoCheckBox->setEnabled(false);

    // Update the current frame number
    currentFrameNumber = 1;
    ui->frameNumberSpinBox->setValue(currentFrameNumber);
    ui->frameHorizontalSlider->setValue(currentFrameNumber);

    // Allow the next and previous frame buttons to auto-repeat
    ui->previousPushButton->setAutoRepeat(true);
    ui->previousPushButton->setAutoRepeatDelay(500);
    ui->previousPushButton->setAutoRepeatInterval(10);
    ui->nextPushButton->setAutoRepeat(true);
    ui->nextPushButton->setAutoRepeatDelay(500);
    ui->nextPushButton->setAutoRepeatInterval(10);

    // Disable the VBI data groupbox
    ui->vbiGroupBox->setEnabled(false);

    // Disable the frame info group box
    ui->frameGroupBox->setEnabled(false);

    // Set the window title
    this->setWindowTitle(tr("ld-analyse"));

    // Set the status bar text
    sourceVideoStatus.setText(tr("No source video file loaded"));

    // Disable menu options
    ui->actionLine_scope->setEnabled(false);
    ui->actionVBI->setEnabled(false);
    ui->actionNTSC->setEnabled(false);

    // Hide the displayed frame
    hideFrame();

    isFileOpen = false;
}

// Method to get the available number of frames
qint32 MainWindow::getAvailableNumberOfFrames(void)
{
    qint32 frameOffset = 0;

    // It's possible that the TBC file will start on the wrong field, so we have to allow for
    // that here by skipping a field if the order isn't right
    if (ldDecodeMetaData.getVideoParameters().isFieldOrderEvenOdd && !ldDecodeMetaData.getField(1).isEven) frameOffset++;
    else if (!ldDecodeMetaData.getVideoParameters().isFieldOrderEvenOdd && ldDecodeMetaData.getField(1).isEven) frameOffset++;

    return (sourceVideo.getNumberOfAvailableFields() / 2) - frameOffset;
}

// Method to get the first and second field numbers based on the frame number
qint32 MainWindow::getFirstFieldNumber(qint32 frameNumber)
{
    // Get the video parameter metadata
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Point at the first field in the TBC file (according to the current frame number)
    qint32 firstFieldNumber; // = (frameNumber * 2);
    qint32 secondFieldNumber;

    if (videoParameters.isFieldOrderEvenOdd) {
        // TBC Field order is even then odd, so we get second field followed by first field
        secondFieldNumber = (frameNumber * 2) - 1;
        firstFieldNumber = secondFieldNumber + 1;
    } else {
        // TBC Field order is odd then even, so we get first field followed by second field
        firstFieldNumber = (frameNumber * 2) - 1;
        secondFieldNumber = firstFieldNumber + 1;
    }

    // It's possible that the TBC file will start on the wrong field, so we have to allow for
    // that here by skipping a field if the order isn't right
    if (ldDecodeMetaData.getField(firstFieldNumber).isEven) {
        // First field is always odd...
        firstFieldNumber++;
        secondFieldNumber++;
        qDebug() << "MainWindow::getFirstFieldNumber(): TBC file has an extra field at the start (out of field order) - skipping";
    }

    // Range check the field number
    if (firstFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "MainWindow::getFirstFieldNumber(): First field number exceed the available number of fields!";
        return 1;
    }

    // Range check the field number
    if (secondFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "MainWindow::getFirstFieldNumber(): Second field number exceed the available number of fields!";
        return 2;
    }

    // Reverse the field ordering for PAL sources
    if (videoParameters.isSourcePal) return secondFieldNumber;

    return firstFieldNumber;
}

qint32 MainWindow::getSecondFieldNumber(qint32 frameNumber)
{
    // Get the video parameter metadata
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Point at the first field in the TBC file (according to the current frame number)
    qint32 firstFieldNumber; // = (frameNumber * 2);
    qint32 secondFieldNumber;

    if (videoParameters.isFieldOrderEvenOdd) {
        // TBC Field order is even then odd, so we get second field followed by first field
        secondFieldNumber = (frameNumber * 2) - 1;
        firstFieldNumber = secondFieldNumber + 1;
    } else {
        // TBC Field order is odd then even, so we get first field followed by second field
        firstFieldNumber = (frameNumber * 2) - 1;
        secondFieldNumber = firstFieldNumber + 1;
    }

    // It's possible that the TBC file will start on the wrong field, so we have to allow for
    // that here by skipping a field if the order isn't right
    if (ldDecodeMetaData.getField(firstFieldNumber).isEven) {
        // First field is always odd...
        firstFieldNumber++;
        secondFieldNumber++;
    }

    // Range check the field number
    if (firstFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "MainWindow::getSecondFieldNumber(): First field number exceed the available number of fields!";
        return 1;
    }

    // Range check the field number
    if (secondFieldNumber > sourceVideo.getNumberOfAvailableFields()) {
        qCritical() << "MainWindow::getSecondFieldNumber(): Second field number exceed the available number of fields!";
        return 2;
    }

    // Reverse the field ordering for PAL sources
    if (videoParameters.isSourcePal) return firstFieldNumber;

    return secondFieldNumber;
}

// Method to display a sequential frame
void MainWindow::showFrame(qint32 frameNumber, bool showActiveVideoArea, bool highlightDropOuts)
{
    // Get the required field numbers
    qint32 firstFieldNumber = getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = getSecondFieldNumber(frameNumber);

    qDebug() << "MainWindow::showFrame(): Frame number" << frameNumber << "has an first-field of" << firstFieldNumber <<
                "and an second field of" << secondFieldNumber;

    // Get a QImage for the frame
    QImage frameImage = generateQImage(firstFieldNumber, secondFieldNumber);

    // Get the field metadata
    LdDecodeMetaData::Field firstField = ldDecodeMetaData.getField(firstFieldNumber);
    LdDecodeMetaData::Field secondField = ldDecodeMetaData.getField(secondFieldNumber);

    // Show the field numbers
    ui->firstFieldLabel->setText(QString::number(firstFieldNumber));
    ui->secondFieldLabel->setText(QString::number(secondFieldNumber));

    // Show the field order
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    if (videoParameters.isFieldOrderValid) {
        if (videoParameters.isFieldOrderEvenOdd) ui->fieldOrderLabel->setText(tr("Even/Odd"));
        else ui->fieldOrderLabel->setText(tr("Odd/Even"));
    } else {
        ui->fieldOrderLabel->setText(tr("Missing metadata"));
    }

    // Show the active video extent?
    if (showActiveVideoArea) {
        // Create a painter object
        QPainter imagePainter;

        imagePainter.begin(&frameImage);
        imagePainter.setPen(Qt::cyan);

        // Determine the first and last active scan line based on the source format
        qint32 firstActiveScanLine;
        qint32 lastActiveScanLine;
        if (videoParameters.isSourcePal) {
            firstActiveScanLine = 44;
            lastActiveScanLine = 617;
        } else {
            firstActiveScanLine = 40;
            lastActiveScanLine = 519;
        }

        // Outline the active video area
        imagePainter.drawLine(videoParameters.activeVideoStart, firstActiveScanLine, videoParameters.activeVideoStart, lastActiveScanLine);
        imagePainter.drawLine(videoParameters.activeVideoEnd, firstActiveScanLine, videoParameters.activeVideoEnd, lastActiveScanLine);
        imagePainter.drawLine(videoParameters.activeVideoStart, firstActiveScanLine, videoParameters.activeVideoEnd, firstActiveScanLine);
        imagePainter.drawLine(videoParameters.activeVideoStart, lastActiveScanLine, videoParameters.activeVideoEnd, lastActiveScanLine);

        // Outline the VP415 Domesday player active video area
        qreal vp415FirstActiveScanLine = firstActiveScanLine + (((videoParameters.fieldHeight * 2) / 100) * 1.0);
        qreal vp415LastActiveScanLine = lastActiveScanLine - (((videoParameters.fieldHeight * 2) / 100) * 1.0);
        qreal vp415VideoStart = videoParameters.activeVideoStart + ((videoParameters.fieldWidth / 100) * 1.0);
        qreal vp415VideoEnd = videoParameters.activeVideoEnd - ((videoParameters.fieldWidth / 100) * 1.0);
        imagePainter.drawLine(static_cast<qint32>(vp415VideoStart), static_cast<qint32>(vp415FirstActiveScanLine),
                              static_cast<qint32>(vp415VideoStart), static_cast<qint32>(vp415LastActiveScanLine));
        imagePainter.drawLine(static_cast<qint32>(vp415VideoEnd), static_cast<qint32>(vp415FirstActiveScanLine),
                              static_cast<qint32>(vp415VideoEnd), static_cast<qint32>(vp415LastActiveScanLine));

        imagePainter.drawLine(static_cast<qint32>(vp415VideoStart), static_cast<qint32>(vp415FirstActiveScanLine),
                              static_cast<qint32>(vp415VideoEnd), static_cast<qint32>(vp415FirstActiveScanLine));
        imagePainter.drawLine(static_cast<qint32>(vp415VideoStart), static_cast<qint32>(vp415LastActiveScanLine),
                              static_cast<qint32>(vp415VideoEnd), static_cast<qint32>(vp415LastActiveScanLine));

        // End the painter object
        imagePainter.end();
    }

    if (highlightDropOuts) {
        // Create a painter object
        QPainter imagePainter;
        imagePainter.begin(&frameImage);

        // Draw the drop out data for the first field
        imagePainter.setPen(Qt::red);
        for (qint32 dropOutIndex = 0; dropOutIndex < firstField.dropOuts.startx.size(); dropOutIndex++) {
            qint32 startx = firstField.dropOuts.startx[dropOutIndex];
            qint32 endx = firstField.dropOuts.endx[dropOutIndex];
            qint32 fieldLine = firstField.dropOuts.fieldLine[dropOutIndex];

            imagePainter.drawLine(startx, ((fieldLine - 1) * 2) + 1, endx, ((fieldLine - 1) * 2) + 1);
        }

        // Draw the drop out data for the second field
        imagePainter.setPen(Qt::blue);
        for (qint32 dropOutIndex = 0; dropOutIndex < secondField.dropOuts.startx.size(); dropOutIndex++) {
            qint32 startx = secondField.dropOuts.startx[dropOutIndex];
            qint32 endx = secondField.dropOuts.endx[dropOutIndex];
            qint32 fieldLine = secondField.dropOuts.fieldLine[dropOutIndex];

            imagePainter.drawLine(startx, ((fieldLine - 1) * 2), endx, ((fieldLine - 1) * 2));
        }

        // End the painter object
        imagePainter.end();
    }

    // Add the first field VBI data to the dialogue
    if (firstField.vbi.inUse) {
        ui->even0VbiLabel->setText("0x" + QString::number(firstField.vbi.vbi16, 16));
        ui->even1VbiLabel->setText("0x" + QString::number(firstField.vbi.vbi17, 16));
        ui->even2VbiLabel->setText("0x" + QString::number(firstField.vbi.vbi18, 16));
    } else {
        ui->even0VbiLabel->setText("No metadata");
        ui->even1VbiLabel->setText("No metadata");
        ui->even2VbiLabel->setText("No metadata");
    }

    // Add the second field VBI data to the dialogue
    if (secondField.vbi.inUse) {
        ui->odd0VbiLabel->setText("0x" + QString::number(secondField.vbi.vbi16, 16));
        ui->odd1VbiLabel->setText("0x" + QString::number(secondField.vbi.vbi17, 16));
        ui->odd2VbiLabel->setText("0x" + QString::number(secondField.vbi.vbi18, 16));
    } else {
        ui->odd0VbiLabel->setText("No metadata");
        ui->odd1VbiLabel->setText("No metadata");
        ui->odd2VbiLabel->setText("No metadata");
    }

    // Update the VBI dialogue
    vbiDialog->updateVbi(firstField, secondField);

    // Update the NTSC dialogue
    ntscDialog->updateNtsc(firstField, secondField);

    // Add the QImage to the QLabel in the dialogue
    ui->frameViewerLabel->clear();
    ui->frameViewerLabel->setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    ui->frameViewerLabel->setAlignment(Qt::AlignCenter);
    ui->frameViewerLabel->setMinimumSize(frameImage.width(), frameImage.height());
    ui->frameViewerLabel->setMaximumSize(frameImage.width(), frameImage.height());
    ui->frameViewerLabel->setScaledContents(false);
    ui->frameViewerLabel->setPixmap(QPixmap::fromImage(frameImage));

    // If the scope window is open, update it too (using the last scope line selected by the user)
    if (oscilloscopeDialog->isVisible()) {
        // Show the oscilloscope dialogue for the selected scan-line
        updateOscilloscopeDialogue(currentFrameNumber, lastScopeLine);
    }
}

// Method to create a QImage for a source video frame
QImage MainWindow::generateQImage(qint32 firstFieldNumber, qint32 secondFieldNumber)
{
    // Generate the QImage for the frame

    // Get the metadata for the video parameters
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Get the raw data for the fields
    QByteArray firstFieldData = sourceVideo.getVideoField(firstFieldNumber)->getFieldData();
    QByteArray secondFieldData = sourceVideo.getVideoField(secondFieldNumber)->getFieldData();

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    qDebug() << "MainWindow::generateQImage(): Generating a QImage with first field =" << firstFieldNumber <<
                "and second field =" << secondFieldNumber << "(" << videoParameters.fieldWidth << "x" <<
                frameHeight << ")";

    // Create a QImage
    QImage frameImage = QImage(videoParameters.fieldWidth, frameHeight, QImage::Format_RGB888);

    // Copy the raw 16-bit grayscale data into the RGB888 QImage
    for (qint32 y = 0; y < frameHeight; y++) {
        // Extract the current scan line data from the frame
        qint32 startPointer = (y / 2) * videoParameters.fieldWidth * 2;
        qint32 length = videoParameters.fieldWidth * 2;

        QByteArray firstLineData = firstFieldData.mid(startPointer, length);
        QByteArray secondLineData = secondFieldData.mid(startPointer, length);

        for (qint32 x = 0; x < videoParameters.fieldWidth; x++) {
            // Take just the MSB of the input data
            qint32 dp = x * 2;
            uchar pixelValue;
            if (y % 2) {
                pixelValue = static_cast<uchar>(firstLineData[dp + 1]);
            } else {
                pixelValue = static_cast<uchar>(secondLineData[dp + 1]);
            }

            qint32 xpp = x * 3;
            *(frameImage.scanLine(y) + xpp + 0) = static_cast<uchar>(pixelValue); // R
            *(frameImage.scanLine(y) + xpp + 1) = static_cast<uchar>(pixelValue); // G
            *(frameImage.scanLine(y) + xpp + 2) = static_cast<uchar>(pixelValue); // B
        }
    }

    return frameImage;
}

// Method to hide the current frame
void MainWindow::hideFrame(void)
{
    ui->frameViewerLabel->clear();
}

void MainWindow::on_actionExit_triggered()
{
    qDebug() << "MainWindow::on_actionExit_triggered(): Called";
        // Quit the application
    qApp->quit();
}

// Load a TBC file based on the passed file name
void MainWindow::loadTbcFile(QString inputFileName)
{
    qInfo() << "Opening TBC filename =" << inputFileName;

    // Open the TBC metadata file
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        // Open failed
        qWarning() << "Open TBC JSON metadata failed for filename" << inputFileName;

        // Show an error to the user
        QMessageBox messageBox;
        messageBox.critical(this, "Error","Could not open TBC JSON metadata file for the TBC input file!");
        messageBox.setFixedSize(500, 200);

        // Update the GUI
        updateGuiUnloaded();
    } else {
        // Opened meta data file, now open TBC source video file
        LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();
        sourceVideo.close();

        if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
            // Open failed
            qWarning() << "Open TBC file failed for filename" << inputFileName;

            // Show an error to the user
            QMessageBox messageBox;
            messageBox.critical(this, "Error","Could not open TBC video file!");
            messageBox.setFixedSize(500, 200);

            // Update the GUI
            updateGuiUnloaded();
        } else {
            // Both the video and metadata files are now open

            if (!videoParameters.isFieldOrderValid) {
                // Show a warning to the user
                QMessageBox messageBox;
                messageBox.warning(this, "Warning","TBC Metadata does not contain a valid field order... Frame rendering may be incorrect!");
                messageBox.setFixedSize(500, 200);
            }

            // Update the status bar
            QString statusText;
            if (videoParameters.isSourcePal) statusText += "PAL";
            else statusText += "NTSC";
            statusText += " source loaded with ";
            statusText += QString::number(getAvailableNumberOfFrames());
            statusText += " sequential frames available";
            sourceVideoStatus.setText(statusText);

            // Update the configuration for the source directory
            QFileInfo inFileInfo(inputFileName);
            configuration->setSourceDirectory(inFileInfo.absolutePath());
            qDebug() << "MainWindow::on_actionOpen_TBC_file_triggered(): Setting source directory to:" << inFileInfo.absolutePath();
            configuration->writeConfiguration();

            // Update the GUI
            updateGuiLoaded();

            // Set the window title
            this->setWindowTitle(tr("ld-analyse - ") + inputFileName);
        }
    }
}

// Load a TBC file based on the file selection from the GUI
void MainWindow::on_actionOpen_TBC_file_triggered()
{
    qDebug() << "MainWindow::on_actionOpen_TBC_file_triggered(): Called";

    QString inputFileName = QFileDialog::getOpenFileName(this,
                tr("Open TBC file"),
                configuration->getSourceDirectory()+tr("/ldsample.tbc"),
                tr("TBC output (*.tbc);;All Files (*)"));

    // Was a filename specified?
    if (!inputFileName.isEmpty() && !inputFileName.isNull()) {
        loadTbcFile(inputFileName);
    }
}

// Previous frame button has been clicked
void MainWindow::on_previousPushButton_clicked()
{
    currentFrameNumber--;
    if (currentFrameNumber < 1) {
        currentFrameNumber = 1;
    } else {
        ui->frameNumberSpinBox->setValue(currentFrameNumber);
        ui->frameHorizontalSlider->setValue(currentFrameNumber);
        showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());
    }
}

// Next frame button has been clicked
void MainWindow::on_nextPushButton_clicked()
{
    currentFrameNumber++;
    if (currentFrameNumber > getAvailableNumberOfFrames()) {
        currentFrameNumber = getAvailableNumberOfFrames();
    } else {
        ui->frameNumberSpinBox->setValue(currentFrameNumber);
        ui->frameHorizontalSlider->setValue(currentFrameNumber);
        showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());
    }
}

// Frame number spin box editing has finished
void MainWindow::on_frameNumberSpinBox_editingFinished()
{
    if (ui->frameNumberSpinBox->value() != currentFrameNumber) {
        if (ui->frameNumberSpinBox->value() < 1) ui->frameNumberSpinBox->setValue(1);
        if (ui->frameNumberSpinBox->value() > sourceVideo.getNumberOfAvailableFields()) ui->frameNumberSpinBox->setValue(getAvailableNumberOfFrames());
        currentFrameNumber = ui->frameNumberSpinBox->value();
        ui->frameHorizontalSlider->setValue(currentFrameNumber);
        showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());
    }
}

// Frame slider value has changed
void MainWindow::on_frameHorizontalSlider_valueChanged(int value)
{
    (void)value;
    qDebug() << "MainWindow::on_frameHorizontalSlider_valueChanged(): Called";

    currentFrameNumber = ui->frameHorizontalSlider->value();

    // If the spinbox is enabled, we can update the current frame number
    // otherwisew we just ignore this
    if (ui->frameNumberSpinBox->isEnabled()) {
        ui->frameNumberSpinBox->setValue(currentFrameNumber);
        showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());
    }
}


void MainWindow::on_showActiveVideoCheckBox_clicked()
{
    showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());
}

void MainWindow::on_highlightDropOutsCheckBox_clicked()
{
    showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());
}

void MainWindow::on_actionLine_scope_triggered()
{
    if (isFileOpen) {
        // Show the oscilloscope dialogue for the selected scan-line
        updateOscilloscopeDialogue(currentFrameNumber, lastScopeLine);
        oscilloscopeDialog->show();
    }
}

void MainWindow::on_actionAbout_ld_analyse_triggered()
{
    aboutDialog->show();
}


void MainWindow::on_actionVBI_triggered()
{
    // Show the VBI dialogue
    vbiDialog->show();
}

void MainWindow::on_actionNTSC_triggered()
{
    // Show the NTSC dialogue
    ntscDialog->show();
}

// Comb Filter button clicked
void MainWindow::on_combFilterPushButton_clicked()
{
    // Get the video parameter metadata
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;
    qint32 firstActiveScanLine = 44;
    qint32 lastActiveScanLine = 617;
    QByteArray outputData;

    // Perform a PAL 2D comb filter on the current frame
    if (videoParameters.isSourcePal) {
        // PAL source

        // Set the first and last active scan line
        firstActiveScanLine = 44;
        lastActiveScanLine = 617;

        // Determine the first and second fields for the frame number
        qint32 firstFieldNumber = getFirstFieldNumber(currentFrameNumber);
        qint32 secondFieldNumber = getSecondFieldNumber(currentFrameNumber);

        // Calculate the saturation level from the burst median IRE
        // Note: This code works as a temporary MTF compensator whilst ld-decode gets
        // real MTF compensation added to it.
        qreal tSaturation = 100.0 + ((100.0 / 20.0) * (20.0 - ldDecodeMetaData.getField(firstFieldNumber).medianBurstIRE));

        // Perform the PALcolour filtering (output is RGB 16-16-16)
        PalColour palColour(videoParameters);
        outputData = palColour.performDecode(sourceVideo.getVideoField(firstFieldNumber)->getFieldData(), sourceVideo.getVideoField(secondFieldNumber)->getFieldData(),
                                              100, static_cast<qint32>(tSaturation));
    } else {
        // NTSC source

        // Set the first and last active scan line
        firstActiveScanLine = 43;
        lastActiveScanLine = 525;

        // Determine the first and second fields for the frame number
        qint32 firstFieldNumber = getFirstFieldNumber(currentFrameNumber);
        qint32 secondFieldNumber = getSecondFieldNumber(currentFrameNumber);

        // Create the comb filter object
        Comb comb;

        // Get the default configuration for the comb filter
        Comb::Configuration configuration = comb.getConfiguration();

        // Set the comb filter configuration
        configuration.filterDepth = 2;
        configuration.blackAndWhite = false;
        configuration.adaptive2d = false;
        configuration.opticalflow = false;

        // Set the input buffer dimensions configuration
        configuration.fieldWidth = videoParameters.fieldWidth;
        configuration.fieldHeight = videoParameters.fieldHeight;

        // Set the active video range
        configuration.activeVideoStart = videoParameters.activeVideoStart;
        configuration.activeVideoEnd = videoParameters.activeVideoEnd;

        // Set the first frame scan line which contains active video
        configuration.firstVisibleFrameLine = firstActiveScanLine;

        // Set the IRE levels
        configuration.blackIre = videoParameters.black16bIre;
        configuration.whiteIre = videoParameters.white16bIre;

        // Update the comb filter object's configuration
        comb.setConfiguration(configuration);

        outputData = comb.process(sourceVideo.getVideoField(firstFieldNumber)->getFieldData(), sourceVideo.getVideoField(secondFieldNumber)->getFieldData(),
                                                        ldDecodeMetaData.getField(firstFieldNumber).medianBurstIRE,
                                                        ldDecodeMetaData.getField(firstFieldNumber).fieldPhaseID,
                                                        ldDecodeMetaData.getField(secondFieldNumber).fieldPhaseID);
    }

    // Create a QImage
    QImage frameImage = QImage(videoParameters.fieldWidth, frameHeight, QImage::Format_RGB888);
    frameImage.fill(Qt::black);

    // Copy the raw 16-bit grayscale data into the RGB888 QImage
    for (qint32 y = firstActiveScanLine; y < lastActiveScanLine; y++) {
        // Extract the current scan line data from the frame
        qint32 startPointer = y * videoParameters.fieldWidth * 6;
        qint32 length = videoParameters.fieldWidth * 6;

        QByteArray rgbData = outputData.mid(startPointer, length);

        for (qint32 x = videoParameters.activeVideoStart; x < videoParameters.activeVideoEnd; x++) {
            // Take just the MSB of the input data
            qint32 dp = x * 6;

            uchar pixelValueR = static_cast<uchar>(rgbData[dp + 1]);
            uchar pixelValueG = static_cast<uchar>(rgbData[dp + 3]);
            uchar pixelValueB = static_cast<uchar>(rgbData[dp + 5]);

            qint32 xpp = x * 3;
            *(frameImage.scanLine(y) + xpp + 0) = static_cast<uchar>(pixelValueR); // R
            *(frameImage.scanLine(y) + xpp + 1) = static_cast<uchar>(pixelValueG); // G
            *(frameImage.scanLine(y) + xpp + 2) = static_cast<uchar>(pixelValueB); // B
        }
    }

    // Add the QImage to the QLabel in the dialogue
    ui->frameViewerLabel->clear();
    ui->frameViewerLabel->setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    ui->frameViewerLabel->setAlignment(Qt::AlignCenter);
    ui->frameViewerLabel->setMinimumSize(frameImage.width(), frameImage.height());
    ui->frameViewerLabel->setMaximumSize(frameImage.width(), frameImage.height());
    ui->frameViewerLabel->setScaledContents(false);
    ui->frameViewerLabel->setPixmap(QPixmap::fromImage(frameImage));
}

// Source button clicked
void MainWindow::on_sourcePushButton_clicked()
{
    // Show the current frame
    showFrame(currentFrameNumber, ui->showActiveVideoCheckBox->isChecked(), ui->highlightDropOutsCheckBox->isChecked());
}

// Mouse press event handler
void MainWindow::mousePressEvent(QMouseEvent *event)
{
    // Get the mouse position relative to our scene
    QPoint origin = ui->frameViewerLabel->mapFromGlobal(QCursor::pos());

    // Get the metadata for the fields
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Check that the mouse click is within bounds of the current picture
    if (origin.x() + 1 >= 0 &&
            origin.y() >= 1 &&
            origin.x() + 1 <= videoParameters.fieldWidth &&
            origin.y() <= frameHeight) {

        qDebug() << "MainWindow::mousePressEvent():" << origin.x() << "x" << origin.y();

        if (isFileOpen) {
            // Show the oscilloscope dialogue for the selected scan-line
            updateOscilloscopeDialogue(currentFrameNumber, origin.y());
            oscilloscopeDialog->show();

            // Remember the last line rendered
            lastScopeLine = origin.y();
        }

        event->accept();
    }
}

void MainWindow::scanLineChangedSignalHandler(qint32 scanLine)
{
    qDebug() << "MainWindow::scanLineChangedSignalHandler(): Called with scanLine =" << scanLine;

    if (isFileOpen) {
        // Show the oscilloscope dialogue for the selected scan-line
        updateOscilloscopeDialogue(currentFrameNumber, scanLine);
        oscilloscopeDialog->show();

        // Remember the last line rendered
        lastScopeLine = scanLine;
    }
}

// Method to update the line oscilloscope based on the frame number and scan line
void MainWindow::updateOscilloscopeDialogue(qint32 frameNumber, qint32 scanLine)
{
    // Get the video parameter metadata
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Determine the first and second fields for the frame number
    qint32 firstFieldNumber = getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = getSecondFieldNumber(frameNumber);

    // Update the oscilloscope dialogue
    oscilloscopeDialog->showTraceImage(sourceVideo.getVideoField(firstFieldNumber)->getFieldData(),
                                       sourceVideo.getVideoField(secondFieldNumber)->getFieldData(),
                                       videoParameters, scanLine);
}


