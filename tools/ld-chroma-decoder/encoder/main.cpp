/************************************************************************

    main.cpp

    ld-chroma-encoder - PAL encoder for testing
    Copyright (C) 2019 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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
#include <QFile>
#include <QtGlobal>
#include <QCommandLineParser>
#include <cstdio>

#include "lddecodemetadata.h"

#include "palencoder.h"

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
    QCoreApplication::setApplicationName("ld-chroma-encoder");
    QCoreApplication::setApplicationVersion("1.0");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-chroma-encoder - PAL encoder for testing\n"
                "\n"
                "(c)2019 Adam Sampson\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // -- General options --

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to set quiet mode (-q)
    QCommandLineOption setQuietOption(QStringList() << "q" << "quiet",
                                       QCoreApplication::translate("main", "Suppress info and warning messages"));
    parser.addOption(setQuietOption);

    // -- Positional arguments --

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input RGB file (- for piped input)"));

    // Positional argument to specify output video file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output TBC file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    if (parser.isSet(showDebugOption)) showDebug = true;
    if (parser.isSet(setQuietOption)) showOutput = false;

    // Get the arguments from the parser
    QString inputFileName;
    QString outputFileName;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFileName = positionalArguments.at(0);
        outputFileName = positionalArguments.at(1);
    } else {
        // Quit with error
        qCritical("You must specify the input RGB and output TBC files");
        return -1;
    }

    if (inputFileName == outputFileName) {
        // Quit with error
        qCritical("Input and output files cannot be the same");
        return -1;
    }

    // Open the input file
    QFile rgbFile(inputFileName);
    if (inputFileName == "-") {
        if (!rgbFile.open(stdin, QFile::ReadOnly)) {
            qCritical("Cannot open stdin");
            return -1;
        }
    } else {
        if (!rgbFile.open(QFile::ReadOnly)) {
            qCritical() << "Cannot open input file:" << inputFileName;
            return -1;
        }
    }

    // Open the output file
    QFile tbcFile(outputFileName);
    if (!tbcFile.open(QFile::WriteOnly)) {
        qCritical() << "Cannot open output file:" << outputFileName;
        return -1;
    }

    // Encode the data
    LdDecodeMetaData metaData;
    PALEncoder encoder(rgbFile, tbcFile, metaData);
    if (!encoder.encode()) {
        return -1;
    }

    // Write the metadata
    if (!metaData.write(outputFileName + ".json")) {
        return -1;
    }

    // Quit with success
    return 0;
}
