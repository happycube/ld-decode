/************************************************************************

    configuration.h

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-analyse is free software: you can redistribute it and/or
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
    void setCsvDirectory(QString csvDirectory);
    QString getCsvDirectory(void);

    // Get and set methods - windows
    void setMainWindowGeometry(QByteArray mainWindowGeometry);
    QByteArray getMainWindowGeometry(void);
    void setVbiDialogGeometry(QByteArray vbiDialogGeometry);
    QByteArray getVbiDialogGeometry(void);
    void setNtscDialogGeometry(QByteArray ntscDialogGeometry);
    QByteArray getNtscDialogGeometry(void);
    void setOscilloscopeDialogGeometry(QByteArray oscilloscopeDialogGeometry);
    QByteArray getOscilloscopeDialogGeometry(void);
    void setVideoMetadataDialogGeometry(QByteArray videoMetadataDialogGeometry);
    QByteArray getVideoMetadataDialogGeometry(void);
    void setDropoutAnalysisDialogGeometry(QByteArray videoMetadataDialogGeometry);
    QByteArray getDropoutAnalysisDialogGeometry(void);
    void setSnrAnalysisDialogGeometry(QByteArray snrAnalysisDialogGeometry);
    QByteArray getSnrAnalysisDialogGeometry(void);

signals:

public slots:

private:
    QSettings *configuration;

    // Directories
    struct Directories {
        QString sourceDirectory; // Last used directory for .tbc files
        QString pngDirectory; // Last used directory for .png files
        QString csvDirectory; // Last used directory for .csv files
    };

    // Window geometry and settings
    struct Windows {
        QByteArray mainWindowGeometry;
        QByteArray vbiDialogGeometry;
        QByteArray ntscDialogGeometry;
        QByteArray videoMetadataDialogGeometry;
        QByteArray oscilloscopeDialogGeometry;
        QByteArray dropoutAnalysisDialogGeometry;
        QByteArray snrAnalysisDialogGeometry;
    };

    // Overall settings structure
    struct Settings {
        qint32 version;
        Directories directories;
        Windows windows;
    } settings;

    void setDefault(void);
};

#endif // CONFIGURATION_H
