/************************************************************************

    configuration.cpp

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
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

#include "configuration.h"

// This define should be incremented if the settings file format changes
static const qint32 SETTINGSVERSION = 3;

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
        qDebug() << "Configuration::Configuration(): Configuration invalid or wrong version (" <<
                    settings.version << "!= " << SETTINGSVERSION <<").  Setting to default values";

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
    configuration->setValue("csvDirectory", settings.directories.csvDirectory);
    configuration->endGroup();

    // Windows
    configuration->beginGroup("windows");
    configuration->setValue("mainWindowGeometry", settings.windows.mainWindowGeometry);
    configuration->setValue("vbiDialogGeometry", settings.windows.vbiDialogGeometry);
    configuration->setValue("ntscDialogGeometry", settings.windows.ntscDialogGeometry);
    configuration->setValue("videoMetadataDialogGeometry", settings.windows.videoMetadataDialogGeometry);
    configuration->setValue("oscilloscopeDialogGeometry", settings.windows.oscilloscopeDialogGeometry);
    configuration->setValue("dropoutAnalysisDialogGeometry", settings.windows.dropoutAnalysisDialogGeometry);
    configuration->setValue("vitsMetricsDialogGeometry", settings.windows.vitsMetricsDialogGeometry);
    configuration->setValue("snrAnalysisDialogGeometry", settings.windows.snrAnalysisDialogGeometry);
    configuration->endGroup();

    // Sync the settings with disk
    qDebug() << "Configuration::writeConfiguration(): Writing configuration to disk";
    configuration->sync();
}

void Configuration::readConfiguration(void)
{
    qDebug() << "Configuration::readConfiguration(): Reading configuration from" << configuration->fileName();

    // Read the valid configuration flag
    settings.version = configuration->value("version").toInt();

    // Directories
    configuration->beginGroup("directories");
    settings.directories.sourceDirectory = configuration->value("sourceDirectory").toString();
    settings.directories.pngDirectory = configuration->value("pngDirectory").toString();
    settings.directories.csvDirectory = configuration->value("csvDirectory").toString();
    configuration->endGroup();

    // Windows
    configuration->beginGroup("windows");
    settings.windows.mainWindowGeometry = configuration->value("mainWindowGeometry").toByteArray();
    settings.windows.vbiDialogGeometry = configuration->value("vbiDialogGeometry").toByteArray();
    settings.windows.ntscDialogGeometry = configuration->value("ntscDialogGeometry").toByteArray();
    settings.windows.videoMetadataDialogGeometry = configuration->value("videoMetadataDialogGeometry").toByteArray();
    settings.windows.oscilloscopeDialogGeometry = configuration->value("oscilloscopeDialogGeometry").toByteArray();
    settings.windows.dropoutAnalysisDialogGeometry = configuration->value("dropoutAnalysisDialogGeometry").toByteArray();
    settings.windows.vitsMetricsDialogGeometry = configuration->value("vitsMetricsDialogGeometry").toByteArray();
    settings.windows.snrAnalysisDialogGeometry = configuration->value("snrAnalysisDialogGeometry").toByteArray();
    configuration->endGroup();
}

void Configuration::setDefault(void)
{
    // Set up the default values
    settings.version = SETTINGSVERSION;

    // Directories
    settings.directories.sourceDirectory = QDir::homePath();
    settings.directories.pngDirectory = QDir::homePath();
    settings.directories.csvDirectory = QDir::homePath();

    // Windows
    settings.windows.mainWindowGeometry = QByteArray();
    settings.windows.vbiDialogGeometry = QByteArray();
    settings.windows.ntscDialogGeometry = QByteArray();
    settings.windows.videoMetadataDialogGeometry = QByteArray();
    settings.windows.oscilloscopeDialogGeometry = QByteArray();
    settings.windows.dropoutAnalysisDialogGeometry = QByteArray();
    settings.windows.vitsMetricsDialogGeometry = QByteArray();
    settings.windows.snrAnalysisDialogGeometry = QByteArray();

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

void Configuration::setCsvDirectory(QString csvDirectory)
{
    settings.directories.csvDirectory = csvDirectory;
}

QString Configuration::getCsvDirectory(void)
{
    return settings.directories.csvDirectory;
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

void Configuration::setVbiDialogGeometry(QByteArray vbiDialogGeometry)
{
    settings.windows.vbiDialogGeometry = vbiDialogGeometry;
}

QByteArray Configuration::getVbiDialogGeometry(void)
{
    return settings.windows.vbiDialogGeometry;
}

void Configuration::setNtscDialogGeometry(QByteArray ntscDialogGeometry)
{
    settings.windows.ntscDialogGeometry = ntscDialogGeometry;
}

QByteArray Configuration::getNtscDialogGeometry(void)
{
    return settings.windows.ntscDialogGeometry;
}

void Configuration::setOscilloscopeDialogGeometry(QByteArray oscilloscopeDialogGeometry)
{
    settings.windows.oscilloscopeDialogGeometry = oscilloscopeDialogGeometry;
}

QByteArray Configuration::getOscilloscopeDialogGeometry(void)
{
    return settings.windows.oscilloscopeDialogGeometry;
}

void Configuration::setVideoMetadataDialogGeometry(QByteArray videoMetadataDialogGeometry)
{
    settings.windows.videoMetadataDialogGeometry = videoMetadataDialogGeometry;
}

QByteArray Configuration::getVideoMetadataDialogGeometry(void)
{
    return settings.windows.videoMetadataDialogGeometry;
}

void Configuration::setDropoutAnalysisDialogGeometry(QByteArray dropoutAnalysisDialogGeometry)
{
    settings.windows.dropoutAnalysisDialogGeometry = dropoutAnalysisDialogGeometry;
}

QByteArray Configuration::getDropoutAnalysisDialogGeometry(void)
{
    return settings.windows.dropoutAnalysisDialogGeometry;
}

void Configuration::setVitsMetricsDialogGeometry(QByteArray vitsMetricsDialogGeometry)
{
    settings.windows.vitsMetricsDialogGeometry = vitsMetricsDialogGeometry;
}

QByteArray Configuration::getVitsMetricsDialogGeometry(void)
{
    return settings.windows.vitsMetricsDialogGeometry;
}

void Configuration::setSnrAnalysisDialogGeometry(QByteArray snrAnalysisDialogGeometry)
{
    settings.windows.snrAnalysisDialogGeometry = snrAnalysisDialogGeometry;
}

QByteArray Configuration::getSnrAnalysisDialogGeometry(void)
{
    return settings.windows.snrAnalysisDialogGeometry;
}

