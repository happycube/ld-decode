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

#include "configuration.h"
#include "efmprocess.h"
#include "aboutdialog.h"

namespace Ui {
class MainWindow;
}

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(QWidget *parent = nullptr);
    ~MainWindow();

private slots:
    void percentageProcessedSignalHandler(qint32 percentage);
    void processingCompletedSignalHandler(void);
    void updateStatistics(void);

    void on_actionOpen_EFM_file_triggered();
    void on_actionSave_Audio_As_triggered();
    void on_actionSave_Data_As_triggered();
    void on_actionExit_triggered();
    void on_actionAbout_ld_process_efm_triggered();
    void on_decodePushButton_clicked();
    void on_cancelPushButton_clicked();

private:
    Ui::MainWindow *ui;

    // Dialogues
    AboutDialog *aboutDialog;

    // Class globals
    Configuration *configuration;
    EfmProcess efmProcess;
    QLabel efmStatus;
    QString currentInputFilename;
    QTimer *statisticsUpdateTimer;

    // Temporary files
    QTemporaryFile *audioOutputFile;
    QTemporaryFile *dataOutputFile;

    void noEfmFileLoaded(void);
    void efmFileLoaded(void);
    void decodingStop(void);
    void decodingStart(void);

    void loadEfmFile(QString filename);
    void resetStatistics(void);
};

#endif // MAINWINDOW_H
