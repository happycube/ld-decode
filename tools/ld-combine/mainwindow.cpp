/************************************************************************

    mainwindow.cpp

    ld-combine - TBC combination and enhancement tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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
    ui->setupUi(this);

    // Set up dialogues
    aboutDialog = new AboutDialog(this);
    busyDialog = new BusyDialog(this);
    reportDialog = new ReportDialog(this);

    // Connect to the TbcSource signals (busy loading and finished loading)
    connect(&tbcSources, &TbcSources::setBusy, this, &MainWindow::on_setBusy);
    connect(&tbcSources, &TbcSources::clearBusy, this, &MainWindow::on_clearBusy);
    connect(&tbcSources, &TbcSources::updateSources, this, &MainWindow::on_updateSources);

    // Load the window geometry and settings from the configurationMainWindow
    restoreGeometry(configuration.getMainWindowGeometry());

    // Add a status bar to show the state of the source video file
    ui->statusBar->addWidget(&applicationStatus);

    // Set up the GUI
    updateGUInoSourcesAvailable();
}

MainWindow::~MainWindow()
{
    // Save the window geometry and settings to the configuration
    configuration.setMainWindowGeometry(saveGeometry());
    configuration.writeConfiguration();

    delete ui;
}

// GUI update methods -------------------------------------------------------------------------------------------------

// Enable GUI when sources are available
void MainWindow::updateGUIsourcesAvailable()
{
    // Enable the GUI menu options
    ui->actionClose_current_source->setEnabled(true);
    ui->actionReplace_current_source->setEnabled(true);

    // Enable the GUI media controls
    ui->previousFramePushButton->setEnabled(true);
    ui->nextFramePushButton->setEnabled(true);
    ui->keyFrameCheckBox->setEnabled(true);
    ui->keyFrameCheckBox->setChecked(true);
    ui->sourceSelectComboBox->setEnabled(true);
    ui->frameNumberSpinBox->setEnabled(true);
    ui->frameNumberHorizontalSlider->setEnabled(true);

    // Set the spin box to the current frame number
    ui->frameNumberSpinBox->setValue(tbcSources.getCurrentFrameNumber());

    // Enable previous/next buttons to rapidly auto-repeat
    ui->previousFramePushButton->setAutoRepeat(true);
    ui->previousFramePushButton->setAutoRepeatDelay(500);
    ui->previousFramePushButton->setAutoRepeatInterval(1);
    ui->nextFramePushButton->setAutoRepeat(true);
    ui->nextFramePushButton->setAutoRepeatDelay(500);
    ui->nextFramePushButton->setAutoRepeatInterval(1);
}

// Disable GUI when sources are unavailable
void MainWindow::updateGUInoSourcesAvailable()
{
    // Disable the GUI menu options
    ui->actionClose_current_source->setEnabled(false);
    ui->actionReplace_current_source->setEnabled(false);

    // Disable the GUI media controls
    ui->previousFramePushButton->setEnabled(false);
    ui->nextFramePushButton->setEnabled(false);
    ui->keyFrameCheckBox->setEnabled(false);
    ui->keyFrameCheckBox->setChecked(false);
    ui->sourceSelectComboBox->setEnabled(false);
    ui->frameNumberSpinBox->setEnabled(false);
    ui->frameNumberHorizontalSlider->setEnabled(false);

    // Clear the frame viewer
    ui->mediaViewLabel->clear();
    ui->mediaViewLabel->setText("No sources loaded");

    // Set the main window's title
    this->setWindowTitle(tr("ld-combine - No sources loaded"));

    // Set the status bar
    applicationStatus.setText("No source loaded");

    // Clear the source selection combobox
    ui->sourceSelectComboBox->clear();
}

// Update GUI when the source changes
void MainWindow::sourceChanged()
{
    // Block signals during update
    ui->sourceSelectComboBox->blockSignals(true);
    ui->frameNumberSpinBox->blockSignals(true);
    ui->frameNumberHorizontalSlider->blockSignals(true);

    // Set the main window title
    this->setWindowTitle(tr("ld-combine - ") + tbcSources.getCurrentSourceFilename());

    // Set the status bar text
    applicationStatus.setText("Source #" + QString::number(tbcSources.getCurrentSource()) +
                              " with " + QString::number(tbcSources.getNumberOfFrames()) + " frames");

    // Set the frame number spin box
    ui->frameNumberSpinBox->setValue(tbcSources.getCurrentFrameNumber());

    // Set the source selection combo box index
    ui->sourceSelectComboBox->setCurrentIndex(tbcSources.getCurrentSource());

    // Set the horizontal slider bar
    ui->frameNumberHorizontalSlider->setMinimum(1);
    ui->frameNumberHorizontalSlider->setMaximum(tbcSources.getNumberOfFrames());
    ui->frameNumberHorizontalSlider->setValue(tbcSources.getCurrentFrameNumber());

    showFrame();

    // Unblock signals
    ui->sourceSelectComboBox->blockSignals(false);
    ui->frameNumberSpinBox->blockSignals(false);
    ui->frameNumberHorizontalSlider->blockSignals(false);

    qDebug() << "MainWindow::sourceChanged(): Current source now" << tbcSources.getCurrentSource();
}

void MainWindow::updateSourceSelectionCombobox()
{
    // Populate the source selection combobox
    ui->sourceSelectComboBox->blockSignals(true);
    if (tbcSources.getNumberOfAvailableSources() > 0) {
        ui->sourceSelectComboBox->clear();
        QVector<QString> sourceList = tbcSources.getListOfAvailableSources();
        for (qint32 i = 0; i < sourceList.size(); i++) ui->sourceSelectComboBox->addItem(sourceList[i], i);
        ui->sourceSelectComboBox->setCurrentIndex(tbcSources.getCurrentSource());
    } else {
        ui->sourceSelectComboBox->clear();
    }
    ui->sourceSelectComboBox->blockSignals(false);
}

// Show the current source's current frame
void MainWindow::showFrame()
{
    ui->mediaViewLabel->setPixmap(QPixmap::fromImage(tbcSources.getCurrentFrameImage()));
}

// Menu action slots --------------------------------------------------------------------------------------------------

void MainWindow::on_actionOpen_new_source_triggered()
{
    qDebug() << "MainWindow::on_actionOpen_new_source_triggered(): Called";

    QString inputFileName = QFileDialog::getOpenFileName(this,
                tr("Open TBC file"),
                configuration.getSourceDirectory()+tr("/ldsample.tbc"),
                tr("TBC output (*.tbc);;All Files (*)"));

    // If a filename was specified, load the source
    if (!inputFileName.isEmpty() && !inputFileName.isNull()) tbcSources.loadSource(inputFileName);
}

void MainWindow::on_actionClose_current_source_triggered()
{
    QMessageBox::StandardButton reply;
    reply = QMessageBox::question(this, "Close source",
                                  "Are you sure that you want to close the current source?", QMessageBox::Yes|QMessageBox::No);
    if (reply == QMessageBox::Yes) {
        qDebug() << "MainWindow::on_actionClose_current_source_triggered(): Closing current source";
        tbcSources.unloadSource();
        if (tbcSources.getNumberOfAvailableSources() > 0) {
            sourceChanged();
            updateSourceSelectionCombobox();
        } else {
            updateGUInoSourcesAvailable();
            updateSourceSelectionCombobox();
        }
    } else {
        qDebug() << "MainWindow::on_actionClose_current_source_triggered(): User did not confirm close current source";
    }
}

void MainWindow::on_actionExit_triggered()
{
    qDebug() << "MainWindow::on_actionExit_triggered(): Called";

    // Quit the application
    qApp->quit();
}

void MainWindow::on_actionAbout_ld_combine_triggered()
{
    aboutDialog->show();
}

// Main window widget slots -------------------------------------------------------------------------------------------

void MainWindow::on_previousFramePushButton_clicked()
{
    qint32 frameNumber = tbcSources.getCurrentFrameNumber();
    tbcSources.setCurrentFrameNumber(tbcSources.getCurrentFrameNumber() - 1);
    ui->frameNumberSpinBox->blockSignals(true);
    ui->frameNumberHorizontalSlider->blockSignals(true);
    ui->frameNumberSpinBox->setValue(tbcSources.getCurrentFrameNumber());
    ui->frameNumberHorizontalSlider->setValue(tbcSources.getCurrentFrameNumber());
    ui->frameNumberSpinBox->blockSignals(false);
    ui->frameNumberHorizontalSlider->blockSignals(false);
    if (frameNumber != tbcSources.getCurrentFrameNumber()) showFrame();
}

void MainWindow::on_nextFramePushButton_clicked()
{
    qint32 frameNumber = tbcSources.getCurrentFrameNumber();
    tbcSources.setCurrentFrameNumber(frameNumber + 1);
    ui->frameNumberSpinBox->blockSignals(true);
    ui->frameNumberHorizontalSlider->blockSignals(true);
    ui->frameNumberSpinBox->setValue(tbcSources.getCurrentFrameNumber());
    ui->frameNumberHorizontalSlider->setValue(tbcSources.getCurrentFrameNumber());
    ui->frameNumberSpinBox->blockSignals(false);
    ui->frameNumberHorizontalSlider->blockSignals(false);
    if (frameNumber != tbcSources.getCurrentFrameNumber()) showFrame();
}

// User has selected a different source
void MainWindow::on_sourceSelectComboBox_currentIndexChanged(int index)
{
    if (index < 0) return;
    if (index == tbcSources.getCurrentSource()) return;

    qDebug() << "MainWindow::on_sourceSelectComboBox_currentIndexChanged(): Setting current source to" << index;
    tbcSources.setCurrentSource(index);
    sourceChanged();
}

void MainWindow::on_frameNumberSpinBox_valueChanged(int arg1)
{
    qint32 frameNumber = tbcSources.getCurrentFrameNumber();
    tbcSources.setCurrentFrameNumber(arg1);
    ui->frameNumberHorizontalSlider->blockSignals(true);
    ui->frameNumberSpinBox->setValue(tbcSources.getCurrentFrameNumber());
    ui->frameNumberHorizontalSlider->setValue(tbcSources.getCurrentFrameNumber());
    ui->frameNumberHorizontalSlider->blockSignals(false);
    if (frameNumber != tbcSources.getCurrentFrameNumber()) showFrame();
}

void MainWindow::on_frameNumberHorizontalSlider_valueChanged(int value)
{
    qint32 frameNumber = tbcSources.getCurrentFrameNumber();
    tbcSources.setCurrentFrameNumber(value);
    ui->frameNumberSpinBox->blockSignals(true);
    ui->frameNumberSpinBox->setValue(tbcSources.getCurrentFrameNumber());
    ui->frameNumberSpinBox->blockSignals(false);
    if (frameNumber != tbcSources.getCurrentFrameNumber()) showFrame();
}

void MainWindow::on_actionSource_report_triggered()
{
    reportDialog->clearReport();
    reportDialog->showReport(tbcSources.getCurrentMapReport());
    reportDialog->show();
}

// TbcSources class signal handlers -----------------------------------------------------------------------------------

// Signal handler for setBusy signal from TbcSources class
void MainWindow::on_setBusy(QString message, bool showProgress, qint32 progress)
{
    qDebug() << "MainWindow::on_setBusy(): Got signal with message" << message << "show progress" << showProgress << "progress =" << progress;
    // Set the busy message and centre the dialog in the parent window
    busyDialog->setMessage(message);
    busyDialog->setProgress(progress);
    busyDialog->showProgress(showProgress);
    busyDialog->move(this->geometry().center() - busyDialog->rect().center());

    if (!busyDialog->isVisible()) {
        // Disable the main window during loading
        this->setEnabled(false);
        busyDialog->setEnabled(true);
        busyDialog->exec();
    }
}

// Signal handler for clearBusy signal from TbcSources class
void MainWindow::on_clearBusy()
{
    qDebug() << "MainWindow::on_clearBusy(): Called";

    // Hide the busy dialogue and enable the main window
    busyDialog->hide();
    this->setEnabled(true);
}

// Signal handler for updateSources signal from TbcSources class (called after
// a new source is loaded)
void MainWindow::on_updateSources(bool isSuccessful)
{
    // Check for failure
    if (!isSuccessful) {
        qDebug() << "MainWindow::on_updateSources(): Updating source failed - displaying error message";
        QMessageBox messageBox;
                    messageBox.warning(this, "Warning", tbcSources.getLoadingMessage());
                    messageBox.setFixedSize(500, 200);
    } else {
        qDebug() << "MainWindow::on_updateSources(): Updating source successful";
        updateGUIsourcesAvailable();
        sourceChanged();

        // Populate the source selection combobox
        updateSourceSelectionCombobox();

        // Update the configuration for the source directory
        QFileInfo inFileInfo(tbcSources.getCurrentSourceFilename());
        configuration.setSourceDirectory(inFileInfo.absolutePath());
        qDebug() << "MainWindow::on_updateSources(): Setting source directory to:" << inFileInfo.absolutePath();
        configuration.writeConfiguration();
    }
}

