/******************************************************************************
 * configuration.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef CONFIGURATION_H
#define CONFIGURATION_H

#include <QObject>
#include <QCoreApplication>
#include <QSettings>
#include <QStandardPaths>
#include <QApplication>
#include <QDir>
#include <QDebug>

class Configuration : public QObject
{
    Q_OBJECT
public:
    explicit Configuration(QObject *parent = nullptr);
    ~Configuration() override;

    void writeConfiguration(void);
    void readConfiguration(void);

    // Get and set methods - Directories
    void setSourceDirectory(QString sourceDirectory);
    QString getSourceDirectory(void);
    void setPngDirectory(QString pngDirectory);
    QString getPngDirectory(void);

    // Get and set methods - windows
    void setMainWindowGeometry(QByteArray mainWindowGeometry);
    QByteArray getMainWindowGeometry(void);
    void setMainWindowScaleFactor(double mainWindowScaleFactor);
    double getMainWindowScaleFactor(void);
    void setVbiDialogGeometry(QByteArray vbiDialogGeometry);
    QByteArray getVbiDialogGeometry(void);
    void setOscilloscopeDialogGeometry(QByteArray oscilloscopeDialogGeometry);
    QByteArray getOscilloscopeDialogGeometry(void);
    void setVectorscopeDialogGeometry(QByteArray vectorscopeDialogGeometry);
    QByteArray getVectorscopeDialogGeometry(void);
    void setDropoutAnalysisDialogGeometry(QByteArray dropoutAnalysisDialogGeometry);
    QByteArray getDropoutAnalysisDialogGeometry(void);
    void setVisibleDropoutAnalysisDialogGeometry(QByteArray visibleDropoutDialogGeometry);
    QByteArray getVisibleDropoutAnalysisDialogGeometry(void);
    void setBlackSnrAnalysisDialogGeometry(QByteArray blackSnrAnalysisDialogGeometry);
    QByteArray getBlackSnrAnalysisDialogGeometry(void);
    void setWhiteSnrAnalysisDialogGeometry(QByteArray whiteSnrAnalysisDialogGeometry);
    QByteArray getWhiteSnrAnalysisDialogGeometry(void);
    void setClosedCaptionDialogGeometry(QByteArray closedCaptionDialogGeometry);
    QByteArray getClosedCaptionDialogGeometry(void);
    void setVideoParametersDialogGeometry(QByteArray videoParametersConfigDialogGeometry);
    QByteArray getVideoParametersDialogGeometry(void);
    void setChromaDecoderConfigDialogGeometry(QByteArray chromaDecoderConfigDialogGeometry);
    QByteArray getChromaDecoderConfigDialogGeometry(void);

    // Get and set methods - view options
    void setToggleChromaDuringSeek(bool toggleChromaDuringSeek);
    bool getToggleChromaDuringSeek(void);
    void setResizeFrameWithWindow(bool resizeFrameWithWindow);
    bool getResizeFrameWithWindow(void);

signals:

public slots:

private:
    QSettings *configuration;

    // Directories
    struct Directories {
        QString sourceDirectory; // Last used directory for .tbc files
        QString pngDirectory; // Last used directory for .png files
    };

    // Window geometry and settings
    struct Windows {
        QByteArray mainWindowGeometry;
        double mainWindowScaleFactor;
        QByteArray vbiDialogGeometry;
        QByteArray oscilloscopeDialogGeometry;
        QByteArray vectorscopeDialogGeometry;
        QByteArray dropoutAnalysisDialogGeometry;
        QByteArray visibleDropoutAnalysisDialogGeometry;
        QByteArray blackSnrAnalysisDialogGeometry;
        QByteArray whiteSnrAnalysisDialogGeometry;
        QByteArray closedCaptionDialogGeometry;
        QByteArray videoParametersDialogGeometry;
        QByteArray chromaDecoderConfigDialogGeometry;
    };

    // View options
    struct ViewOptions {
        bool toggleChromaDuringSeek;
        bool resizeFrameWithWindow;
    };

    // Overall settings structure
    struct Settings {
        qint32 version;
        Directories directories;
        Windows windows;
        ViewOptions viewOptions;
    } settings;

    void setDefault(void);
};

#endif // CONFIGURATION_H
