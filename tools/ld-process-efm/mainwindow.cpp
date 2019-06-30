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

    // Set up the about dialogue
    aboutDialog = new AboutDialog(this);

    // Connect to the signals from the file converter thread
    connect(&efmProcess, &EfmProcess::processingComplete, this, &MainWindow::processingCompleteSignalHandler);

    // Load the window geometry from the configuration
    restoreGeometry(configuration->getMainWindowGeometry());

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
}

// Start processing the EFM file GUI update
void MainWindow::guiEfmProcessingStart(void)
{
    ui->actionOpen_EFM_File->setEnabled(false);
    ui->actionSave_PCM_Audio->setEnabled(false);
    ui->decodePushButton->setEnabled(false);
    ui->cancelPushButton->setEnabled(true);
}

// Stop processing the EFM file GUI update
void MainWindow::guiEfmProcessingStop(void)
{
    ui->actionOpen_EFM_File->setEnabled(true);
    // Don't set the save audio here, it's set by the signal handler
    ui->decodePushButton->setEnabled(true);
    ui->cancelPushButton->setEnabled(false);
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
        if (!audioOutputTemporaryFile.copy(audioFilename)) {
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

    // Open temporary file for audio data
    audioOutputTemporaryFile.close();
    if (!audioOutputTemporaryFile.open()) {
        // Failed to open file
        qFatal("Could not open audio output temporary file - this is fatal!");
    } else {
        qDebug() << "MainWindow::on_decodePushButton_clicked(): Opened audio output temporary file";
    }

    // Update the GUI
    guiEfmProcessingStart();

    efmProcess.startProcessing(currentInputEfmFileAndPath, &audioOutputTemporaryFile);
}

void MainWindow::on_cancelPushButton_clicked()
{
    qDebug() << "MainWindow::on_cancelPushButton_clicked(): Called";

    efmProcess.stopProcessing();

    // Update the GUI
    guiEfmProcessingStop();
}

// Local signal handling methods --------------------------------------------------------------------------------------

// Handle processingComplete signal from EfmProcess class
void MainWindow::processingCompleteSignalHandler(bool audioAvailable, bool dataAvailable)
{
    if (audioAvailable) {
        qDebug() << "MainWindow::processingCompleteSignalHandler(): Processing complete - audio available";
        ui->actionSave_PCM_Audio->setEnabled(true);
    }
    if (dataAvailable) qDebug() << "MainWindow::processingCompleteSignalHandler(): Processing complete - data available";

    // Update the GUI
    guiEfmProcessingStop();
}

// Miscellaneous methods ----------------------------------------------------------------------------------------------

// Load an EFM file
void MainWindow::loadInputEfmFile(QString filename)
{
    // Open the EFM input file and verify the contents

    // Open input file for reading
    QFile inputFileHandle((filename));
    if (!inputFileHandle.open(QIODevice::ReadOnly)) {
        // Show an error to the user
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Could not open the EFM input file!");
        messageBox.setFixedSize(500, 200);

        guiNoEfmFileLoaded();
        inputFileHandle.close();
        return;
    }

    if (inputFileHandle.bytesAvailable() == 0) {
        // Show an error to the user
        QMessageBox messageBox;
        messageBox.critical(this, "Error", "Input EFM file is empty!");
        messageBox.setFixedSize(500, 200);

        guiNoEfmFileLoaded();
        inputFileHandle.close();
        return;
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

    guiEfmFileLoaded();
    inputFileHandle.close();
}

