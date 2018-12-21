/************************************************************************

    configuration.h

    ld-analyse - TBC output analysis
    Copyright (C) 2018 Simon Inns

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

    // Get and set methods - windows
    void setMainWindowGeometry(QByteArray mainWindowGeometry);
    QByteArray getMainWindowGeometry(void);
    void setVbiDialogGeometry(QByteArray vbiDialogGeometry);
    QByteArray getVbiDialogGeometry(void);
    void setNtscDialogGeometry(QByteArray ntscDialogGeometry);
    QByteArray getNtscDialogGeometry(void);
    void setOscilloscopeDialogGeometry(QByteArray oscilloscopeDialogGeometry);
    QByteArray getOscilloscopeDialogGeometry(void);

signals:

public slots:

private:
    QSettings *configuration;

    // Directories
    struct Directories {
        QString sourceDirectory;
    };

    // Window geometry and settings
    struct Windows {
        QByteArray mainWindowGeometry;
        QByteArray vbiDialogGeometry;
        QByteArray ntscDialogGeometry;
        QByteArray oscilloscopeDialogGeometry;
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
