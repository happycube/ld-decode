/************************************************************************

    main.cpp

    ld-dropout-correct - Dropout correction for ld-decode
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

#include <QCoreApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>
#include <QThread>

#include "correctorpool.h"
#include "dropoutcorrect.h"

// Global for debug output
static bool showDebug = false;

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
        if (context.file != nullptr) fprintf(stderr, "Info: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Info: %s\n", localMsg.constData());
        break;
    case QtWarningMsg:
        if (context.file != nullptr) fprintf(stderr, "Warning: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Warning: %s\n", localMsg.constData());
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
    QCoreApplication::setApplicationName("ld-dropout-correct");
    QCoreApplication::setApplicationVersion("1.4");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-dropout-correct - Dropout correction for ld-decode\n"
                "\n"
                "(c)2018-2019 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to reverse the field order (-r)
    QCommandLineOption setReverseOption(QStringList() << "r" << "reverse",
                                       QCoreApplication::translate("main", "Reverse the field order to second/first (default first/second)"));
    parser.addOption(setReverseOption);

    // Option to select over correct mode (-o)
    QCommandLineOption setOverCorrectOption(QStringList() << "o" << "overcorrect",
                                       QCoreApplication::translate("main", "Over correct mode (use on heavily damaged sources)"));
    parser.addOption(setOverCorrectOption);

    // Force intra-field correction only
    QCommandLineOption setIntrafieldOption(QStringList() << "i" << "intra",
                                       QCoreApplication::translate("main", "Force intrafield correction (default interfield)"));
    parser.addOption(setIntrafieldOption);

    // Option to select the number of threads (-t)
    QCommandLineOption threadsOption(QStringList() << "t" << "threads",
                                        QCoreApplication::translate("main", "Specify the number of concurrent threads (default is the number of logical CPUs)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(threadsOption);

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC file"));

    // Positional argument to specify output video file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output TBC file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool reverse = parser.isSet(setReverseOption);
    bool intraField = parser.isSet(setIntrafieldOption);
    bool overCorrect = parser.isSet(setOverCorrectOption);

    // Get the arguments from the parser
    qint32 maxThreads = QThread::idealThreadCount();
    if (parser.isSet(threadsOption)) {
        maxThreads = parser.value(threadsOption).toInt();

        if (maxThreads < 1) {
            // Quit with error
            qCritical("Specified number of threads must be greater than zero");
            return -1;
        }
    }

    QString inputFilename;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFilename = positionalArguments.at(0);
        outputFilename = positionalArguments.at(1);
    } else {
        // Quit with error
        qCritical("You must specify input and output TBC files");
        return -1;
    }

    if (inputFilename == outputFilename) {
        // Quit with error
        qCritical("Input and output files cannot be the same");
        return -1;
    }

    // Process the command line options
    if (isDebugOn) showDebug = true;

    // Open the JSON metadata
    LdDecodeMetaData metaData;

    // Open the source video metadata
    qInfo().nospace().noquote() << "Reading JSON metadata from " << inputFilename << ".json";
    if (!metaData.read(inputFilename + ".json")) {
        qCritical() << "Unable to open TBC JSON metadata file";
        return 1;
    }

    // Perform the processing
    qInfo() << "Beginning dropout correction...";
    CorrectorPool correctorPool(inputFilename, outputFilename, maxThreads, metaData, reverse, intraField, overCorrect);
    if (!correctorPool.process()) return 1;

    // Quit with success
    return 0;
}
