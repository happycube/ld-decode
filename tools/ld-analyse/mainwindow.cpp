/************************************************************************

    mainwindow.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2022 Simon Inns
    Copyright (C) 2022 Adam Sampson

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

#include "mainwindow.h"
#include "ui_mainwindow.h"

MainWindow::MainWindow(QString inputFilenameParam, QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::MainWindow)
{
    ui->setupUi(this);

    // Set up dialogues
    oscilloscopeDialog = new OscilloscopeDialog(this);
    vectorscopeDialog = new VectorscopeDialog(this);
    aboutDialog = new AboutDialog(this);
    vbiDialog = new VbiDialog(this);
    dropoutAnalysisDialog = new DropoutAnalysisDialog(this);
    visibleDropoutAnalysisDialog = new VisibleDropOutAnalysisDialog(this);
    blackSnrAnalysisDialog = new BlackSnrAnalysisDialog(this);
    whiteSnrAnalysisDialog = new WhiteSnrAnalysisDialog(this);
    busyDialog = new BusyDialog(this);
    closedCaptionDialog = new ClosedCaptionsDialog(this);
    videoParametersDialog = new VideoParametersDialog(this);
    chromaDecoderConfigDialog = new ChromaDecoderConfigDialog(this);

    // Add a status bar to show the state of the source video file
    ui->statusBar->addWidget(&sourceVideoStatus);
    ui->statusBar->addWidget(&fieldNumberStatus);
    ui->statusBar->addWidget(&vbiStatus);
    ui->statusBar->addWidget(&timeCodeStatus);
    sourceVideoStatus.setText(tr("No source video file loaded"));
    fieldNumberStatus.setText(tr(" -  Fields: ./."));
    vbiStatus.hide();
    timeCodeStatus.hide();

    // Set the initial field/frame number
    setCurrentFrame(1);

    // Connect to the scan line changed signal from the oscilloscope dialogue
    connect(oscilloscopeDialog, &OscilloscopeDialog::scopeCoordsChanged, this, &MainWindow::scopeCoordsChangedSignalHandler);
    lastScopeLine = 1;
    lastScopeDot = 1;

    // Make shift-clicking on the oscilloscope change the black/white level
    connect(oscilloscopeDialog, &OscilloscopeDialog::scopeLevelSelect, videoParametersDialog, &VideoParametersDialog::levelSelected);

    // Connect to the changed signal from the vectorscope dialogue
    connect(vectorscopeDialog, &VectorscopeDialog::scopeChanged, this, &MainWindow::vectorscopeChangedSignalHandler);

    // Connect to the video parameters changed signal
    connect(videoParametersDialog, &VideoParametersDialog::videoParametersChanged, this, &MainWindow::videoParametersChangedSignalHandler);

    // Connect to the chroma decoder configuration changed signal
    connect(chromaDecoderConfigDialog, &ChromaDecoderConfigDialog::chromaDecoderConfigChanged, this, &MainWindow::chromaDecoderConfigChangedSignalHandler);

    // Connect to the TbcSource signals (busy and finished loading)
    connect(&tbcSource, &TbcSource::busy, this, &MainWindow::on_busy);
    connect(&tbcSource, &TbcSource::finishedLoading, this, &MainWindow::on_finishedLoading);
    connect(&tbcSource, &TbcSource::finishedSaving, this, &MainWindow::on_finishedSaving);

    // Load the window geometry and settings from the configuration
    restoreGeometry(configuration.getMainWindowGeometry());
    scaleFactor = configuration.getMainWindowScaleFactor();
    vbiDialog->restoreGeometry(configuration.getVbiDialogGeometry());
    oscilloscopeDialog->restoreGeometry(configuration.getOscilloscopeDialogGeometry());
    vectorscopeDialog->restoreGeometry(configuration.getVectorscopeDialogGeometry());
    dropoutAnalysisDialog->restoreGeometry(configuration.getDropoutAnalysisDialogGeometry());
    visibleDropoutAnalysisDialog->restoreGeometry(configuration.getVisibleDropoutAnalysisDialogGeometry());
    blackSnrAnalysisDialog->restoreGeometry(configuration.getBlackSnrAnalysisDialogGeometry());
    whiteSnrAnalysisDialog->restoreGeometry(configuration.getWhiteSnrAnalysisDialogGeometry());
    closedCaptionDialog->restoreGeometry(configuration.getClosedCaptionDialogGeometry());
    videoParametersDialog->restoreGeometry(configuration.getVideoParametersDialogGeometry());
    chromaDecoderConfigDialog->restoreGeometry(configuration.getChromaDecoderConfigDialogGeometry());

    // Store the current button palette for the show dropouts button
    buttonPalette = ui->dropoutsPushButton->palette();

    // Set the GUI to unloaded
    updateGuiUnloaded();

    // Was a filename specified on the command line?
    if (!inputFilenameParam.isEmpty()) {
        lastFilename = inputFilenameParam;
        tbcSource.loadSource(inputFilenameParam);
    } else {
        lastFilename.clear();
    }
}

MainWindow::~MainWindow()
{
    // Save the window geometry and settings to the configuration
    configuration.setMainWindowGeometry(saveGeometry());
    configuration.setMainWindowScaleFactor(scaleFactor);
    configuration.setVbiDialogGeometry(vbiDialog->saveGeometry());
    configuration.setOscilloscopeDialogGeometry(oscilloscopeDialog->saveGeometry());
    configuration.setVectorscopeDialogGeometry(vectorscopeDialog->saveGeometry());
    configuration.setDropoutAnalysisDialogGeometry(dropoutAnalysisDialog->saveGeometry());
    configuration.setVisibleDropoutAnalysisDialogGeometry(visibleDropoutAnalysisDialog->saveGeometry());
    configuration.setBlackSnrAnalysisDialogGeometry(blackSnrAnalysisDialog->saveGeometry());
    configuration.setWhiteSnrAnalysisDialogGeometry(whiteSnrAnalysisDialog->saveGeometry());
    configuration.setClosedCaptionDialogGeometry(closedCaptionDialog->saveGeometry());
    configuration.setVideoParametersDialogGeometry(videoParametersDialog->saveGeometry());
    configuration.setChromaDecoderConfigDialogGeometry(chromaDecoderConfigDialog->saveGeometry());
    configuration.writeConfiguration();

    // Close the source video if open
    if (tbcSource.getIsSourceLoaded()) {
        tbcSource.unloadSource();
    }

    delete ui;
}

// Update GUI methods for when TBC source files are loaded and unloaded -----------------------------------------------

// Enable or disable all the GUI controls
void MainWindow::setGuiEnabled(bool enabled)
{
    // Enable the field/frame controls
    ui->posNumberSpinBox->setEnabled(enabled);
    ui->previousPushButton->setEnabled(enabled);
    ui->nextPushButton->setEnabled(enabled);
    ui->startPushButton->setEnabled(enabled);
    ui->endPushButton->setEnabled(enabled);
    ui->posHorizontalSlider->setEnabled(enabled);
    ui->mediaControl_frame->setEnabled(enabled);

    // Enable menu options
    ui->actionLine_scope->setEnabled(enabled);
    ui->actionVectorscope->setEnabled(enabled);
    ui->actionVBI->setEnabled(enabled);
    ui->actionNTSC->setEnabled(enabled);
    ui->actionVideo_metadata->setEnabled(enabled);
    ui->actionVITS_Metrics->setEnabled(enabled);
    ui->actionZoom_In->setEnabled(enabled);
    ui->actionZoom_Out->setEnabled(enabled);
    ui->actionZoom_1x->setEnabled(enabled);
    ui->actionZoom_2x->setEnabled(enabled);
    ui->actionZoom_3x->setEnabled(enabled);
    ui->actionDropout_analysis->setEnabled(enabled);
    ui->actionVisible_Dropout_analysis->setEnabled(enabled);
    ui->actionSNR_analysis->setEnabled(enabled); // Black SNR
    ui->actionWhite_SNR_analysis->setEnabled(enabled);
    ui->actionSave_frame_as_PNG->setEnabled(enabled);
    ui->actionClosed_Captions->setEnabled(enabled);
    ui->actionVideo_parameters->setEnabled(enabled);
    ui->actionChroma_decoder_configuration->setEnabled(enabled);
    ui->actionReload_TBC->setEnabled(enabled);

    // "Save JSON" should be disabled by default
    ui->actionSave_JSON->setEnabled(false);

    // Set zoom button states
    ui->zoomInPushButton->setEnabled(enabled);
    ui->zoomOutPushButton->setEnabled(enabled);
    ui->originalSizePushButton->setEnabled(enabled);
}

TbcSource& MainWindow::getTbcSource()
{
	return this->tbcSource;
}

void MainWindow::resetGui()
{
    ui->posNumberSpinBox->setMinimum(1);
    ui->posHorizontalSlider->setMinimum(1);

    ui->posNumberSpinBox->setValue(1);
    ui->posHorizontalSlider->setValue(1);
   (this->width() >= 930) ? ui->dropoutsPushButton->setText(tr("Dropouts Off")) : ui->dropoutsPushButton->setText(tr("Drop N"));

    setViewValues();

    // Allow the next and previous frame buttons to auto-repeat
    ui->previousPushButton->setAutoRepeat(true);
    ui->previousPushButton->setAutoRepeatDelay(500);
    ui->previousPushButton->setAutoRepeatInterval(1);
    ui->nextPushButton->setAutoRepeat(true);
    ui->nextPushButton->setAutoRepeatDelay(500);
    ui->nextPushButton->setAutoRepeatInterval(1);

    // Set option button states
    ui->videoPushButton->setText(tr("Source"));
    displayAspectRatio = true;
    updateAspectPushButton();
    updateSourcesPushButton();
    if (this->width() > 1000)
		ui->fieldOrderPushButton->setText(tr("Normal Field-order"));
	else if (this->width() >= 930)
		ui->fieldOrderPushButton->setText(tr("Normal order"));
	else
		ui->fieldOrderPushButton->setText(tr("Normal"));

    // Zoom button options
    ui->zoomInPushButton->setAutoRepeat(true);
    ui->zoomInPushButton->setAutoRepeatDelay(500);
    ui->zoomInPushButton->setAutoRepeatInterval(100);
    ui->zoomOutPushButton->setAutoRepeat(true);
    ui->zoomOutPushButton->setAutoRepeatDelay(500);
    ui->zoomOutPushButton->setAutoRepeatInterval(100);

    ui->stretchFieldButton->setText(tr("2:1"));
    tbcSource.setStretchField(true);

    // Update the video parameters dialogue
    videoParametersDialog->setVideoParameters(tbcSource.getVideoParameters());

    // Update the chroma decoder configuration dialogue
    chromaDecoderConfigDialog->setConfiguration(tbcSource.getSystem(), tbcSource.getPalConfiguration(),
                                                tbcSource.getNtscConfiguration(),
                                                tbcSource.getMonoConfiguration(),
                                                tbcSource.getSourceMode(),
												true,//set to true because the chroma decoder is already init
												tbcSource.getOutputConfiguration());
}

// Method to update the GUI when a file is loaded
void MainWindow::updateGuiLoaded()
{
    // Enable the GUI controls
    setGuiEnabled(true);

    // Update the status bar
    QString statusText;
	if(tbcSource.getVideoParameters().tapeFormat != "") {
		statusText += (tbcSource.getVideoParameters().tapeFormat + " ");
	}
    statusText += tbcSource.getSystemDescription();
    statusText += " source loaded with ";

    if (tbcSource.getFieldViewEnabled()) {
        statusText += QString::number(tbcSource.getNumberOfFields());
        statusText += " fields available";
    } else {
        statusText += QString::number(tbcSource.getNumberOfFrames());
        statusText += " sequential frames available";
    }

    sourceVideoStatus.setText(statusText);

    // Update source mode button
    updateSourcesPushButton();

    // Load and show the current image
    showImage();

    // Update the video parameters dialogue
    videoParametersDialog->setVideoParameters(tbcSource.getVideoParameters());

    // Update the chroma decoder configuration dialogue
        chromaDecoderConfigDialog->setConfiguration(tbcSource.getSystem(), tbcSource.getPalConfiguration(),
                                                tbcSource.getNtscConfiguration(),
                                                tbcSource.getMonoConfiguration(),
                                                tbcSource.getSourceMode(),
												false,//set to false to init the chroma decoder selection
												tbcSource.getOutputConfiguration());

    // Ensure the busy dialogue is hidden
    busyDialog->hide();

    // Disable "Save JSON", now we've loaded the metadata into the GUI
    ui->actionSave_JSON->setEnabled(false);

	//resize the windows to fit the content in full screen
	MainWindow::resize_on_aspect();
}

// Method to update the GUI when a file is unloaded
void MainWindow::updateGuiUnloaded()
{
    // Disable the GUI controls
    setGuiEnabled(false);

    // Update the current field/frame number
    setCurrentFrame(1);
    ui->posNumberSpinBox->setValue(1);
    ui->posHorizontalSlider->setValue(1);

    // Set the window title
    this->setWindowTitle(tr("ld-analyse"));

    // Set the status bar text
    sourceVideoStatus.setText(tr("No source video file loaded"));
    fieldNumberStatus.setText(tr("- Fields: ./."));
    vbiStatus.hide();
    timeCodeStatus.hide();

    // Set option button states
    ui->videoPushButton->setText(tr("Source"));
    (this->width() >= 930) ? ui->dropoutsPushButton->setText(tr("Dropouts Off")) : ui->dropoutsPushButton->setText(tr("Drop N"));
    displayAspectRatio = false;
    updateAspectPushButton();
    updateSourcesPushButton();
    if (this->width() > 1000)
		ui->fieldOrderPushButton->setText(tr("Normal Field-order"));
	else if (this->width() >= 930)
		ui->fieldOrderPushButton->setText(tr("Normal order"));
	else
		ui->fieldOrderPushButton->setText(tr("Normal"));

    // Hide the displayed image
    hideImage();

    // Hide graphs
    blackSnrAnalysisDialog->hide();
    whiteSnrAnalysisDialog->hide();
    dropoutAnalysisDialog->hide();

    // Hide configuration dialogues
    videoParametersDialog->hide();
    chromaDecoderConfigDialog->hide();
}

// Update the aspect ratio button
void MainWindow::updateAspectPushButton()
{
    if (!displayAspectRatio) {
        ui->aspectPushButton->setText(tr("SAR 1:1"));
    } else if (tbcSource.getIsWidescreen()) {
        (this->width() >= 1020) ? ui->aspectPushButton->setText(tr("DAR 16:9")) : ui->aspectPushButton->setText(tr("16:9"));
    } else {
        ui->aspectPushButton->setText(tr("DAR 4:3"));
    }
}

// Update the source selection button
void MainWindow::updateSourcesPushButton()
{
	if (this->width() >= 930)
	{
		switch (tbcSource.getSourceMode()) {
		case TbcSource::ONE_SOURCE:
			ui->sourcesPushButton->setText(tr("One Source"));
			break;
		case TbcSource::LUMA_SOURCE:
			ui->sourcesPushButton->setText(tr("Y Source"));
			break;
		case TbcSource::CHROMA_SOURCE:
			ui->sourcesPushButton->setText(tr("C Source"));
			break;
		case TbcSource::BOTH_SOURCES:
			ui->sourcesPushButton->setText(tr("Y/C Sources"));
			break;
		}
	}
	else
	{
		switch (tbcSource.getSourceMode()) {
		case TbcSource::ONE_SOURCE:
			ui->sourcesPushButton->setText(tr(".TBC"));
			break;
		case TbcSource::LUMA_SOURCE:
			ui->sourcesPushButton->setText(tr("Y"));
			break;
		case TbcSource::CHROMA_SOURCE:
			ui->sourcesPushButton->setText(tr("C"));
			break;
		case TbcSource::BOTH_SOURCES:
			ui->sourcesPushButton->setText(tr("Y/C"));
			break;
		}
	}
	chromaDecoderConfigDialog->updateSourceMode(tbcSource.getSourceMode());
}

// Frame display methods ----------------------------------------------------------------------------------------------

// Update the UI and displays when currentFrameNumber or currentFieldNumber has changed
void MainWindow::showImage()
{
    tbcSource.load(currentFrameNumber, currentFieldNumber);

    // Show the field numbers
    if (tbcSource.getViewMode() == TbcSource::ViewMode::FIELD_VIEW) {
        fieldNumberStatus.setText(QString(" - Field:  %1 (%2/2) - Frame: %3")
                                  .arg(currentFieldNumber)
                                  .arg(currentFieldNumber % 2 ? 1 : 2)
                                  .arg(currentFrameNumber));
    } else {
        fieldNumberStatus.setText(QString(" - Fields: %1/%2")
                                  .arg(tbcSource.getFirstFieldNumber())
                                  .arg(tbcSource.getSecondFieldNumber()));
    }

    // Show VBI position in the status bar, if available
    if (tbcSource.getIsFrameVbiValid()) {
        VbiDecoder::Vbi vbi = tbcSource.getFrameVbi();
        if (vbi.clvHr != -1) {
            vbiStatus.setText(QString(" -  CLV time code: %1:%2:%3")
                                  .arg(vbi.clvHr, 2, 10, QChar('0'))
                                  .arg(vbi.clvMin, 2, 10, QChar('0'))
                                  .arg(vbi.clvSec, 2, 10, QChar('0')));
            vbiStatus.show();
        } else if (vbi.picNo != -1) {
            vbiStatus.setText(QString(" -  CAV picture number: %1")
                                  .arg(vbi.picNo, 5, 10, QChar('0')));
            vbiStatus.show();
        } else {
            vbiStatus.hide();
        }
    } else {
        vbiStatus.hide();
    }

    // Show timecode in the status bar, if available
    if (tbcSource.getIsFrameVitcValid()) {
        // Use ; rather than : if the drop flag is set (as ffmpeg does)
        VitcDecoder::Vitc vitc = tbcSource.getFrameVitc();
        timeCodeStatus.setText(QString(" -  VITC time code: %1:%2:%3%4%5")
                                   .arg(vitc.hour, 2, 10, QChar('0'))
                                   .arg(vitc.minute, 2, 10, QChar('0'))
                                   .arg(vitc.second, 2, 10, QChar('0'))
                                   .arg(vitc.isDropFrame ? QChar(';') : QChar(':'))
                                   .arg(vitc.frame, 2, 10, QChar('0')));
        timeCodeStatus.show();
    } else {
        timeCodeStatus.hide();
    }

    // If there are dropouts in the frame, highlight the show dropouts button
    if (tbcSource.getIsDropoutPresent()) {
        QPalette tempPalette = buttonPalette;
        tempPalette.setColor(QPalette::Button, QColor(Qt::lightGray));
        ui->dropoutsPushButton->setAutoFillBackground(true);
        ui->dropoutsPushButton->setPalette(tempPalette);
        ui->dropoutsPushButton->update();
    } else {
        ui->dropoutsPushButton->setAutoFillBackground(true);
        ui->dropoutsPushButton->setPalette(buttonPalette);
        ui->dropoutsPushButton->update();
    }

    // Update the VBI dialogue
    if (vbiDialog->isVisible()) {
        vbiDialog->updateVbi(tbcSource.getFrameVbi(), tbcSource.getIsFrameVbiValid());
        vbiDialog->updateVideoId(tbcSource.getFrameVideoId(), tbcSource.getIsFrameVideoIdValid());
    }

    // Add the QImage to the QLabel in the dialogue
    ui->imageViewerLabel->clear();
    ui->imageViewerLabel->setScaledContents(false);
    ui->imageViewerLabel->setAlignment(Qt::AlignCenter);

    // Update the field/frame image
    updateImage();

    // Update the closed caption dialog
    closedCaptionDialog->addData(currentFrameNumber, tbcSource.getCcData0(), tbcSource.getCcData1());

    // QT Bug workaround for some macOS versions
    #if defined(Q_OS_MACOS)
    	repaint();
    #endif
}

// Redraw all the GUI elements that depend on the decoded field/frame
void MainWindow::updateImage()
{
    // Update the image viewer
    updateImageViewer();

    // If the scope dialogues are open, update them
    if (oscilloscopeDialog->isVisible()) {
        updateOscilloscopeDialogue();
    }
    if (vectorscopeDialog->isVisible()) {
        updateVectorscopeDialogue();
    }
}

// Return the width adjustment for the current aspect mode
qint32 MainWindow::getAspectAdjustment() {
    // Using source aspect ratio? No adjustment
    if (!displayAspectRatio) return 0;

    if (tbcSource.getSystem() == PAL) {
        // 625 lines
        if (tbcSource.getIsWidescreen()) return 103; // 16:9
        else return -196; // 4:3
    } else {
        // 525 lines
        if (tbcSource.getIsWidescreen()) return 122; // 16:9
        else return -150; // 4:3
    }
}

// Redraw the viewer (for example, when scaleFactor has been changed)
void MainWindow::updateImageViewer()
{
    QImage image = tbcSource.getImage();

    if (ui->mouseModePushButton->isChecked()) {
        // Create a painter object
        QPainter imagePainter;
        imagePainter.begin(&image);

        // Draw lines to indicate the current scope position
        imagePainter.setPen(QColor(0, 255, 0, 127));
        imagePainter.drawLine(0, lastScopeLine - 1, tbcSource.getFrameWidth(), lastScopeLine - 1);
        imagePainter.drawLine(lastScopeDot, 0, lastScopeDot, tbcSource.getFrameHeight());

        // End the painter object
        imagePainter.end();
    }

    QPixmap pixmap = QPixmap::fromImage(image);

    // Get the aspect ratio adjustment if required
    qint32 adjustment = getAspectAdjustment();

    // Scale and apply the pixmap (only if it's valid)
    if (!pixmap.isNull()) {
        const int width = static_cast<int>(scaleFactor * (pixmap.size().width() + adjustment));
        const int height = static_cast<int>(scaleFactor * pixmap.size().height());
        ui->imageViewerLabel->setPixmap(pixmap.scaled(width, height,
                                                      Qt::IgnoreAspectRatio, Qt::SmoothTransformation));
    }

    // Update the current frame markers on the graphs
    blackSnrAnalysisDialog->updateFrameMarker(currentFrameNumber);
    whiteSnrAnalysisDialog->updateFrameMarker(currentFrameNumber);
    dropoutAnalysisDialog->updateFrameMarker(currentFrameNumber);
    visibleDropoutAnalysisDialog->updateFrameMarker(currentFrameNumber);

    // QT Bug workaround for some macOS versions
    #if defined(Q_OS_MACOS)
    	repaint();
    #endif
}

// Method to hide the current image
void MainWindow::hideImage()
{
    ui->imageViewerLabel->clear();
}

// Misc private methods -----------------------------------------------------------------------------------------------

// Load a TBC file based on the passed file name
void MainWindow::loadTbcFile(QString inputFileName)
{
    // Update the GUI
    updateGuiUnloaded();

    // Close current source video (if loaded)
    if (tbcSource.getIsSourceLoaded()) tbcSource.unloadSource();

    // Load the source
    tbcSource.loadSource(inputFileName);

    // Note: loading continues in the background...
}

// Method to update the line oscilloscope based on the frame number and scan line
void MainWindow::updateOscilloscopeDialogue()
{
    // Update the oscilloscope dialogue
    oscilloscopeDialog->showTraceImage(tbcSource.getScanLineData(lastScopeLine),
                                       lastScopeDot, lastScopeLine - 1,
                                       tbcSource.getFrameWidth(), tbcSource.getFrameHeight());
}

// Method to update the vectorscope
void MainWindow::updateVectorscopeDialogue()
{
    // Update the vectorscope dialogue
    vectorscopeDialog->showTraceImage(tbcSource.getComponentFrame(), tbcSource.getVideoParameters(),
                                      tbcSource.getViewMode(), currentFieldNumber % 2);
}

// Method to set the view (field/frame) values
void MainWindow::setViewValues()
{
    qint32 currentNumber, maximum;
    QString buttonLabel, spinLabel;

	if (this->width() >= 930)
	{
		if (tbcSource.getFieldViewEnabled()) {
			currentNumber = currentFieldNumber;
			maximum = tbcSource.getNumberOfFields();
			spinLabel = QString("Field #:");
			buttonLabel = QString("Field View");

			ui->stretchFieldButton->setEnabled(true);
		} else {
			currentNumber = currentFrameNumber;
			maximum = tbcSource.getNumberOfFrames();
			spinLabel = QString("Frame #:");

			ui->stretchFieldButton->setEnabled(false);

			if (tbcSource.getSplitViewEnabled()) {
				buttonLabel = QString("Split View");
			} else {
				buttonLabel = QString("Frame View");
			}
		}
	}
	else
	{
		if (tbcSource.getFieldViewEnabled()) {
			currentNumber = currentFieldNumber;
			maximum = tbcSource.getNumberOfFields();
			spinLabel = QString("Field #:");
			buttonLabel = QString("Field");

			ui->stretchFieldButton->setEnabled(true);
		} else {
			currentNumber = currentFrameNumber;
			maximum = tbcSource.getNumberOfFrames();
			spinLabel = QString("Frame #:");

			ui->stretchFieldButton->setEnabled(false);

			if (tbcSource.getSplitViewEnabled()) {
				buttonLabel = QString("Split");
			} else {
				buttonLabel = QString("Frame");
			}
		}
	}

    ui->posNumberSpinBox->setMaximum(maximum);
    ui->posNumberSpinBox->setValue(currentNumber);
    ui->posHorizontalSlider->setMaximum(maximum);
    ui->posHorizontalSlider->setPageStep(maximum / 100);
    ui->posHorizontalSlider->setValue(currentNumber);

    ui->viewPushButton->setText(buttonLabel);
    ui->posNumberSpinBoxLabel->setText(spinLabel);
    ui->posNumberSpinBoxLabel->repaint();
}

// Set the current frame, field is updated based on frame number
void MainWindow::setCurrentFrame(qint32 number)
{
    if (number == currentFrameNumber) return;

    currentFrameNumber = number;
    currentFieldNumber = (number * 2) - 1;

    sanitizeCurrentPosition();
    showImage();
}

// Set the current field, frame is updated based on field number
void MainWindow::setCurrentField(qint32 number)
{
    if (number == currentFieldNumber) return;

    currentFieldNumber = number;
    currentFrameNumber = std::ceil((double)number / 2);

    sanitizeCurrentPosition();
    showImage();
}

void MainWindow::sanitizeCurrentPosition()
{
    if (currentFrameNumber > tbcSource.getNumberOfFrames() || currentFieldNumber > tbcSource.getNumberOfFields()) {
        currentFrameNumber = tbcSource.getNumberOfFrames();
        currentFieldNumber = tbcSource.getNumberOfFields();
    }

    if (currentFrameNumber == 0)
    {
        currentFrameNumber = 1;
    }

    if (currentFieldNumber == 0) {
        currentFieldNumber = 1;
    }
}

// Menu bar signal handlers -------------------------------------------------------------------------------------------

void MainWindow::on_actionExit_triggered()
{
    qDebug() << "MainWindow::on_actionExit_triggered(): Called";

    // Quit the application
    qApp->quit();
}

// Load a TBC file based on the file selection from the GUI
void MainWindow::on_actionOpen_TBC_file_triggered()
{
    qDebug() << "MainWindow::on_actionOpen_TBC_file_triggered(): Called";

    QString inputFileName = QFileDialog::getOpenFileName(this,
                tr("Open TBC file"),
                configuration.getSourceDirectory()+tr("/ldsample.tbc"),
                tr("TBC output (*.tbc);;All Files (*)"));

    // Was a filename specified?
    if (!inputFileName.isEmpty() && !inputFileName.isNull()) {
        lastFilename = inputFileName;
        loadTbcFile(inputFileName);
    }
}

// Reload the current TBC selection from the GUI
void MainWindow::on_actionReload_TBC_triggered()
{
    // Reload the current TBC file
    if (!lastFilename.isEmpty() && !lastFilename.isNull()) {
        loadTbcFile(lastFilename);
    }
}

// Start saving the modified JSON metadata
void MainWindow::on_actionSave_JSON_triggered()
{
    tbcSource.saveSourceJson();

    // Saving continues in the background...
}

// Display the scan line oscilloscope view
void MainWindow::on_actionLine_scope_triggered()
{
    if (tbcSource.getIsSourceLoaded()) {
        // Show the oscilloscope dialogue for the selected scan-line
        updateOscilloscopeDialogue();
        oscilloscopeDialog->show();
    }
}

// Display the vectorscope view
void MainWindow::on_actionVectorscope_triggered()
{
    if (tbcSource.getIsSourceLoaded()) {
        // Show the vectorscope dialogue
        updateVectorscopeDialogue();
        vectorscopeDialog->show();
    }
}

// Show the about window
void MainWindow::on_actionAbout_ld_analyse_triggered()
{
    aboutDialog->show();
}

// Show the VBI window
void MainWindow::on_actionVBI_triggered()
{
    // Show the VBI dialogue
    vbiDialog->updateVbi(tbcSource.getFrameVbi(), tbcSource.getIsFrameVbiValid());
    vbiDialog->updateVideoId(tbcSource.getFrameVideoId(), tbcSource.getIsFrameVideoIdValid());
    vbiDialog->show();
}

// Show the drop out analysis graph
void MainWindow::on_actionDropout_analysis_triggered()
{
    // Show the dropout analysis dialogue
    dropoutAnalysisDialog->show();
}

// Show the visible drop out analysis graph
void MainWindow::on_actionVisible_Dropout_analysis_triggered()
{
    // Show the visible dropout analysis dialogue
    visibleDropoutAnalysisDialog->show();
}

// Show the Black SNR analysis graph
void MainWindow::on_actionSNR_analysis_triggered()
{
    // Show the black SNR analysis dialogue
    blackSnrAnalysisDialog->show();
}

// Show the White SNR analysis graph
void MainWindow::on_actionWhite_SNR_analysis_triggered()
{
    // Show the white SNR analysis dialogue
    whiteSnrAnalysisDialog->show();
}

// Save current frame as PNG
void MainWindow::on_actionSave_frame_as_PNG_triggered()
{
    qDebug() << "MainWindow::on_actionSave_frame_as_PNG_triggered(): Called";

    // Create a suggestion for the filename
    QString filenameSuggestion = configuration.getPngDirectory();

    switch (tbcSource.getViewMode()) {
        case TbcSource::ViewMode::FRAME_VIEW:
            filenameSuggestion += tr("/frame_");
            break;

        case TbcSource::ViewMode::SPLIT_VIEW:
            filenameSuggestion += tr("/fields_");
            break;

        case TbcSource::ViewMode::FIELD_VIEW:
            filenameSuggestion += tr("/field_");
            break;
    }

    if (tbcSource.getSystem() == PAL) filenameSuggestion += tr("pal_");
    else if (tbcSource.getSystem() == PAL_M) filenameSuggestion += tr("palm_");
    else filenameSuggestion += tr("ntsc_");

    if (!tbcSource.getChromaDecoder()) filenameSuggestion += tr("source_");
    else filenameSuggestion += tr("chroma_");

    if (displayAspectRatio) {
        if (tbcSource.getIsWidescreen()) filenameSuggestion += tr("ar169_");
        else filenameSuggestion += tr("ar43_");
    }

    if (tbcSource.getViewMode() == TbcSource::ViewMode::FIELD_VIEW) {
        filenameSuggestion += QString::number(currentFieldNumber);
    } else {
        filenameSuggestion += QString::number(currentFrameNumber);
    }

    filenameSuggestion += "_" + tbcSource.getCurrentSourceFilename().split("/").last() + tr(".png");

    QString pngFilename = QFileDialog::getSaveFileName(this,
                tr("Save PNG file"),
                filenameSuggestion,
                tr("PNG image (*.png);;All Files (*)"));

    // Was a filename specified?
    if (!pngFilename.isEmpty() && !pngFilename.isNull()) {
        // Save the current frame as a PNG
        qDebug() << "MainWindow::on_actionSave_frame_as_PNG_triggered(): Saving current frame as" << pngFilename;

        // Generate QImage for the current frame
        QImage imageToSave = tbcSource.getImage();

        // Get the aspect ratio adjustment, and scale the image if needed
        qint32 adjustment = getAspectAdjustment();
        if (adjustment != 0) {
            imageToSave = imageToSave.scaled((imageToSave.size().width() + adjustment),
                                             (imageToSave.size().height()),
                                             Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
        }

        // Save the QImage as PNG
        if (!imageToSave.save(pngFilename)) {
            qDebug() << "MainWindow::on_actionSave_frame_as_PNG_triggered(): Failed to save file as" << pngFilename;

            QMessageBox messageBox;
            messageBox.warning(this, "Warning","Could not save a PNG using the specified filename!");
        }

        // Update the configuration for the PNG directory
        QFileInfo pngFileInfo(pngFilename);
        configuration.setPngDirectory(pngFileInfo.absolutePath());
        qDebug() << "MainWindow::on_actionSave_frame_as_PNG_triggered(): Setting PNG directory to:" << pngFileInfo.absolutePath();
        configuration.writeConfiguration();
    }
}

// Zoom in menu option
void MainWindow::on_actionZoom_In_triggered()
{
    on_zoomInPushButton_clicked();
	MainWindow::resize_on_aspect();
}

// Zoom out menu option
void MainWindow::on_actionZoom_Out_triggered()
{
    on_zoomOutPushButton_clicked();
	MainWindow::resize_on_aspect();
}

// Original size 1:1 zoom menu option
void MainWindow::on_actionZoom_1x_triggered()
{
    on_originalSizePushButton_clicked();
	MainWindow::resize_on_aspect();
}

// 2:1 zoom menu option
void MainWindow::on_actionZoom_2x_triggered()
{
    scaleFactor = 2.0;
    updateImageViewer();
	MainWindow::resize_on_aspect();
}

// 3:1 zoom menu option
void MainWindow::on_actionZoom_3x_triggered()
{
    scaleFactor = 3.0;
    updateImageViewer();
	MainWindow::resize_on_aspect();
}

// Show closed captions
void MainWindow::on_actionClosed_Captions_triggered()
{
    closedCaptionDialog->show();
}

// Show video parameters dialogue
void MainWindow::on_actionVideo_parameters_triggered()
{
    videoParametersDialog->show();
}

// Show chroma decoder configuration
void MainWindow::on_actionChroma_decoder_configuration_triggered()
{
    chromaDecoderConfigDialog->show();
}

// Media control frame signal handlers --------------------------------------------------------------------------------

// Previous field/frame button has been clicked
void MainWindow::on_previousPushButton_clicked()
{
    qint32 currentNumber;
    if (tbcSource.getFieldViewEnabled()) {
        setCurrentField(currentFieldNumber - 1);
        currentNumber = currentFieldNumber;
    } else {
        setCurrentFrame(currentFrameNumber - 1);
        currentNumber = currentFrameNumber;
    }

    ui->posNumberSpinBox->setValue(currentNumber);
    ui->posHorizontalSlider->setValue(currentNumber);
}

// Next field/frame button has been clicked
void MainWindow::on_nextPushButton_clicked()
{
    qint32 currentNumber;
    if (tbcSource.getFieldViewEnabled()) {
        setCurrentField(currentFieldNumber + 1);
        currentNumber = currentFieldNumber;
    } else {
        setCurrentFrame(currentFrameNumber + 1);
        currentNumber = currentFrameNumber;
    }

    ui->posNumberSpinBox->setValue(currentNumber);
    ui->posHorizontalSlider->setValue(currentNumber);
}

// Skip to the next chapter (note: this button was repurposed from 'end frame')
void MainWindow::on_endPushButton_clicked()
{
    setCurrentFrame(tbcSource.startOfNextChapter(currentFrameNumber));
    auto uiNumber = currentFrameNumber;

    if (tbcSource.getFieldViewEnabled()) {
        uiNumber = currentFieldNumber;
    }

    ui->posNumberSpinBox->setValue(uiNumber);
    ui->posHorizontalSlider->setValue(uiNumber);
}

// Skip to the start of chapter (note: this button was repurposed from 'start frame')
void MainWindow::on_startPushButton_clicked()
{
    setCurrentFrame(tbcSource.startOfChapter(currentFrameNumber));
    auto uiNumber = currentFrameNumber;

    if (tbcSource.getFieldViewEnabled()) {
        uiNumber = currentFieldNumber;
    }

    ui->posNumberSpinBox->setValue(uiNumber);
    ui->posHorizontalSlider->setValue(uiNumber);
}

// Field/Frame number spin box editing has finished
void MainWindow::on_posNumberSpinBox_editingFinished()
{
    qint32 currentNumber;
    qint32 totalNumber;

    if (tbcSource.getFieldViewEnabled()) {
        currentNumber = currentFieldNumber;
        totalNumber = tbcSource.getNumberOfFields();
    } else {
        currentNumber = currentFrameNumber;
        totalNumber = tbcSource.getNumberOfFrames();
    }

    if (ui->posNumberSpinBox->value() != currentNumber) {
        if (ui->posNumberSpinBox->value() < 1) ui->posNumberSpinBox->setValue(1);
        if (ui->posNumberSpinBox->value() > totalNumber) ui->posNumberSpinBox->setValue(totalNumber);

        if (tbcSource.getFieldViewEnabled()) {
            setCurrentField(ui->posNumberSpinBox->value());
            currentNumber = currentFieldNumber;
        } else {
            setCurrentFrame(ui->posNumberSpinBox->value());
            currentNumber = currentFrameNumber;
        }

        ui->posHorizontalSlider->setValue(currentNumber);
    }
}

// Field/frame slider value has changed
void MainWindow::on_posHorizontalSlider_valueChanged(int value)
{
    if (!tbcSource.getIsSourceLoaded()) return;
    qint32 currentNumber;

    if (tbcSource.getFieldViewEnabled()) {
        setCurrentField(ui->posHorizontalSlider->value());
        currentNumber = currentFieldNumber;
    } else {
        setCurrentFrame(ui->posHorizontalSlider->value());
        currentNumber = currentFrameNumber;
    }

    // If the spinbox is enabled, we can update the current field/frame number
    // otherwise we just ignore this
    if (ui->posNumberSpinBox->isEnabled()) {
        ui->posNumberSpinBox->setValue(currentNumber);
    }
}

// Source/Chroma select button clicked
void MainWindow::on_videoPushButton_clicked()
{
    if (tbcSource.getChromaDecoder()) {
        // Chroma decoder off
        tbcSource.setChromaDecoder(false);
        ui->videoPushButton->setText(tr("Source"));
    } else {
        // Chroma decoder on
        tbcSource.setChromaDecoder(true);
        ui->videoPushButton->setText(tr("Chroma"));
    }

    // Show the current image
    showImage();
}

// Aspect ratio button clicked
void MainWindow::on_aspectPushButton_clicked()
{
    displayAspectRatio = !displayAspectRatio;

    // Update the button text
	updateAspectPushButton();

    // Update the image viewer (the scopes don't depend on this)
    updateImageViewer();

	//resize the windows to fit the new size
	resize_on_aspect();
}

void MainWindow::resize_on_aspect()
{
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
	int width = ui->imageViewerLabel->pixmap().width();
	int height = ui->imageViewerLabel->pixmap().height();
#else
	int width = ui->imageViewerLabel->pixmap()->width();
	int height = ui->imageViewerLabel->pixmap()->height();
#endif

	if(!this->isFullScreen() && !this->isMaximized() && autoResize)
	{
		this->resize(width + 20, height + 140);
	}
}

// Show/hide dropouts button clicked
void MainWindow::on_dropoutsPushButton_clicked()
{
	int width = this->width();

    if (tbcSource.getHighlightDropouts()) {
        tbcSource.setHighlightDropouts(false);
		if (width >= 930)
		{
			ui->dropoutsPushButton->setText(tr("Dropouts Off"));
		}
		else
		{
			ui->dropoutsPushButton->setText(tr("Drop N"));
		}
    } else {
        tbcSource.setHighlightDropouts(true);
        if (width >= 930)
		{
			ui->dropoutsPushButton->setText(tr("Dropouts On"));
		}
		else
		{
			ui->dropoutsPushButton->setText(tr("Drop Y"));
		}
    }

    // Show the current image (why isn't this option passed?)
    showImage();
}

// Source selection button clicked
void MainWindow::on_sourcesPushButton_clicked()
{
    switch (tbcSource.getSourceMode()) {
    case TbcSource::ONE_SOURCE:
        // Do nothing - the button's disabled anyway
        break;
    case TbcSource::LUMA_SOURCE:
        tbcSource.setSourceMode(TbcSource::CHROMA_SOURCE);
        break;
    case TbcSource::CHROMA_SOURCE:
        tbcSource.setSourceMode(TbcSource::BOTH_SOURCES);
        break;
    case TbcSource::BOTH_SOURCES:
        tbcSource.setSourceMode(TbcSource::LUMA_SOURCE);
        break;
    }

    // Update the button
    updateSourcesPushButton();

    // Show the current image
    showImage();
}

// Frame/Field view button clicked
void MainWindow::on_viewPushButton_clicked()
{
    switch (tbcSource.getViewMode()) {
        case TbcSource::ViewMode::FRAME_VIEW:
            qDebug() << "Changing to SPLIT_VIEW mode";

            // Set split mode
            tbcSource.setViewMode(TbcSource::ViewMode::SPLIT_VIEW);
            //ui->fieldOrderPushButton->setEnabled(false);
            break;

        case TbcSource::ViewMode::SPLIT_VIEW:
            qDebug() << "Changing to FIELD_VIEW mode";

            // Set field mode
            tbcSource.setViewMode(TbcSource::ViewMode::FIELD_VIEW);
            //ui->fieldOrderPushButton->setEnabled(false);
            break;

        case TbcSource::ViewMode::FIELD_VIEW:
            qDebug() << "Changing to FRAME_VIEW mode";

            // Set frame mode
            tbcSource.setViewMode(TbcSource::ViewMode::FRAME_VIEW);
            //ui->fieldOrderPushButton->setEnabled(true);
            break;
    }

    setViewValues();
    updateGuiLoaded();

    // Show the current image
    showImage();
}

// Normal/Reverse field order button clicked
void MainWindow::on_fieldOrderPushButton_clicked()
{
	int width = this->width();

    if (tbcSource.getFieldOrder()) {
        tbcSource.setFieldOrder(false);

        // If the TBC field order is changed, the number of available frames can change, so we need to update the GUI
        resetGui();
        updateGuiLoaded();
        if (width > 1000)
			ui->fieldOrderPushButton->setText(tr("Normal Field-order"));
		else if (width >= 930)
			ui->fieldOrderPushButton->setText(tr("Normal order"));
		else
			ui->fieldOrderPushButton->setText(tr("Normal"));
    } else {
        tbcSource.setFieldOrder(true);

        // If the TBC field order is changed, the number of available frames can change, so we need to update the GUI
        resetGui();
        updateGuiLoaded();
        if (width > 1000)
			ui->fieldOrderPushButton->setText(tr("Reverse Field-order"));
		else if (width >= 930)
			ui->fieldOrderPushButton->setText(tr("Reverse order"));
		else
			ui->fieldOrderPushButton->setText(tr("Reverse"));
    }

    // Show the current image
    showImage();
}

void MainWindow::on_toggleAutoResize_toggled(bool checked)
{
	autoResize = checked;
}

// Zoom in
void MainWindow::on_zoomInPushButton_clicked()
{
    constexpr double factor = 1.1;
    if (((scaleFactor * factor) > 0.333) && ((scaleFactor * factor) < 3.0)) {
        scaleFactor *= factor;
    }

    updateImageViewer();
}

// Zoom out
void MainWindow::on_zoomOutPushButton_clicked()
{
    constexpr double factor = 0.9;
    if (((scaleFactor * factor) > 0.333) && ((scaleFactor * factor) < 3.0)) {
        scaleFactor *= factor;
    }

    updateImageViewer();
}

// Original size 1:1 zoom
void MainWindow::on_originalSizePushButton_clicked()
{
    scaleFactor = 1.0;
    updateImageViewer();
}

// Field stretch mode
void MainWindow::on_stretchFieldButton_clicked()
{
    if (tbcSource.getStretchField()) {
        tbcSource.setStretchField(false);
        ui->stretchFieldButton->setText(tr("1:1"));
    } else {
        tbcSource.setStretchField(true);
        ui->stretchFieldButton->setText(tr("2:1"));
    }

    updateImageViewer();
}

// Mouse mode button clicked
void MainWindow::on_mouseModePushButton_clicked()
{
    if (ui->mouseModePushButton->isChecked()) {
        // Show the oscilloscope view if currently hidden
        if (!oscilloscopeDialog->isVisible()) {
            updateOscilloscopeDialogue();
            oscilloscopeDialog->show();
        }
    }

    // Update the image viewer to display/hide the indicator line
    updateImageViewer();
}

// Miscellaneous handler methods --------------------------------------------------------------------------------------

// Handler called when another class changes the currently selected scan line
void MainWindow::scopeCoordsChangedSignalHandler(qint32 xCoord, qint32 yCoord)
{
    qDebug() << "MainWindow::scanLineChangedSignalHandler(): Called with xCoord =" << xCoord << "and yCoord =" << yCoord;

    if (tbcSource.getIsSourceLoaded()) {
        // Show the oscilloscope dialogue for the selected scan-line
        lastScopeDot = xCoord;
        lastScopeLine = yCoord + 1;
        updateOscilloscopeDialogue();
        oscilloscopeDialog->show();

        // Update the image viewer
        updateImageViewer();
    }
}

// Handler called when vectorscope settings are changed
void MainWindow::vectorscopeChangedSignalHandler()
{
    qDebug() << "MainWindow::vectorscopeChangedSignalHandler(): Called";

    if (tbcSource.getIsSourceLoaded()) {
        // Update the vectorscope
        updateVectorscopeDialogue();
    }
}

// Mouse press event handler
void MainWindow::mousePressEvent(QMouseEvent *event)
{
    if (!tbcSource.getIsSourceLoaded()) return;

    // Get the mouse position relative to our scene
    QPoint origin = ui->imageViewerLabel->mapFromGlobal(QCursor::pos());

    // Check that the mouse click is within bounds of the current picture
    qint32 oX = origin.x();
    qint32 oY = origin.y();

    if (oX + 1 >= 0 &&
            oY >= 0 &&
            oX + 1 <= ui->imageViewerLabel->width() &&
            oY <= ui->imageViewerLabel->height()) {

        mouseScanLineSelect(oX, oY);
        event->accept();
    }
}

// Mouse move event
void MainWindow::mouseMoveEvent(QMouseEvent *event)
{
    if (!tbcSource.getIsSourceLoaded()) return;

    // Get the mouse position relative to our scene
    QPoint origin = ui->imageViewerLabel->mapFromGlobal(QCursor::pos());

    // Check that the mouse click is within bounds of the current picture
    qint32 oX = origin.x();
    qint32 oY = origin.y();

    if (oX + 1 >= 0 &&
            oY >= 0 &&
            oX + 1 <= ui->imageViewerLabel->width() &&
            oY <= ui->imageViewerLabel->height()) {

        mouseScanLineSelect(oX, oY);
        event->accept();
    }
}

// Perform mouse based scan line selection
void MainWindow::mouseScanLineSelect(qint32 oX, qint32 oY)
{
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
    QPixmap imageViewerPixmap = ui->imageViewerLabel->pixmap();
#elif QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    QPixmap imageViewerPixmap = ui->imageViewerLabel->pixmap(Qt::ReturnByValue);
#else
    QPixmap imageViewerPixmap = *(ui->imageViewerLabel->pixmap());
#endif

    // X calc
    double offsetX = ((static_cast<double>(ui->imageViewerLabel->width()) -
                       static_cast<double>(imageViewerPixmap.width())) / 2.0);

    double unscaledXR = (static_cast<double>(tbcSource.getFrameWidth()) /
                         static_cast<double>(imageViewerPixmap.width())) * static_cast<double>(oX - offsetX);
    qint32 unscaledX = static_cast<qint32>(unscaledXR);
    if (unscaledX > tbcSource.getFrameWidth() - 1) unscaledX = tbcSource.getFrameWidth() - 1;
    if (unscaledX < 0) unscaledX = 0;

    // Y Calc
    double offsetY = ((static_cast<double>(ui->imageViewerLabel->height()) -
                       static_cast<double>(imageViewerPixmap.height())) / 2.0);

    double unscaledYR = (static_cast<double>(tbcSource.getFrameHeight()) /
                         static_cast<double>(imageViewerPixmap.height())) * static_cast<double>(oY - offsetY);
    qint32 unscaledY = static_cast<qint32>(unscaledYR);
    if (unscaledY > tbcSource.getFrameHeight()) unscaledY = tbcSource.getFrameHeight();
    if (unscaledY < 1) unscaledY = 1;

    // Show the oscilloscope dialogue for the selected scan-line (if the right mouse mode is selected)
    if (ui->mouseModePushButton->isChecked()) {
        // Remember the last line rendered
        lastScopeLine = unscaledY;
        lastScopeDot = unscaledX;

        updateOscilloscopeDialogue();
        oscilloscopeDialog->show();

        // Update the image viewer
        updateImageViewer();
    }
}

// Handle parameters changed signal from the video parameters dialogue
void MainWindow::videoParametersChangedSignalHandler(const LdDecodeMetaData::VideoParameters &videoParameters)
{
    // Update the VideoParameters in the source
    tbcSource.setVideoParameters(videoParameters);

    // Enable the "Save JSON" action, since the metadata has been modified
    ui->actionSave_JSON->setEnabled(true);

    // Update the aspect button's label
    updateAspectPushButton();

    // Update the image viewer
    updateImage();
}

// Handle configuration changed signal from the chroma decoder configuration dialogue
void MainWindow::chromaDecoderConfigChangedSignalHandler()
{
    // Set the new configuration
    tbcSource.setChromaConfiguration(chromaDecoderConfigDialog->getPalConfiguration(),
                                     chromaDecoderConfigDialog->getNtscConfiguration(),
                                     chromaDecoderConfigDialog->getOutputConfiguration());

    // Update the image viewer
    updateImage();
}

// TbcSource class signal handlers ------------------------------------------------------------------------------------

// Signal handler for busy signal from TbcSource class
void MainWindow::on_busy(QString infoMessage)
{
    qDebug() << "MainWindow::on_busy(): Got signal with message" << infoMessage;
    // Set the busy message and centre the dialog in the parent window
    busyDialog->setMessage(infoMessage);
    busyDialog->move(this->geometry().center() - busyDialog->rect().center());

    if (!busyDialog->isVisible()) {
        // Disable the main window during loading
        this->setEnabled(false);
        busyDialog->setEnabled(true);

        busyDialog->show();
    }
}

// Signal handler for finishedLoading signal from TbcSource class
void MainWindow::on_finishedLoading(bool success)
{
    qDebug() << "MainWindow::on_finishedLoading(): Called";

    // Hide the busy dialogue
    busyDialog->hide();

    // Ensure source loaded ok
    if (success) {
        // Generate the graph data
        dropoutAnalysisDialog->startUpdate(tbcSource.getNumberOfFrames());
        visibleDropoutAnalysisDialog->startUpdate(tbcSource.getNumberOfFrames());
        blackSnrAnalysisDialog->startUpdate(tbcSource.getNumberOfFrames());
        whiteSnrAnalysisDialog->startUpdate(tbcSource.getNumberOfFrames());

        QVector<double> doGraphData = tbcSource.getDropOutGraphData();
        QVector<double> visibleDoGraphData = tbcSource.getVisibleDropOutGraphData();
        QVector<double> blackSnrGraphData = tbcSource.getBlackSnrGraphData();
        QVector<double> whiteSnrGraphData = tbcSource.getWhiteSnrGraphData();

        for (qint32 frameNumber = 0; frameNumber < tbcSource.getNumberOfFrames(); frameNumber++) {
            dropoutAnalysisDialog->addDataPoint(frameNumber + 1, doGraphData[frameNumber]);
            visibleDropoutAnalysisDialog->addDataPoint(frameNumber + 1, visibleDoGraphData[frameNumber]);
            blackSnrAnalysisDialog->addDataPoint(frameNumber + 1, blackSnrGraphData[frameNumber]);
            whiteSnrAnalysisDialog->addDataPoint(frameNumber + 1, whiteSnrGraphData[frameNumber]);
        }

        dropoutAnalysisDialog->finishUpdate(currentFrameNumber);
        visibleDropoutAnalysisDialog->finishUpdate(currentFrameNumber);
        blackSnrAnalysisDialog->finishUpdate(currentFrameNumber);
        whiteSnrAnalysisDialog->finishUpdate(currentFrameNumber);

        // Update the GUI
        resetGui();
        updateGuiLoaded();

        // Set the main window title
        this->setWindowTitle(tr("ld-analyse - ") + tbcSource.getCurrentSourceFilename());

        // Update the configuration for the source directory
        QFileInfo inFileInfo(tbcSource.getCurrentSourceFilename());
        configuration.setSourceDirectory(inFileInfo.absolutePath());
        qDebug() << "MainWindow::loadTbcFile(): Setting source directory to:" << inFileInfo.absolutePath();
        configuration.writeConfiguration();
    } else {
        // Load failed
        updateGuiUnloaded();

        // Show the error to the user
        QMessageBox messageBox;
        messageBox.warning(this, "Error", tbcSource.getLastIOError());
    }

    // Enable the main window
    this->setEnabled(true);
}

// Signal handler for finishedSaving signal from TbcSource class
void MainWindow::on_finishedSaving(bool success)
{
    qDebug() << "MainWindow::on_finishedSaving(): Called";

    // Hide the busy dialogue
    busyDialog->hide();

    if (success) {
        // Disable the "Save JSON" action until the metadata is modified again
        ui->actionSave_JSON->setEnabled(false);
    } else {
        // Show the error to the user
        QMessageBox messageBox;
        messageBox.warning(this, "Error", tbcSource.getLastIOError());
    }

    // Enable the main window
    this->setEnabled(true);
}

void MainWindow::resizeEvent(QResizeEvent *event)
{
    QMainWindow::resizeEvent(event);
    int width = this->width();

	//field order rename depending on size
	if (!tbcSource.getFieldOrder())
	{
		if (width > 1000)
			ui->fieldOrderPushButton->setText(tr("Normal Field-order"));
		else if (width >= 930)
			ui->fieldOrderPushButton->setText(tr("Normal order"));
		else
			ui->fieldOrderPushButton->setText(tr("Normal"));
	}
	else
	{
		if (width > 1000)
			ui->fieldOrderPushButton->setText(tr("Reverse Field-order"));
		else if (width >= 930)
			ui->fieldOrderPushButton->setText(tr("Reverse order"));
		else
			ui->fieldOrderPushButton->setText(tr("Reverse"));
	}

	//source label depending on size
	updateSourcesPushButton();

	//dropout label
	if (!tbcSource.getHighlightDropouts())
	{
		if (width >= 930)
		{
			ui->dropoutsPushButton->setText(tr("Dropouts Off"));
		}
		else
		{
			ui->dropoutsPushButton->setText(tr("Drop N"));
		}

	}
	else
	{
		if (width >= 930)
		{
			ui->dropoutsPushButton->setText(tr("Dropouts On"));
		}
		else
		{
			ui->dropoutsPushButton->setText(tr("Drop Y"));
		}
	}

	//view label
	if (this->width() >= 930)
	{
		if (tbcSource.getFieldViewEnabled()) {
			ui->viewPushButton->setText("Field View");

			ui->stretchFieldButton->setEnabled(true);
		} else {
			ui->stretchFieldButton->setEnabled(false);

			if (tbcSource.getSplitViewEnabled()) {
				ui->viewPushButton->setText("Split View");
			} else {
				ui->viewPushButton->setText("Frame View");
			}
		}
	}
	else
	{
		if (tbcSource.getFieldViewEnabled()) {
			ui->viewPushButton->setText("Field");

			ui->stretchFieldButton->setEnabled(true);
		} else {
			ui->stretchFieldButton->setEnabled(false);

			if (tbcSource.getSplitViewEnabled()) {
				ui->viewPushButton->setText("Split");
			} else {
				ui->viewPushButton->setText("Frame");
			}
		}
	}

	//asepec ratio label
	updateAspectPushButton();

}
