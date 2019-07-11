/************************************************************************

    mainwindow.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

MainWindow::MainWindow(bool debugOn, bool _nonInteractive, QString _outputAudioFilename, QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::MainWindow)
{
    nonInteractive = _nonInteractive;
    outputAudioFilename = _outputAudioFilename;

    // Initialise the GUI
    ui->setupUi(this);

    // Load the application's configuration
    configuration = new Configuration();

    // Add a status bar to show the state of the source video file
    ui->statusBar->addWidget(&efmStatus);
    efmStatus.setText(tr("No EFM file loaded"));

    // Set up the about dialogue
    aboutDialog = new AboutDialog(this);

    // Connect to the signals from the file decoder thread
    connect(&efmProcess, &EfmProcess::processingComplete, this, &MainWindow::processingCompleteSignalHandler);
    connect(&efmProcess, &EfmProcess::percentProcessed, this, &MainWindow::percentProcessedSignalHandler);

    // Load the window geometry from the configuration
    restoreGeometry(configuration->getMainWindowGeometry());

    // Reset the statistics
    resetStatistics();

    // Reset the decoder options
    resetDecoderOptions();
    if (debugOn) {
        ui->debugEnabled_checkBox->setChecked(true);
        ui->debug_efmToF3_checkBox->setEnabled(true);
        ui->debug_f3Sync_checkBox->setEnabled(true);
        ui->debug_f3ToF2_checkBox->setEnabled(true);
        ui->debug_f2ToAudio_checkBox->setEnabled(true);
        ui->debug_audioSampleFrameToPcm_checkBox->setEnabled(true);
    }

    // Select the Audio tab by default
    ui->tabWidget->setCurrentWidget(ui->audioTab);

    // Set up a timer for updating the statistics
    statisticsUpdateTimer = new QTimer(this);
    connect(statisticsUpdateTimer, SIGNAL(timeout()), this, SLOT(updateStatistics()));

    // Set up GUI for no EFM file loaded
    guiNoEfmFileLoaded();
}

MainWindow::~MainWindow()
{
    // Quit the processing thread
    efmProcess.quit();

    // Save the window geometry to the configuration
    configuration->setMainWindowGeometry(saveGeometry());

    // Save the configuration
    configuration->writeConfiguration();

    delete ui;
}

void MainWindow::startDecodeNonInteractive()
{
    on_decodePushButton_clicked();
}

// GUI update methods -------------------------------------------------------------------------------------------------

// No EFM file loaded GUI update
void MainWindow::guiNoEfmFileLoaded(void)
{
    ui->actionOpen_EFM_File->setEnabled(true);
    ui->actionSave_PCM_Audio->setEnabled(false);
    ui->decodePushButton->setEnabled(false);
    ui->cancelPushButton->setEnabled(false);

    // Set the main window title
    this->setWindowTitle(tr("ld-process-efm"));

    // Clear the input EFM file filename
    currentInputEfmFileAndPath.clear();

    resetStatistics();
}

// EFM file loaded GUI update
void MainWindow::guiEfmFileLoaded(void)
{
    ui->actionOpen_EFM_File->setEnabled(true);
    ui->actionSave_PCM_Audio->setEnabled(false);

    ui->decodePushButton->setEnabled(true);
    ui->cancelPushButton->setEnabled(false);

    // Set the main window title
    QFileInfo fileInfo(currentInputEfmFileAndPath);
    this->setWindowTitle(tr("ld-process-efm - ") + fileInfo.fileName());

    resetStatistics();
}

// Start processing the EFM file GUI update
void MainWindow::guiEfmProcessingStart(void)
{
    resetStatistics();
    statisticsUpdateTimer->start(100); // Update 10 times per second

    ui->actionOpen_EFM_File->setEnabled(false);
    ui->actionSave_PCM_Audio->setEnabled(false);
    ui->decodePushButton->setEnabled(false);
    ui->cancelPushButton->setEnabled(true);

    // Disable changing of options
    ui->options_audio_groupBox->setEnabled(false);
    ui->options_development_groupBox->setEnabled(false);
}

// Stop processing the EFM file GUI update
void MainWindow::guiEfmProcessingStop(void)
{
    statisticsUpdateTimer->stop();
    updateStatistics();

    ui->actionOpen_EFM_File->setEnabled(true);
    // Note: Don't set the save audio here, it's set by the signal handler
    ui->decodePushButton->setEnabled(true);
    ui->cancelPushButton->setEnabled(false);

    // Allow changing of options
    ui->options_audio_groupBox->setEnabled(true);
    ui->options_development_groupBox->setEnabled(true);
}

// Reset statistics
void MainWindow::resetStatistics(void)
{
    // Progress bar
    ui->progressBar->setValue(0);

    TrackTime dummyTime;
    dummyTime.setTime(0, 0, 0);

    // EFM tab
    ui->efm_validSyncs_label->setText(tr("0"));
    ui->efm_overshootSyncs_label->setText(tr("0"));
    ui->efm_undershootSyncs_label->setText(tr("0"));
    ui->efm_totalSyncs_label->setText(tr("0"));

    ui->efm_validTValues_label->setText(tr("0"));
    ui->efm_invalidTValues_label->setText(tr("0"));
    ui->efm_totalTValues_label->setText(tr("0"));

    ui->efm_validFrames_label->setText(tr("0"));
    ui->efm_overshootFrames_label->setText(tr("0"));
    ui->efm_undershootFrames_label->setText(tr("0"));
    ui->efm_totalFrames_label->setText(tr("0"));

    // F3 tab
    ui->f3_totalInputF3Frames_label->setText(tr("0"));
    ui->f3_discardedFrames_label->setText(tr("0"));
    ui->f3_totalValidSections_label->setText(tr("0"));
    ui->f3_totalValidF3Frames_label->setText(tr("0"));

    // F2 tab
    // == F3 to F2
    ui->f2_f3ToF2_totalInputF3Frames_label->setText(tr("0"));
    ui->f2_f3ToF2_totalOutputF2Frames_label->setText(tr("0"));
    ui->f2_f3ToF2_f3SequenceInterruptions_label->setText(tr("0"));
    ui->f2_f3ToF2_missingF3Frames_label->setText(tr("0"));
    ui->f2_f3ToF2_initialDiscTime_label->setText(dummyTime.getTimeAsQString());
    ui->f2_f3ToF2_currentDiscTime_label->setText(dummyTime.getTimeAsQString());

    // == C1
    ui->f2_c1_totalC1sProcessed_label->setText(tr("0"));
    ui->f2_c1_validC1s_label->setText(tr("0"));
    ui->f2_c1_invalidC1s_label->setText(tr("0"));
    ui->f2_c1_c1sCorrected_label->setText(tr("0"));
    ui->f2_c1_delayBufferFlushes_label->setText(tr("0"));
    ui->f2_c1_errorRate_label->setText(tr("0%"));

    // == C2
    ui->f2_c2_totalC2sProcessed_label->setText(tr("0"));
    ui->f2_c2_validC2s_label->setText(tr("0"));
    ui->f2_c2_invalidC2s_label->setText(tr("0"));
    ui->f2_c2_c2sCorrected_label->setText(tr("0"));
    ui->f2_c2_delayBufferFlushes_label->setText(tr("0"));

    // == Deinterleave
    ui->f2_deinterleave_totalC2sProcessed_label->setText(tr("0"));
    ui->f2_deinterleave_validC2s_label->setText(tr("0"));
    ui->f2_deinterleave_invalidC2s_label->setText(tr("0"));
    ui->f2_deinterleave_delayBufferFlushes_label->setText(tr("0"));

    // Audio
    ui->audio_validSamples_label->setText(tr("0"));
    ui->audio_corruptSamples_label->setText(tr("0"));
    ui->audio_missingSectionSamples_label->setText(tr("0"));
    ui->audio_encoderOffSamples_label->setText(tr("0"));
    ui->audio_totalSamples_label->setText(tr("0"));

    ui->audio_sampleStartTime_label->setText(dummyTime.getTimeAsQString());
    ui->audio_sampleCurrentTime_label->setText(dummyTime.getTimeAsQString());
    ui->audio_sampleDuration_label->setText(dummyTime.getTimeAsQString());
    ui->audio_sampleFrameLength_label->setText(tr("0"));
    ui->audio_sampleDurationSeconds_label->setText(tr("0"));
}

// Update statistics
void MainWindow::updateStatistics(void)
{
    // Get the updated statistics
    EfmProcess::Statistics statistics = efmProcess.getStatistics();

    // EFM tab
    ui->efm_validSyncs_label->setText(QString::number(statistics.efmToF3Frames.validSyncs));
    ui->efm_overshootSyncs_label->setText(QString::number(statistics.efmToF3Frames.overshootSyncs));
    ui->efm_undershootSyncs_label->setText(QString::number(statistics.efmToF3Frames.undershootSyncs));
    ui->efm_totalSyncs_label->setText(QString::number(statistics.efmToF3Frames.validSyncs +
                                                      statistics.efmToF3Frames.overshootSyncs + statistics.efmToF3Frames.undershootSyncs));

    ui->efm_validTValues_label->setText(QString::number(statistics.efmToF3Frames.validTValues));
    ui->efm_invalidTValues_label->setText(QString::number(statistics.efmToF3Frames.invalidTValues));
    ui->efm_totalTValues_label->setText(QString::number(statistics.efmToF3Frames.validTValues + statistics.efmToF3Frames.invalidTValues));

    ui->efm_validFrames_label->setText(QString::number(statistics.efmToF3Frames.validFrames));
    ui->efm_overshootFrames_label->setText(QString::number(statistics.efmToF3Frames.overshootFrames));
    ui->efm_undershootFrames_label->setText(QString::number(statistics.efmToF3Frames.undershootFrames));
    ui->efm_totalFrames_label->setText(QString::number(statistics.efmToF3Frames.validFrames + statistics.efmToF3Frames.overshootFrames +
                                                       statistics.efmToF3Frames.undershootFrames));

    // F3 tab
    ui->f3_totalInputF3Frames_label->setText(QString::number(statistics.syncF3Frames.totalF3Frames));
    ui->f3_discardedFrames_label->setText(QString::number(statistics.syncF3Frames.discardedFrames));
    ui->f3_totalValidSections_label->setText(QString::number(statistics.syncF3Frames.totalSections));
    ui->f3_totalValidF3Frames_label->setText(QString::number(statistics.syncF3Frames.totalSections * 98));

    // F2 tab
    // == F3 to F2
    ui->f2_f3ToF2_totalInputF3Frames_label->setText(QString::number(statistics.f3ToF2Frames.totalF3Frames));
    ui->f2_f3ToF2_totalOutputF2Frames_label->setText(QString::number(statistics.f3ToF2Frames.totalF2Frames));
    ui->f2_f3ToF2_f3SequenceInterruptions_label->setText(QString::number(statistics.f3ToF2Frames.sequenceInterruptions));
    ui->f2_f3ToF2_missingF3Frames_label->setText(QString::number(statistics.f3ToF2Frames.missingF3Frames));
    ui->f2_f3ToF2_initialDiscTime_label->setText(statistics.f3ToF2Frames.initialDiscTime.getTimeAsQString());
    ui->f2_f3ToF2_currentDiscTime_label->setText(statistics.f3ToF2Frames.currentDiscTime.getTimeAsQString());

    // == C1
    ui->f2_c1_totalC1sProcessed_label->setText(QString::number(statistics.f3ToF2Frames.c1Circ_statistics.c1Passed +
                                                               statistics.f3ToF2Frames.c1Circ_statistics.c1Failed +
                                                               statistics.f3ToF2Frames.c1Circ_statistics.c1Corrected));
    ui->f2_c1_validC1s_label->setText(QString::number(statistics.f3ToF2Frames.c1Circ_statistics.c1Passed +
                                                      statistics.f3ToF2Frames.c1Circ_statistics.c1Corrected));
    ui->f2_c1_invalidC1s_label->setText(QString::number(statistics.f3ToF2Frames.c1Circ_statistics.c1Failed));
    ui->f2_c1_c1sCorrected_label->setText(QString::number(statistics.f3ToF2Frames.c1Circ_statistics.c1Corrected));
    ui->f2_c1_delayBufferFlushes_label->setText(QString::number(statistics.f3ToF2Frames.c1Circ_statistics.c1flushed));

    qreal c1ErrorRate = static_cast<qreal>(statistics.f3ToF2Frames.c1Circ_statistics.c1Passed) +
            static_cast<qreal>(statistics.f3ToF2Frames.c1Circ_statistics.c1Failed) +
            static_cast<qreal>(statistics.f3ToF2Frames.c1Circ_statistics.c1Corrected);

    c1ErrorRate = (100 / c1ErrorRate) * (statistics.f3ToF2Frames.c1Circ_statistics.c1Failed + statistics.f3ToF2Frames.c1Circ_statistics.c1Corrected);
    ui->f2_c1_errorRate_label->setText(QString::number(c1ErrorRate) + "%");

    // == C2
    ui->f2_c2_totalC2sProcessed_label->setText(QString::number(statistics.f3ToF2Frames.c2Circ_statistics.c2Passed +
                                                               statistics.f3ToF2Frames.c2Circ_statistics.c2Failed +
                                                               statistics.f3ToF2Frames.c2Circ_statistics.c2Corrected));
    ui->f2_c2_validC2s_label->setText(QString::number(statistics.f3ToF2Frames.c2Circ_statistics.c2Passed +
                                                      statistics.f3ToF2Frames.c2Circ_statistics.c2Corrected));
    ui->f2_c2_invalidC2s_label->setText(QString::number(statistics.f3ToF2Frames.c2Circ_statistics.c2Failed));
    ui->f2_c2_c2sCorrected_label->setText(QString::number(statistics.f3ToF2Frames.c2Circ_statistics.c2Corrected));
    ui->f2_c2_delayBufferFlushes_label->setText(QString::number(statistics.f3ToF2Frames.c2Circ_statistics.c2flushed));

    // == Deinterleave
    ui->f2_deinterleave_totalC2sProcessed_label->setText(QString::number(statistics.f3ToF2Frames.c2Deinterleave_statistics.validDeinterleavedC2s +
                                                                         statistics.f3ToF2Frames.c2Deinterleave_statistics.invalidDeinterleavedC2s));
    ui->f2_deinterleave_validC2s_label->setText(QString::number(statistics.f3ToF2Frames.c2Deinterleave_statistics.validDeinterleavedC2s));
    ui->f2_deinterleave_invalidC2s_label->setText(QString::number(statistics.f3ToF2Frames.c2Deinterleave_statistics.invalidDeinterleavedC2s));
    ui->f2_deinterleave_delayBufferFlushes_label->setText(QString::number(statistics.f3ToF2Frames.c2Deinterleave_statistics.c2flushed));

    // Audio
    ui->audio_validSamples_label->setText(QString::number(statistics.f2FramesToAudio.validSamples));
    ui->audio_corruptSamples_label->setText(QString::number(statistics.f2FramesToAudio.corruptSamples));
    ui->audio_missingSectionSamples_label->setText(QString::number(statistics.f2FramesToAudio.missingSectionSamples));
    ui->audio_encoderOffSamples_label->setText(QString::number(statistics.f2FramesToAudio.encoderOffSamples));
    ui->audio_totalSamples_label->setText(QString::number(statistics.f2FramesToAudio.totalSamples));

    ui->audio_sampleStartTime_label->setText(statistics.f2FramesToAudio.sampleStart.getTimeAsQString());
    ui->audio_sampleCurrentTime_label->setText(statistics.f2FramesToAudio.sampleCurrent.getTimeAsQString());

    qint32 sampleFrameLength = statistics.f2FramesToAudio.sampleCurrent.getDifference(statistics.f2FramesToAudio.sampleStart.getTime());
    TrackTime sampleLength;
    sampleLength.setTime(0, 0, 0);
    sampleLength.addFrames(sampleFrameLength);

    ui->audio_sampleDuration_label->setText(sampleLength.getTimeAsQString());
    ui->audio_sampleFrameLength_label->setText(QString::number(sampleFrameLength));
    ui->audio_sampleDurationSeconds_label->setText(QString::number(sampleFrameLength / 75.0));
}

// Reset decoder options
void MainWindow::resetDecoderOptions(void)
{
    ui->debugEnabled_checkBox->setChecked(false);
    ui->debug_efmToF3_checkBox->setChecked(false);
    ui->debug_f3Sync_checkBox->setChecked(false);
    ui->debug_f3ToF2_checkBox->setChecked(false);
    ui->debug_f2ToAudio_checkBox->setChecked(false);
    ui->debug_audioSampleFrameToPcm_checkBox->setChecked(false);

    ui->debug_efmToF3_checkBox->setEnabled(false);
    ui->debug_f3Sync_checkBox->setEnabled(false);
    ui->debug_f3ToF2_checkBox->setEnabled(false);
    ui->debug_f2ToAudio_checkBox->setEnabled(false);
    ui->debug_audioSampleFrameToPcm_checkBox->setEnabled(false);

    ui->audio_conceal_radioButton->setChecked(true);
    ui->audio_silence_radioButton->setChecked(false);
    ui->audio_passthrough_radioButton->setChecked(false);
}

// GUI action slots ---------------------------------------------------------------------------------------------------

void MainWindow::on_actionOpen_EFM_File_triggered()
{
    qDebug() << "MainWindow::on_actionOpen_EFM_file_triggered(): Called";

    QString inputFilename = QFileDialog::getOpenFileName(this,
                tr("Open EFM file"),
                configuration->getSourceDirectory()+tr("/ldsample.efm"),
                tr("EFM output (*.efm);;All Files (*)"));

    // Was a filename specified?
    if (!inputFilename.isEmpty() && !inputFilename.isNull()) {
        // Load the file
        loadInputEfmFile(inputFilename);
    }
}

void MainWindow::on_actionSave_PCM_Audio_triggered()
{
    qDebug() << "MainWindow::on_actionSave_PCM_Audio_triggered(): Called";

    // Create a suggestion for the filename
    QFileInfo fileInfo(currentInputEfmFileAndPath);
    QString filenameSuggestion = configuration->getAudioDirectory() + "/";
    filenameSuggestion += fileInfo.fileName() + tr(".pcm");

    qDebug() << "MainWindow::on_actionSave_PCM_Audio_triggered()L filename suggestion is =" << filenameSuggestion;

    QString audioFilename = QFileDialog::getSaveFileName(this,
                tr("Save PCM file"),
                filenameSuggestion,
                tr("PCM raw audio (*.pcm);;All Files (*)"));

    // Was a filename specified?
    if (!audioFilename.isEmpty() && !audioFilename.isNull()) {
        // Save the audio as PCM
        qDebug() << "MainWindow::on_actionSave_Audio_As_triggered(): Saving audio as" << audioFilename;

        // Check if filename exists (and remove the file if it does)
        if (QFile::exists(audioFilename)) QFile::remove(audioFilename);
        if (QFile::exists(audioFilename + tr(".json"))) QFile::remove(audioFilename + tr(".json"));

        // Copy the audio data from the temporary file to the destination
        if (!audioOutputTemporaryFileHandle.copy(audioFilename)) {
            qDebug() << "MainWindow::on_actionSave_PCM_Audio_triggered(): Failed to save file as" << audioFilename;

            QMessageBox messageBox;
            messageBox.warning(this, "Warning","Could not save PCM audio using the specified filename!");
            messageBox.setFixedSize(500, 200);
        }

        // Update the configuration for the PNG directory
        QFileInfo audioFileInfo(audioFilename);
        configuration->setAudioDirectory(audioFileInfo.absolutePath());
        qDebug() << "MainWindow::on_actionSave_PCM_Audio_triggered(): Setting PCM audio directory to:" << audioFileInfo.absolutePath();
        configuration->writeConfiguration();
    }
}

void MainWindow::on_actionExit_triggered()
{
    qDebug() << "MainWindow::on_actionExit_triggered(): Called";

    // Quit the application
    qApp->quit();
}

void MainWindow::on_actionAbout_ld_process_efm_triggered()
{
    // Show the about dialogue
    aboutDialog->show();
}

void MainWindow::on_decodePushButton_clicked()
{
    qDebug() << "MainWindow::on_decodePushButton_clicked(): Called";
    if (currentInputEfmFileAndPath.isEmpty()) return;

    inputEfmFileHandle.close();
    inputEfmFileHandle.setFileName(currentInputEfmFileAndPath);
    if (!inputEfmFileHandle.open(QIODevice::ReadOnly)) {
        // Failed to open file
        qDebug() << "MainWindow::on_decodePushButton_clicked(): Could not open EFM input file";
        return;
    } else {
        qDebug() << "MainWindow::on_decodePushButton_clicked(): Opened EFM input file";
    }

    // Open temporary file for audio data
    audioOutputTemporaryFileHandle.close();
    if (audioOutputTemporaryFileHandle.exists()) audioOutputTemporaryFileHandle.remove();
    if (!audioOutputTemporaryFileHandle.open()) {
        // Failed to open file
        qFatal("Could not open audio output temporary file - this is fatal!");
    } else {
        qDebug() << "MainWindow::on_decodePushButton_clicked(): Opened audio output temporary file";
    }

    // Open temporary file for data
    dataOutputTemporaryFileHandle.close();
    if (dataOutputTemporaryFileHandle.exists()) dataOutputTemporaryFileHandle.remove();
    if (!dataOutputTemporaryFileHandle.open()) {
        // Failed to open file
        qFatal("Could not open data output temporary file - this is fatal!");
    } else {
        qDebug() << "MainWindow::on_decodePushButton_clicked(): Opened data output temporary file";
    }

    // Update the GUI
    guiEfmProcessingStart();

    // Set the debug states
    efmProcess.setDebug(ui->debug_efmToF3_checkBox->isChecked(), ui->debug_f3Sync_checkBox->isChecked(),
                        ui->debug_f3ToF2_checkBox->isChecked(), ui->debug_f2ToAudio_checkBox->isChecked(),
                        ui->debug_audioSampleFrameToPcm_checkBox->isChecked());

    // Set the audio error treatment option
    if (ui->audio_conceal_radioButton->isChecked()) efmProcess.setAudioErrorTreatment(AudioSampleFramesToPcm::ErrorTreatment::conceal);
    if (ui->audio_silence_radioButton->isChecked()) efmProcess.setAudioErrorTreatment(AudioSampleFramesToPcm::ErrorTreatment::silence);
    if (ui->audio_passthrough_radioButton->isChecked()) efmProcess.setAudioErrorTreatment(AudioSampleFramesToPcm::ErrorTreatment::passThrough);

    // Start the processing of the EFM
    efmProcess.startProcessing(&inputEfmFileHandle, &audioOutputTemporaryFileHandle,
                               &dataOutputTemporaryFileHandle);
}

void MainWindow::on_cancelPushButton_clicked()
{
    qDebug() << "MainWindow::on_cancelPushButton_clicked(): Called";

    efmProcess.stopProcessing();

    // Update the GUI
    guiEfmProcessingStop();
}

void MainWindow::on_debugEnabled_checkBox_clicked()
{
    if (ui->debugEnabled_checkBox->isChecked()) {
        ui->debug_efmToF3_checkBox->setEnabled(true);
        ui->debug_f3Sync_checkBox->setEnabled(true);
        ui->debug_f3ToF2_checkBox->setEnabled(true);
        ui->debug_f2ToAudio_checkBox->setEnabled(true);
        ui->debug_audioSampleFrameToPcm_checkBox->setEnabled(true);
        setDebug(true);
    } else {
        ui->debug_efmToF3_checkBox->setEnabled(false);
        ui->debug_f3Sync_checkBox->setEnabled(false);
        ui->debug_f3ToF2_checkBox->setEnabled(false);
        ui->debug_f2ToAudio_checkBox->setEnabled(false);
        ui->debug_audioSampleFrameToPcm_checkBox->setEnabled(false);
        setDebug(false);
    }
}

// Local signal handling methods --------------------------------------------------------------------------------------

// Handle processingComplete signal from EfmProcess class
void MainWindow::processingCompleteSignalHandler(bool audioAvailable, bool dataAvailable)
{
    if (audioAvailable) {
        qDebug() << "MainWindow::processingCompleteSignalHandler(): Processing complete - audio available";
        ui->actionSave_PCM_Audio->setEnabled(true);

        // If in non-Interactive mode, autosave
        if (nonInteractive) {
            // Save the audio as PCM
            qInfo() << "Saving audio as" << outputAudioFilename;

            // Check if filename exists (and remove the file if it does)
            if (QFile::exists(outputAudioFilename)) QFile::remove(outputAudioFilename);
            if (QFile::exists(outputAudioFilename + tr(".json"))) QFile::remove(outputAudioFilename + tr(".json"));

            // Copy the audio data from the temporary file to the destination
            if (!audioOutputTemporaryFileHandle.copy(outputAudioFilename)) {
                qWarning() << "MainWindow::processingCompleteSignalHandler(): Failed to save file as" << outputAudioFilename;
            }

            // Report the decode statistics
            efmProcess.reportStatistics();

            // Quit the application
            qApp->quit();
        } else efmProcess.reportStatistics();
    }

    if (dataAvailable) qDebug() << "MainWindow::processingCompleteSignalHandler(): Processing complete - data available";

    // Update the GUI
    guiEfmProcessingStop();
}

// Handle percent processed signal from EfmProcess class
void MainWindow::percentProcessedSignalHandler(qint32 percent)
{
    ui->progressBar->setValue(percent);
    if (nonInteractive) qInfo().nospace() << "Processing at " << percent << "%";
}


// Miscellaneous methods ----------------------------------------------------------------------------------------------

// Load an EFM file
bool MainWindow::loadInputEfmFile(QString filename)
{
    // Open the EFM input file and verify the contents

    // Open input file for reading
    QFile inputFileHandle((filename));
    if (!inputFileHandle.open(QIODevice::ReadOnly)) {
        // Show an error to the user
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Could not open the EFM input file!");
        messageBox.setFixedSize(500, 200);
        qWarning() << "Could not load input EFM file!";

        guiNoEfmFileLoaded();
        inputFileHandle.close();
        return false;
    }

    if (inputFileHandle.bytesAvailable() == 0) {
        // Show an error to the user
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Input EFM file is empty!");
        messageBox.setFixedSize(500, 200);
        qWarning() << "EFM input file is empty!";

        guiNoEfmFileLoaded();
        inputFileHandle.close();
        return false;
    }

    // Update the GUI to the no EFM file loaded state
    guiNoEfmFileLoaded();

    // Update the configuration for the source directory
    QFileInfo inFileInfo(filename);
    configuration->setSourceDirectory(inFileInfo.absolutePath());
    qDebug() << "MainWindow::on_actionOpen_EFM_file_triggered(): Setting EFM source directory to:" << inFileInfo.absolutePath();
    configuration->writeConfiguration();

    // Update the status bar
    efmStatus.setText(tr("EFM file loaded with ") + QString::number(inputFileHandle.bytesAvailable()) + tr(" T values"));

    // Set the current file name
    currentInputEfmFileAndPath = filename;
    qDebug() << "MainWindow::on_actionOpen_TBC_file_triggered(): Set current file name to to:" << currentInputEfmFileAndPath;

    if (nonInteractive) qInfo() << "Processing EFM file:" << currentInputEfmFileAndPath;

    guiEfmFileLoaded();
    inputFileHandle.close();

    return true;
}



