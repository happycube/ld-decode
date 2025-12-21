/******************************************************************************
 * main.cpp
 * ld-export-decode-metadata - metadata export tool for ld-decode
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
#include "metadataconverter.h"

int main(int argc, char *argv[])
{
    // Set 'binary mode' for stdin and stdout on Windows
    setBinaryMode();

    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-export-decode-metadata");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-export-decode-metadata - JSON converter tool for ld-decode\n"
                "\n"
                "(c)2025 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Option to specify a different JSON input file
    QCommandLineOption inputSqliteOption(QStringList() << "input-sqlite",
                                       QCoreApplication::translate("main", "Specify the input SQLite file"),
                                       QCoreApplication::translate("main", "filename"));
    parser.addOption(inputSqliteOption);

    // Option to specify a different SQLite DB output file
    QCommandLineOption outputJsonOption(QStringList() << "output-json",
                                        QCoreApplication::translate("main", "Specify the output JSON file (default same as input but with -export.json extension)"),
                                        QCoreApplication::translate("main", "filename"));
    parser.addOption(outputJsonOption);

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the input JSON filename from the parser
    QString inputSqliteFilename;
    if (parser.isSet(inputSqliteOption)) {
        // Use the --input-json option if provided
        inputSqliteFilename = parser.value(inputSqliteOption);
    } else {
        // Fall back to positional arguments
        QStringList positionalArguments = parser.positionalArguments();
        if (positionalArguments.count() == 1) {
            inputSqliteFilename = positionalArguments.at(0);
        } else {
            // Quit with error
            qCritical("You must specify an input SQLite file using --input-sqlite or as a positional argument");
            return -1;
        }
    }

    // Work out the output SQLite filename
    QString outputJsonFilename;
    if (parser.isSet(outputJsonOption)) {
        outputJsonFilename = parser.value(outputJsonOption);
    } else {
        // Remove .json extension if present, then add .db
        if (inputSqliteFilename.endsWith(".db", Qt::CaseInsensitive)) {
            outputJsonFilename = inputSqliteFilename.left(inputSqliteFilename.length() - 3) + ".export.json";
        } else {
            outputJsonFilename = inputSqliteFilename + ".export.json";
        }
    }

    // Perform the conversion processing
    qInfo() << "Beginning SQLite DB to export JSON processing...";
    MetadataConverter metadataConverter(inputSqliteFilename, outputJsonFilename);
    if (!metadataConverter.process()) return 1;

    // Quit with success
    return 0;
}
