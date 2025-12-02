/******************************************************************************
 * main.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "mainwindow.h"
#include <QApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>
#include <QLoggingCategory>

#ifdef Q_OS_WIN
#include <QSettings>
#elif defined(Q_OS_MACOS)
#include <QProcess>
#elif defined(Q_OS_LINUX)
#include <QProcess>
#endif

#include "logging.h"

// Cross-platform function to detect if system is in dark mode
bool isDarkModeEnabled() {
#ifdef Q_OS_WIN
    QSettings settings("HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize", QSettings::NativeFormat);
    return settings.value("AppsUseLightTheme", 1).toInt() == 0;
#elif defined(Q_OS_MACOS)
    QProcess process;
    process.start("defaults", QStringList() << "read" << "-g" << "AppleInterfaceStyle");
    process.waitForFinished();
    QString result = process.readAllStandardOutput().trimmed();
    return result == "Dark";
#elif defined(Q_OS_LINUX)
    // Try gsettings for GNOME color-scheme (modern approach)
    QProcess process;
    process.start("gsettings", QStringList() << "get" << "org.gnome.desktop.interface" << "color-scheme");
    process.waitForFinished();
    QString result = process.readAllStandardOutput().trimmed();
    result = result.remove('\'').remove('"'); // Remove quotes
    if (result.contains("dark", Qt::CaseInsensitive)) {
        return true;
    }
    
    // Fallback: Check GTK theme name
    process.start("gsettings", QStringList() << "get" << "org.gnome.desktop.interface" << "gtk-theme");
    process.waitForFinished();
    result = process.readAllStandardOutput().trimmed();
    result = result.remove('\'').remove('"');
    return result.contains("dark", Qt::CaseInsensitive);
#endif
    return false;
}

// Apply a dark theme palette to the application
void applyDarkTheme(QApplication &app) {
    QPalette darkPalette;
    
    // Define dark theme colors
    QColor windowColor(53, 53, 53);
    QColor baseColor(25, 25, 25);
    QColor alternateColor(64, 64, 64);
    QColor textColor(255, 255, 255);
    QColor buttonColor(53, 53, 53);
    QColor highlightColor(42, 130, 218);
    QColor highlightTextColor(255, 255, 255);
    
    // Set palette colors
    darkPalette.setColor(QPalette::Window, windowColor);
    darkPalette.setColor(QPalette::WindowText, textColor);
    darkPalette.setColor(QPalette::Base, baseColor);
    darkPalette.setColor(QPalette::AlternateBase, alternateColor);
    darkPalette.setColor(QPalette::Text, textColor);
    darkPalette.setColor(QPalette::Button, buttonColor);
    darkPalette.setColor(QPalette::ButtonText, textColor);
    darkPalette.setColor(QPalette::Highlight, highlightColor);
    darkPalette.setColor(QPalette::HighlightedText, highlightTextColor);
    
    app.setPalette(darkPalette);
}

// Custom message handler that filters out Wayland warnings
void filteredDebugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Filter out Wayland requestActivate warnings
    if (msg.contains("Wayland does not support QWindow::requestActivate()")) {
        return; // Don't output this warning
    }
    
    // Call the original handler for all other messages
    debugOutputHandler(type, context, msg);
}

int main(int argc, char *argv[])
{
    // Install the local debug message handler with Wayland filtering
    qInstallMessageHandler(filteredDebugOutputHandler);

    QApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-analyse");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
        "ld-analyse - TBC output analysis\n"
        "\n"
        "(c)2018-2025 Simon Inns\n"
        "(c)2020-2022 Adam Sampson\n"
        "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC file"));

    // Process the command line arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Apply dark theme if system is in dark mode
    if (isDarkModeEnabled()) {
        applyDarkTheme(a);
    }

    // Get the arguments from the parser
    QString inputFileName;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 1) {
        inputFileName = positionalArguments.at(0);
    } else {
        inputFileName.clear();
    }

    // Start the GUI application
    MainWindow w(inputFileName);
    w.show();

    return a.exec();
}
