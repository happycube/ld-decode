/******************************************************************************
 * mainwindow.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QtDebug>
#include <QStandardPaths>
#include <QDir>
#include <QFileDialog>
#include <QMessageBox>
#include <QLabel>
#include <QMouseEvent>
#include <QTimer>

#include "oscilloscopedialog.h"
#include "vectorscopedialog.h"
#include "aboutdialog.h"
#include "vbidialog.h"
#include "dropoutanalysisdialog.h"
#include "visibledropoutanalysisdialog.h"
#include "blacksnranalysisdialog.h"
#include "whitesnranalysisdialog.h"
#include "busydialog.h"
#include "closedcaptionsdialog.h"
#include "videoparametersdialog.h"
#include "chromadecoderconfigdialog.h"
#include "configuration.h"
#include "tbcsource.h"

namespace Ui {
class MainWindow;
}

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(QString inputFilenameParam, QWidget *parent = nullptr);
	TbcSource& getTbcSource();
    ~MainWindow();

private slots:
    // Menu bar handlers
    void on_actionExit_triggered();
    void on_actionOpen_TBC_file_triggered();
    void on_actionReload_TBC_triggered();
    void on_actionSave_Metadata_triggered();
    void on_actionLine_scope_triggered();
    void on_actionVectorscope_triggered();
    void on_actionAbout_ld_analyse_triggered();
    void on_actionVBI_triggered();
    void on_actionDropout_analysis_triggered();
    void on_actionVisible_Dropout_analysis_triggered();
    void on_actionSNR_analysis_triggered();
    void on_actionWhite_SNR_analysis_triggered();
    void on_actionSave_frame_as_PNG_triggered();
    void on_actionZoom_In_triggered();
    void on_actionZoom_Out_triggered();
    void on_actionZoom_1x_triggered();
    void on_actionZoom_2x_triggered();
    void on_actionZoom_3x_triggered();
    void on_actionClosed_Captions_triggered();
    void on_actionVideo_parameters_triggered();
    void on_actionChroma_decoder_configuration_triggered();
    void on_actionToggleChromaDuringSeek_triggered();

    // Media control frame handlers
    void on_previousPushButton_clicked();
    void on_nextPushButton_clicked();
    void on_previousPushButton_pressed();
    void on_previousPushButton_released();
    void on_nextPushButton_pressed();
    void on_nextPushButton_released();
    void on_endPushButton_clicked();
    void on_startPushButton_clicked();
    void on_posNumberSpinBox_editingFinished();
    void on_posHorizontalSlider_valueChanged(int value);
    void on_posHorizontalSlider_sliderPressed();
    void on_posHorizontalSlider_sliderReleased();
    void on_videoPushButton_clicked();
    void on_aspectPushButton_clicked();
    void on_dropoutsPushButton_clicked();
    void on_sourcesPushButton_clicked();
    void on_viewPushButton_clicked();
    void on_fieldOrderPushButton_clicked();
    void on_zoomInPushButton_clicked();
    void on_zoomOutPushButton_clicked();
    void on_originalSizePushButton_clicked();
    void on_mouseModePushButton_clicked();
    //void on_autoResizeButton_clicked();
	void on_toggleAutoResize_toggled(bool checked);
	void on_actionResizeFrameWithWindow_toggled(bool checked);

    // Miscellaneous handlers
    void scopeCoordsChangedSignalHandler(qint32 xCoord, qint32 yCoord);
    void vectorscopeChangedSignalHandler();
    void onSliderDebounceTimeout();
    void onDragPauseTimeout();
    void mousePressEvent(QMouseEvent *event);
    void mouseMoveEvent(QMouseEvent *event);
    void videoParametersChangedSignalHandler(const LdDecodeMetaData::VideoParameters &videoParameters);
    void chromaDecoderConfigChangedSignalHandler();

    // Tbc Source signal handlers
    void on_busy(QString infoMessage);
    void on_finishedLoading(bool success);
    void on_finishedSaving(bool success);
	
	// UI handler
	void resize_on_aspect();

private:
    Ui::MainWindow *ui;

    // Dialogues
    OscilloscopeDialog* oscilloscopeDialog;
    VectorscopeDialog* vectorscopeDialog;
    AboutDialog* aboutDialog;
    VbiDialog* vbiDialog;
    DropoutAnalysisDialog* dropoutAnalysisDialog;
    VisibleDropOutAnalysisDialog* visibleDropoutAnalysisDialog;
    BlackSnrAnalysisDialog* blackSnrAnalysisDialog;
    WhiteSnrAnalysisDialog* whiteSnrAnalysisDialog;
    BusyDialog* busyDialog;
    ClosedCaptionsDialog *closedCaptionDialog;
    VideoParametersDialog *videoParametersDialog;
    ChromaDecoderConfigDialog *chromaDecoderConfigDialog;

    // Class globals
    Configuration configuration;
    QLabel sourceVideoStatus;
    QLabel fieldNumberStatus;
    QLabel vbiStatus;
    QLabel timeCodeStatus;
    TbcSource tbcSource;
    bool displayAspectRatio;
	bool autoResize = true;
	bool resizeFrameWithWindow = true;
    qint32 lastScopeLine;
    qint32 lastScopeDot;
    qint32 currentFieldNumber, currentFrameNumber;
    double scaleFactor;
    QPalette buttonPalette;
    QString lastFilename;
    
    // Slider debouncing
    QTimer* sliderDebounceTimer;
    QTimer* dragPauseTimer;
    QTimer* resizeTimer;
    qint32 pendingSliderValue;
    bool sliderDragging;
    
    // Chroma toggle during seek
    bool chromaSeekMode;
    bool originalChromaState;
    QTimer* seekTimer;

    // Update GUI methods
    void setGuiEnabled(bool enabled);
    void resetGui();
    void updateGuiLoaded();
    void updateGuiUnloaded();
    void updateAspectPushButton();
    void updateSourcesPushButton();
    void setViewValues();
    void setCurrentFrame(qint32 frame);
    void setCurrentField(qint32 field);
    void sanitizeCurrentPosition();

	// Image display methods
    void showImage();
    void updateImage();
    qint32 getAspectAdjustment();
    void updateImageViewer();
    void hideImage();
    void resizeFrameToWindow();
    void enterChromaSeekMode(QPushButton* button);
    void exitChromaSeekMode(QPushButton* button);

    // TBC source signal handlers
    void loadTbcFile(QString inputFileName);
    void updateOscilloscopeDialogue();
    void updateVectorscopeDialogue();
    void mouseScanLineSelect(qint32 oX, qint32 oY);
	void resizeEvent(QResizeEvent *event);
};

#endif // MAINWINDOW_H
