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
    ui->decodePushButton->setEnabled(false);
    ui->cancelPushButton->setEnabled(true);
}

// Stop processing the EFM file GUI update
void MainWindow::guiEfmProcessingStop(void)
{
    ui->actionOpen_EFM_File->setEnabled(true);
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

void MainWindow::on_actionExit_triggered()
{
    qDebug() << "MainWindow::on_actionExit_triggered(): Called";

    // Quit the application
    qApp->quit();
}

void MainWindow::on_decodePushButton_clicked()
{
    qDebug() << "MainWindow::on_decodePushButton_clicked(): Called";
    if (currentInputEfmFileAndPath.isEmpty()) return;

    // Update the GUI
    guiEfmProcessingStart();

    efmProcess.startProcessing(currentInputEfmFileAndPath);
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
void MainWindow::processingCompleteSignalHandler(void)
{
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

