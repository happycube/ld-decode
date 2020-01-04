/************************************************************************

    main.cpp

    ld-export-metadata - Export JSON metadata into other formats
    Copyright (C) 2020 Adam Sampson

    This file is part of ld-decode-tools.

    ld-export-metadata is free software: you can redistribute it and/or
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

#include <QCoreApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>

#include "csv.h"

#include "lddecodemetadata.h"

// Global for debug output
static bool showDebug = false;

// Global for quiet mode (suppress info and warning messages)
static bool showOutput = true;

// Qt debug message handler
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Use:
    // context.file - to show the filename
    // context.line - to show the line number
    // context.function - to show the function name

    QByteArray localMsg = msg.toLocal8Bit();
    switch (type) {
    case QtDebugMsg: // These are debug messages meant for developers
        if (showDebug) {
            // If the code was compiled as 'release' the context.file will be NULL
            if (context.file != nullptr) fprintf(stderr, "Debug: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
            else fprintf(stderr, "Debug: %s\n", localMsg.constData());
        }
        break;
    case QtInfoMsg: // These are information messages meant for end-users
        if (showOutput) {
            if (context.file != nullptr) fprintf(stderr, "Info: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
            else fprintf(stderr, "Info: %s\n", localMsg.constData());
        }
        break;
    case QtWarningMsg:
        if (showOutput) {
            if (context.file != nullptr) fprintf(stderr, "Warning: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
            else fprintf(stderr, "Warning: %s\n", localMsg.constData());
        }
        break;
    case QtCriticalMsg:
        if (context.file != nullptr) fprintf(stderr, "Critical: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Critical: %s\n", localMsg.constData());
        break;
    case QtFatalMsg:
        if (context.file != nullptr) fprintf(stderr, "Fatal: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Fatal: %s\n", localMsg.constData());
        abort();
    }
}

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-export-metadata");
    QCoreApplication::setApplicationVersion("1.0");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-export-metadata - Export JSON metadata into other formats\n"
                "\n"
                "(c)2020 Adam Sampson\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // -- General options --

    // Option to show debug (-d)
    QCommandLineOption showDebugOption({"d", "debug"},
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to set quiet mode (-q)
    QCommandLineOption setQuietOption({"q", "quiet"},
                                      QCoreApplication::translate("main", "Suppress info and warning messages"));
    parser.addOption(setQuietOption);

    // -- Output types --

    QCommandLineOption writeVitsCsvOption("vits-csv",
                                          QCoreApplication::translate("main", "Write VITS information as CSV"),
                                          QCoreApplication::translate("main", "file"));
    parser.addOption(writeVitsCsvOption);

    QCommandLineOption writeVbiCsvOption("vbi-csv",
                                          QCoreApplication::translate("main", "Write VBI information as CSV"),
                                          QCoreApplication::translate("main", "file"));
    parser.addOption(writeVbiCsvOption);

    // -- Positional arguments --

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input JSON file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    if (parser.isSet(showDebugOption)) showDebug = true;
    if (parser.isSet(setQuietOption)) showOutput = false;

    // Get the arguments from the parser
    QString inputFileName;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 1) {
        inputFileName = positionalArguments.at(0);
    } else {
        qCritical("You must specify the input JSON file");
        return 1;
    }

    // Load the source video metadata
    LdDecodeMetaData metaData;
    if (!metaData.read(inputFileName)) {
        qInfo() << "Unable to read JSON file";
        return 1;
    }

    // Write the selected output files
    if (parser.isSet(writeVitsCsvOption)) {
        const QString &fileName = parser.value(writeVitsCsvOption);
        if (!writeVitsCsv(metaData, fileName)) {
            qCritical() << "Failed to write output file:" << fileName;
            return 1;
        }
    }
    if (parser.isSet(writeVbiCsvOption)) {
        const QString &fileName = parser.value(writeVbiCsvOption);
        if (!writeVbiCsv(metaData, fileName)) {
            qCritical() << "Failed to write output file:" << fileName;
            return 1;
        }
    }

    // Quit with success
    return 0;
}
