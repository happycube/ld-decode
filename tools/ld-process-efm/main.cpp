/************************************************************************

    main.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "efmprocess.h"

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
    QCoreApplication::setApplicationName("ld-process-efm");
    QCoreApplication::setApplicationVersion("1.0");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-process-efm - EFM data decoder\n"
                "\n"
                "(c)2019 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to show verbose F3 framing debug (-v)
    QCommandLineOption verboseDebugOption(QStringList() << "x" << "verbose",
                                       QCoreApplication::translate("main", "Show verbose F3 framing debug"));
    parser.addOption(verboseDebugOption);


    // Option to specify input EFM file (-i)
    QCommandLineOption inputEfmFileOption(QStringList() << "i" << "input",
                QCoreApplication::translate("main", "Specify input EFM file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(inputEfmFileOption);

    // Option to specify output audio file (-a)
    QCommandLineOption outputAudioFileOption(QStringList() << "a" << "audio",
                QCoreApplication::translate("main", "Specify output audio file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(outputAudioFileOption);

    // Option to specify output sector data file (-s)
    QCommandLineOption outputDataFileOption(QStringList() << "s" << "data",
                QCoreApplication::translate("main", "Specify output sector data file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(outputDataFileOption);

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool verboseDebug = parser.isSet(verboseDebugOption);

    // Get the arguments from the parser
    QString inputEfmFilename = parser.value(inputEfmFileOption);
    QString outputAudioFilename = parser.value(outputAudioFileOption);
    QString outputDataFilename = parser.value(outputDataFileOption);

    // Check the parameters
    if (inputEfmFilename.isEmpty()) {
        qCritical() << "You must specify an input EFM file using --input";
        return -1;
    }

    if (outputAudioFilename.isEmpty() && outputDataFilename.isEmpty()) {
        qCritical() << "You must specify either audio output (with --audio <filename>) or sector data output (with --sector <filename>)";
        return -1;
    }

    // Process the command line options
    if (isDebugOn) showDebug = true;

    // Perform the processing
    EfmProcess efmProcess;
    efmProcess.process(inputEfmFilename, outputAudioFilename, outputDataFilename, verboseDebug);

    // Quit with success
    return 0;
}
