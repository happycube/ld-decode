/******************************************************************************
 * configuration.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "configuration.h"
#include "tbc/logging.h"

// This define should be incremented if the settings file format changes
static const qint32 SETTINGSVERSION = 5;

Configuration::Configuration(QObject *parent) : QObject(parent)
{
    // Open the application's configuration file
    QString configurationPath;
    QString configurationFileName;

    configurationPath = QStandardPaths::writableLocation(QStandardPaths::ConfigLocation) ;
    configurationFileName = "ld-analyse.ini" ;
    configuration = new QSettings(configurationPath + "/"+ configurationFileName, QSettings::IniFormat);

    // Read the configuration
    readConfiguration();

    // Are the configuration settings valid?
    if (settings.version != SETTINGSVERSION) {
        tbcDebugStream() << "Configuration::Configuration(): Configuration invalid or wrong version ("
                         << settings.version << "!=" << SETTINGSVERSION << "). Setting to default values";

        // Set default configuration
        setDefault();
    }
}

Configuration::~Configuration()
{
    delete configuration;
}

void Configuration::writeConfiguration(void)
{
    // Write the valid configuration flag
    configuration->setValue("version", settings.version);

    // Directories
    configuration->beginGroup("directories");
    configuration->setValue("sourceDirectory", settings.directories.sourceDirectory);
    configuration->setValue("pngDirectory", settings.directories.pngDirectory);
    configuration->endGroup();

    // Windows
    configuration->beginGroup("windows");
    configuration->setValue("mainWindowGeometry", settings.windows.mainWindowGeometry);
    configuration->setValue("mainWindowScaleFactor", settings.windows.mainWindowScaleFactor);
    configuration->setValue("vbiDialogGeometry", settings.windows.vbiDialogGeometry);
    configuration->setValue("oscilloscopeDialogGeometry", settings.windows.oscilloscopeDialogGeometry);
    configuration->setValue("vectorscopeDialogGeometry", settings.windows.vectorscopeDialogGeometry);
    configuration->setValue("dropoutAnalysisDialogGeometry", settings.windows.dropoutAnalysisDialogGeometry);
    configuration->setValue("visibleDropoutAnalysisDialogGeometry", settings.windows.visibleDropoutAnalysisDialogGeometry);
    configuration->setValue("blackSnrAnalysisDialogGeometry", settings.windows.blackSnrAnalysisDialogGeometry);
    configuration->setValue("whiteSnrAnalysisDialogGeometry", settings.windows.whiteSnrAnalysisDialogGeometry);
    configuration->setValue("closedCaptionDialogGeometry", settings.windows.closedCaptionDialogGeometry);
    configuration->setValue("videoParametersDialogGeometry", settings.windows.videoParametersDialogGeometry);
    configuration->setValue("chromaDecoderConfigDialogGeometry", settings.windows.chromaDecoderConfigDialogGeometry);
    configuration->endGroup();

    // View options
    configuration->beginGroup("viewOptions");
    configuration->setValue("toggleChromaDuringSeek", settings.viewOptions.toggleChromaDuringSeek);
    configuration->setValue("resizeFrameWithWindow", settings.viewOptions.resizeFrameWithWindow);
    configuration->endGroup();

    // Sync the settings with disk
    tbcDebugStream() << "Configuration::writeConfiguration(): Writing configuration to disk";
    configuration->sync();
}

void Configuration::readConfiguration(void)
{
    tbcDebugStream() << "Configuration::readConfiguration(): Reading configuration from" << configuration->fileName();

    // Read the valid configuration flag
    settings.version = configuration->value("version").toInt();

    // Directories
    configuration->beginGroup("directories");
    settings.directories.sourceDirectory = configuration->value("sourceDirectory").toString();
    settings.directories.pngDirectory = configuration->value("pngDirectory").toString();
    configuration->endGroup();

    // Windows
    configuration->beginGroup("windows");
    settings.windows.mainWindowGeometry = configuration->value("mainWindowGeometry").toByteArray();
    settings.windows.mainWindowScaleFactor = configuration->value("mainWindowScaleFactor").toReal();
    settings.windows.vbiDialogGeometry = configuration->value("vbiDialogGeometry").toByteArray();
    settings.windows.oscilloscopeDialogGeometry = configuration->value("oscilloscopeDialogGeometry").toByteArray();
    settings.windows.vectorscopeDialogGeometry = configuration->value("vectorscopeDialogGeometry").toByteArray();
    settings.windows.dropoutAnalysisDialogGeometry = configuration->value("dropoutAnalysisDialogGeometry").toByteArray();
    settings.windows.visibleDropoutAnalysisDialogGeometry = configuration->value("visibleDropoutAnalysisDialogGeometry").toByteArray();
    settings.windows.blackSnrAnalysisDialogGeometry = configuration->value("blackSnrAnalysisDialogGeometry").toByteArray();
    settings.windows.whiteSnrAnalysisDialogGeometry = configuration->value("whiteSnrAnalysisDialogGeometry").toByteArray();
    settings.windows.closedCaptionDialogGeometry = configuration->value("closedCaptionDialogGeometry").toByteArray();
    settings.windows.videoParametersDialogGeometry = configuration->value("videoParametersDialogGeometry").toByteArray();
    settings.windows.chromaDecoderConfigDialogGeometry = configuration->value("chromaDecoderConfigDialogGeometry").toByteArray();
    configuration->endGroup();

    // View options
    configuration->beginGroup("viewOptions");
    settings.viewOptions.toggleChromaDuringSeek = configuration->value("toggleChromaDuringSeek", false).toBool();
    settings.viewOptions.resizeFrameWithWindow = configuration->value("resizeFrameWithWindow", true).toBool();
    configuration->endGroup();
}

void Configuration::setDefault(void)
{
    // Set up the default values
    settings.version = SETTINGSVERSION;

    // Directories
    settings.directories.sourceDirectory = QDir::homePath();
    settings.directories.pngDirectory = QDir::homePath();

    // Windows
    settings.windows.mainWindowGeometry = QByteArray();
    settings.windows.mainWindowScaleFactor = 1.0;
    settings.windows.vbiDialogGeometry = QByteArray();
    settings.windows.oscilloscopeDialogGeometry = QByteArray();
    settings.windows.vectorscopeDialogGeometry = QByteArray();
    settings.windows.dropoutAnalysisDialogGeometry = QByteArray();
    settings.windows.visibleDropoutAnalysisDialogGeometry = QByteArray();
    settings.windows.blackSnrAnalysisDialogGeometry = QByteArray();
    settings.windows.whiteSnrAnalysisDialogGeometry = QByteArray();
    settings.windows.closedCaptionDialogGeometry = QByteArray();
    settings.windows.videoParametersDialogGeometry = QByteArray();
    settings.windows.chromaDecoderConfigDialogGeometry = QByteArray();

    // View options
    settings.viewOptions.toggleChromaDuringSeek = false;
    settings.viewOptions.resizeFrameWithWindow = true;

    // Write the configuration
    writeConfiguration();
}

// Functions to get and set configuration values ----------------------------------------------------------------------

// Directories
void Configuration::setSourceDirectory(QString sourceDirectory)
{
    settings.directories.sourceDirectory = sourceDirectory;
}

QString Configuration::getSourceDirectory(void)
{
    return settings.directories.sourceDirectory;
}

void Configuration::setPngDirectory(QString pngDirectory)
{
    settings.directories.pngDirectory = pngDirectory;
}

QString Configuration::getPngDirectory(void)
{
    return settings.directories.pngDirectory;
}

// Windows
void Configuration::setMainWindowGeometry(QByteArray mainWindowGeometry)
{
    settings.windows.mainWindowGeometry = mainWindowGeometry;
}

QByteArray Configuration::getMainWindowGeometry(void)
{
    return settings.windows.mainWindowGeometry;
}

void Configuration::setMainWindowScaleFactor(double mainWindowScaleFactor)
{
    settings.windows.mainWindowScaleFactor = mainWindowScaleFactor;
}

double Configuration::getMainWindowScaleFactor(void)
{
    return settings.windows.mainWindowScaleFactor;
}

void Configuration::setVbiDialogGeometry(QByteArray vbiDialogGeometry)
{
    settings.windows.vbiDialogGeometry = vbiDialogGeometry;
}

QByteArray Configuration::getVbiDialogGeometry(void)
{
    return settings.windows.vbiDialogGeometry;
}

void Configuration::setOscilloscopeDialogGeometry(QByteArray oscilloscopeDialogGeometry)
{
    settings.windows.oscilloscopeDialogGeometry = oscilloscopeDialogGeometry;
}

QByteArray Configuration::getOscilloscopeDialogGeometry(void)
{
    return settings.windows.oscilloscopeDialogGeometry;
}

void Configuration::setVectorscopeDialogGeometry(QByteArray vectorscopeDialogGeometry)
{
    settings.windows.vectorscopeDialogGeometry = vectorscopeDialogGeometry;
}

QByteArray Configuration::getVectorscopeDialogGeometry(void)
{
    return settings.windows.vectorscopeDialogGeometry;
}

void Configuration::setDropoutAnalysisDialogGeometry(QByteArray dropoutAnalysisDialogGeometry)
{
    settings.windows.dropoutAnalysisDialogGeometry = dropoutAnalysisDialogGeometry;
}

QByteArray Configuration::getDropoutAnalysisDialogGeometry(void)
{
    return settings.windows.dropoutAnalysisDialogGeometry;
}

void Configuration::setVisibleDropoutAnalysisDialogGeometry(QByteArray visibleDropoutAnalysisDialogGeometry)
{
    settings.windows.visibleDropoutAnalysisDialogGeometry = visibleDropoutAnalysisDialogGeometry;
}

QByteArray Configuration::getVisibleDropoutAnalysisDialogGeometry(void)
{
    return settings.windows.visibleDropoutAnalysisDialogGeometry;
}

void Configuration::setBlackSnrAnalysisDialogGeometry(QByteArray blackSnrAnalysisDialogGeometry)
{
    settings.windows.blackSnrAnalysisDialogGeometry = blackSnrAnalysisDialogGeometry;
}

QByteArray Configuration::getBlackSnrAnalysisDialogGeometry(void)
{
    return settings.windows.blackSnrAnalysisDialogGeometry;
}

void Configuration::setWhiteSnrAnalysisDialogGeometry(QByteArray whiteSnrAnalysisDialogGeometry)
{
    settings.windows.whiteSnrAnalysisDialogGeometry = whiteSnrAnalysisDialogGeometry;
}

QByteArray Configuration::getWhiteSnrAnalysisDialogGeometry(void)
{
    return settings.windows.whiteSnrAnalysisDialogGeometry;
}

void Configuration::setClosedCaptionDialogGeometry(QByteArray closedCaptionDialogGeometry)
{
    settings.windows.closedCaptionDialogGeometry = closedCaptionDialogGeometry;
}

QByteArray Configuration::getClosedCaptionDialogGeometry(void)
{
    return settings.windows.closedCaptionDialogGeometry;
}

void Configuration::setVideoParametersDialogGeometry(QByteArray videoParametersDialogGeometry)
{
    settings.windows.videoParametersDialogGeometry = videoParametersDialogGeometry;
}

QByteArray Configuration::getVideoParametersDialogGeometry(void)
{
    return settings.windows.videoParametersDialogGeometry;
}

void Configuration::setChromaDecoderConfigDialogGeometry(QByteArray chromaDecoderConfigDialogGeometry)
{
    settings.windows.chromaDecoderConfigDialogGeometry = chromaDecoderConfigDialogGeometry;
}

QByteArray Configuration::getChromaDecoderConfigDialogGeometry(void)
{
    return settings.windows.chromaDecoderConfigDialogGeometry;
}

// View options
void Configuration::setToggleChromaDuringSeek(bool toggleChromaDuringSeek)
{
    settings.viewOptions.toggleChromaDuringSeek = toggleChromaDuringSeek;
}

bool Configuration::getToggleChromaDuringSeek(void)
{
    return settings.viewOptions.toggleChromaDuringSeek;
}

void Configuration::setResizeFrameWithWindow(bool resizeFrameWithWindow)
{
    settings.viewOptions.resizeFrameWithWindow = resizeFrameWithWindow;
}

bool Configuration::getResizeFrameWithWindow(void)
{
    return settings.viewOptions.resizeFrameWithWindow;
}
