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

#include "logging.h"

// Custom message handler that filters out Wayland warnings
// Doesn't seem to be any way to disable these from Qt directly at present so
// this code will filter them out here.
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
