/************************************************************************

    mainwindow.h

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

#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QFileDialog>
#include <QLabel>
#include <QMessageBox>
#include <QThread>
#include <QTimer>
#include <QTemporaryFile>
#include <QDebug>

#include "logging.h"
#include "configuration.h"
#include "efmprocess.h"
#include "aboutdialog.h"

#include "Decoders/f2tof1frames.h"

namespace Ui {
class MainWindow;
}

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(bool debugOn, bool _nonInteractive,
            QString _outputAudioFilename, QString _outputDataFilename,
            bool pad,
            QWidget *parent = nullptr);
    ~MainWindow();

    bool loadInputEfmFile(QString filename);
    void startDecodeNonInteractive();

private slots:
    void processingCompleteSignalHandler(bool audioAvailable, bool dataAvailable);
    void percentProcessedSignalHandler(qint32 percent);
    void updateStatistics();

    void on_actionOpen_EFM_File_triggered();
    void on_actionExit_triggered();
    void on_decodePushButton_clicked();
    void on_cancelPushButton_clicked();
    void on_actionSave_PCM_Audio_triggered();
    void on_actionAbout_ld_process_efm_triggered();
    void on_debugEnabled_checkBox_clicked();
    void on_options_decodeAsData_checkbox_clicked();
    void on_options_decodeAsAudio_checkbox_clicked();
    void on_actionSave_Sector_Data_triggered();

private:
    void showError(QString message, bool is_critical);

    Ui::MainWindow *ui;

    // Dialogues
    AboutDialog *aboutDialog;

    // Class globals
    Configuration configuration;
    EfmProcess efmProcess;
    QLabel efmStatus;
    QString currentInputEfmFileAndPath;
    QFile inputEfmFileHandle;
    QTemporaryFile audioOutputTemporaryFileHandle;
    QTemporaryFile dataOutputTemporaryFileHandle;
    QTimer statisticsUpdateTimer;
    bool nonInteractive;
    QString outputAudioFilename;
    QString outputDataFilename;
    bool pad;

    // Method prototypes
    void guiNoEfmFileLoaded();
    void guiEfmFileLoaded();
    void guiEfmProcessingStop();
    void guiEfmProcessingStart();

    void resetStatistics();
    void resetDecoderOptions();
};

#endif // MAINWINDOW_H
