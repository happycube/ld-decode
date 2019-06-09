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

MainWindow::MainWindow(QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::MainWindow)
{
    // Initialise the GUI
    ui->setupUi(this);

    // Load the application's configuration
    configuration = new Configuration();

    // Add a status bar to show the state of the source video file
    ui->statusBar->addWidget(&efmStatus);
    efmStatus.setText(tr("No EFM file loaded"));

    // Set up the dialogues

    // Set up the about dialogue
    aboutDialog = new AboutDialog(this);

    // Connect to the signals from the file converter thread
    connect(&efmProcess, &EfmProcess::percentageProcessed, this, &MainWindow::percentageProcessedSignalHandler);
    connect(&efmProcess, &EfmProcess::completed, this, &MainWindow::processingCompletedSignalHandler);

    // Load the window geometry from the configuration
    restoreGeometry(configuration->getMainWindowGeometry());

    // Open temporary files for decoding output
    audioOutputFile = new QTemporaryFile(this);
    dataOutputFile = new QTemporaryFile(this);

    // No EFM file loaded
    noEfmFileLoaded();

    // Set up a timer for updating the statistics
    statisticsUpdateTimer = new QTimer(this);
    connect(statisticsUpdateTimer, SIGNAL(timeout()), this, SLOT(updateStatistics()));
}

MainWindow::~MainWindow()
{
    // Save the window geometry to the configuration
    configuration->setMainWindowGeometry(saveGeometry());

    // Save the configuration
    configuration->writeConfiguration();

    delete ui;
}

// No EFM file loaded GUI update
void MainWindow::noEfmFileLoaded(void)
{
    // Configure GUI elements
    ui->decodePushButton->setEnabled(false);
    ui->cancelPushButton->setEnabled(false);
    ui->decodeProgressBar->setEnabled(false);
    ui->decodeProgressBar->setValue(0);

    // Set the main window title
    this->setWindowTitle(tr("ld-process-efm"));

    // Clear the current input filename
    currentInputFilename.clear();

    // Reset statistics
    resetStatistics();
}

// EFM file loaded GUI update
void MainWindow::efmFileLoaded(void)
{
    // Configure GUI elements
    ui->decodePushButton->setEnabled(true);
    ui->cancelPushButton->setEnabled(false);
    ui->decodeProgressBar->setEnabled(true);
    ui->decodeProgressBar->setValue(0);

    // Set the main window title
    this->setWindowTitle(tr("ld-process-efm - ") + currentInputFilename);

    // Reset statistics
    resetStatistics();
}

// Decoding stopped GUI update
void MainWindow::decodingStop(void)
{
    ui->decodePushButton->setEnabled(true);
    ui->cancelPushButton->setEnabled(false);
    statisticsUpdateTimer->stop();

    updateStatistics();
}

// Decoding started GUI update
void MainWindow::decodingStart(void)
{
    ui->decodePushButton->setEnabled(false);
    ui->cancelPushButton->setEnabled(true);
    ui->decodeProgressBar->setValue(0);

    // Remove any open temporary files
    if (audioOutputFile->isOpen()) {
        qDebug() << "MainWindow::decodingStart(): Removing previous temporary audio output file";
        audioOutputFile->close();
        audioOutputFile->remove();
    }

    if (dataOutputFile->isOpen()) {
        qDebug() << "MainWindow::decodingStart(): Removing previous temporary data output file";
        dataOutputFile->close();
        dataOutputFile->remove();
    }

    // Open the temporary output files
    if (!audioOutputFile->open()) {
        qCritical() << "Unable to open temporary file for audio processing!";
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Could not open a temporary file for audio processing!");
        messageBox.setFixedSize(500, 200);
    }

    if (!dataOutputFile->open()) {
        qCritical() << "Unable to open temporary file for audio processing!";
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Could not open a temporary file for data processing!");
        messageBox.setFixedSize(500, 200);
    }

    // Show the location of the temporary files in debug
    qDebug() << "MainWindow::decodingStart(): Audio output temporary file is" << audioOutputFile->fileName();
    qDebug() << "MainWindow::decodingStart(): Data output temporary file is" << dataOutputFile->fileName();

    // Reset statistics
    resetStatistics();

    efmProcess.startProcessing(currentInputFilename, audioOutputFile, dataOutputFile);
    statisticsUpdateTimer->start(100); // Update 10 times per second
}

// Reset statistics GUI update
void MainWindow::resetStatistics(void)
{
    // Reset statistics and initialise GUI labels
    efmProcess.resetStatistics();

    // F3 Frames tab
    ui->f3Frames_totalLabel->setText(tr("0"));
    ui->f3Frames_validLabel->setText(tr("0"));
    ui->f3Frames_invalidLabel->setText(tr("0"));
    ui->f3Frames_syncLossLabel->setText(tr("0"));

    // F2 Frames tab
    ui->f2Frames_c1_total->setText(tr("0"));
    ui->f2Frames_c1_valid->setText(tr("0"));
    ui->f2Frames_c1_invalid->setText(tr("0"));
    ui->f2Frames_c1_corrected->setText(tr("0"));
    ui->f2Frames_c1_flushes->setText(tr("0"));

    ui->f2Frames_c2_total->setText(tr("0"));
    ui->f2Frames_c2_valid->setText(tr("0"));
    ui->f2Frames_c2_invalid->setText(tr("0"));
    ui->f2Frames_c2_corrected->setText(tr("0"));
    ui->f2Frames_c2_flushes->setText(tr("0"));

    ui->f2Frames_c2de_total->setText(tr("0"));
    ui->f2Frames_c2de_valid->setText(tr("0"));
    ui->f2Frames_c2de_invalid->setText(tr("0"));
    ui->f2Frames_c2de_flushes->setText(tr("0"));

    // Audio tab
    ui->audio_totalSamples->setText(tr("0"));
}

// Miscellaneous methods ----------------------------------------------------------------------------------------------

// Load an EFM file
void MainWindow::loadEfmFile(QString filename)
{
    // Open the EFM input file and verify the contents

    // Open input file for reading
    QFile inputFileHandle((filename));
    if (!inputFileHandle.open(QIODevice::ReadOnly)) {
        // Show an error to the user
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Could not open the EFM input file!");
        messageBox.setFixedSize(500, 200);

        noEfmFileLoaded();
        inputFileHandle.close();
        return;
    }

    if (inputFileHandle.bytesAvailable() == 0) {
        // Show an error to the user
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Input EFM file is empty!");
        messageBox.setFixedSize(500, 200);

        noEfmFileLoaded();
        inputFileHandle.close();
        return;
    }

    // Close the current EFM input file (if any)
    noEfmFileLoaded();

    // Update the configuration for the source directory
    QFileInfo inFileInfo(filename);
    configuration->setSourceDirectory(inFileInfo.absolutePath());
    qDebug() << "MainWindow::on_actionOpen_EFM_file_triggered(): Setting EFM source directory to:" << inFileInfo.absolutePath();
    configuration->writeConfiguration();

    // Update the status bar
    efmStatus.setText(tr("EFM file loaded with ") + QString::number(inputFileHandle.bytesAvailable()) + tr(" T values"));

    // Set the current file name
    currentInputFilename = filename;
    qDebug() << "MainWindow::on_actionOpen_TBC_file_triggered(): Set current file name to to:" << currentInputFilename;

    efmFileLoaded();
    inputFileHandle.close();
}

// Main window menu events --------------------------------------------------------------------------------------------

// Menu -> File -> Open EFM file
void MainWindow::on_actionOpen_EFM_file_triggered()
{
    qDebug() << "MainWindow::on_actionOpen_EFM_file_triggered(): Called";

    QString inputFileName = QFileDialog::getOpenFileName(this,
                tr("Open EFM file"),
                configuration->getSourceDirectory()+tr("/ldsample.efm"),
                tr("EFM output (*.efm);;All Files (*)"));

    // Was a filename specified?
    if (!inputFileName.isEmpty() && !inputFileName.isNull()) {
        // Load the file
        loadEfmFile(inputFileName);
    }
}

// Menu -> File -> Exit
void MainWindow::on_actionExit_triggered()
{
    qDebug() << "MainWindow::on_actionExit_triggered(): Called";

    // Quit the application
    qApp->quit();
}

// Menu -> Help -> About ld-process-efm
void MainWindow::on_actionAbout_ld_process_efm_triggered()
{
    // Show the about dialogue
    aboutDialog->show();
}

// Signal handlers ----------------------------------------------------------------------------------------------------

// Handle the percentage processed signal sent by the file converter thread
void MainWindow::percentageProcessedSignalHandler(qint32 percentage)
{
    // Update the process dialogue
    ui->decodeProgressBar->setValue(percentage);
}

// Handle the conversion completed signal sent by the file converter thread
void MainWindow::processingCompletedSignalHandler(void)
{
    qDebug() << "MainWindow::processingCompletedSignalHandler(): Called";
    decodingStop();
}

// Handle the update statistics timer event
void MainWindow::updateStatistics(void)
{
    // Get the statistical information from the EFM processing thread
    EfmProcess::Statistics statistics = efmProcess.getStatistics();

    // Update F3 Frames tab
    ui->f3Frames_totalLabel->setText(QString::number(statistics.efmToF3Frames_statistics.validFrameLength +
                                                     statistics.efmToF3Frames_statistics.invalidFrameLength));
    ui->f3Frames_validLabel->setText(QString::number(statistics.efmToF3Frames_statistics.validFrameLength));
    ui->f3Frames_invalidLabel->setText(QString::number(statistics.efmToF3Frames_statistics.invalidFrameLength));
    ui->f3Frames_syncLossLabel->setText(QString::number(statistics.efmToF3Frames_statistics.syncLoss));

    // Update F2 Frames tab
    ui->f2Frames_c1_total->setText(QString::number(statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1Passed +
                                                   statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1Failed +
                                                   statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1Corrected));
    ui->f2Frames_c1_valid->setText(QString::number(statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1Passed +
                                                   statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1Corrected));
    ui->f2Frames_c1_invalid->setText(QString::number(statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1Failed));
    ui->f2Frames_c1_corrected->setText(QString::number(statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1Corrected));
    ui->f2Frames_c1_flushes->setText(QString::number(statistics.f3ToF2Frames_statistics.c1Circ_statistics.c1flushed));

    ui->f2Frames_c2_total->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2Passed +
                                                   statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2Failed +
                                                   statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2Corrected));
    ui->f2Frames_c2_valid->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2Passed +
                                                   statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2Corrected));
    ui->f2Frames_c2_invalid->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2Failed));
    ui->f2Frames_c2_corrected->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2Corrected));
    ui->f2Frames_c2_flushes->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Circ_statistics.c2flushed));

    ui->f2Frames_c2de_total->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Deinterleave_statistics.validDeinterleavedC2s +
                                                     statistics.f3ToF2Frames_statistics.c2Deinterleave_statistics.invalidDeinterleavedC2s));
    ui->f2Frames_c2de_valid->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Deinterleave_statistics.validDeinterleavedC2s));
    ui->f2Frames_c2de_invalid->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Deinterleave_statistics.invalidDeinterleavedC2s));
    ui->f2Frames_c2de_flushes->setText(QString::number(statistics.f3ToF2Frames_statistics.c2Deinterleave_statistics.c2flushed));

    // Update audio tab
    ui->audio_totalSamples->setText(QString::number(statistics.f2FramesToAudio_statistics.audioSamples));
}

// Main window general GUI events -------------------------------------------------------------------------------------

// Start decoding push button clicked
void MainWindow::on_decodePushButton_clicked()
{
    qDebug() << "MainWindow::on_decodePushButton_clicked(): Called";
    if (currentInputFilename.isEmpty()) return;

    // Update the GUI
    decodingStart();
}

// Cancel decoding push button clicked
void MainWindow::on_cancelPushButton_clicked()
{
    qDebug() << "MainWindow::on_cancelPushButton_clicked(): Called";

    // Cancel the processing
    efmProcess.cancelProcessing();

    // Update the GUI
    decodingStop();
}
