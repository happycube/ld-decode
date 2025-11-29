/******************************************************************************
 * main.cpp
 * ld-json-converter - JSON converter tool for ld-decode
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include <QCoreApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>
#include <QThread>

#include "logging.h"
#include "jsonconverter.h"

int main(int argc, char *argv[])
{
    // Set 'binary mode' for stdin and stdout on Windows
    setBinaryMode();

    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-json-converter");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-json-converter - JSON converter tool for ld-decode\n"
                "\n"
                "(c)2025 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Option to specify a different JSON input file
    QCommandLineOption inputJsonOption(QStringList() << "input-json",
                                       QCoreApplication::translate("main", "Specify the input JSON file"),
                                       QCoreApplication::translate("main", "filename"));
    parser.addOption(inputJsonOption);

    // Option to specify a different SQLite DB output file
    QCommandLineOption outputJsonOption(QStringList() << "output-sqlite",
                                        QCoreApplication::translate("main", "Specify the output SQLite file (default same as input but with .db extension)"),
                                        QCoreApplication::translate("main", "filename"));
    parser.addOption(outputJsonOption);

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the input JSON filename from the parser
    QString inputJsonFilename;
    if (parser.isSet(inputJsonOption)) {
        // Use the --input-json option if provided
        inputJsonFilename = parser.value(inputJsonOption);
    } else {
        // Fall back to positional arguments
        QStringList positionalArguments = parser.positionalArguments();
        if (positionalArguments.count() == 1) {
            inputJsonFilename = positionalArguments.at(0);
        } else {
            // Quit with error
            qCritical("You must specify an input JSON file using --input-json or as a positional argument");
            return -1;
        }
    }

    // Work out the output SQLite filename
    QString outputSqliteFilename;
    if (parser.isSet(outputJsonOption)) {
        outputSqliteFilename = parser.value(outputJsonOption);
    } else {
        // Remove .json extension if present, then add .db
        if (inputJsonFilename.endsWith(".json", Qt::CaseInsensitive)) {
            outputSqliteFilename = inputJsonFilename.left(inputJsonFilename.length() - 5) + ".db";
        } else {
            outputSqliteFilename = inputJsonFilename + ".db";
        }
    }

    // Perform the conversion processing
    qInfo() << "Beginning JSON to SQLite DB processing...";
    JsonConverter jsonConverter(inputJsonFilename, outputSqliteFilename);
    if (!jsonConverter.process()) return 1;

    // Quit with success
    return 0;
}
