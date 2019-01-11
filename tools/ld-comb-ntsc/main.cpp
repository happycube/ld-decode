/************************************************************************

    main.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
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

#include "ntscfilter.h"

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
    QCoreApplication::setApplicationName("ld-comb-ntsc");
    QCoreApplication::setApplicationVersion("1.1");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Handle command line options
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "NTSC comb-filter application for ld-decode\n"
                "\n"
                "(c)2018 Chad Page\n"
                "(c)2018 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Declare the filter processing object
    NtscFilter ntscFilter;

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to specify the depth of the filter (2D or 3D) (-f)
    QCommandLineOption filterDepthParameterOption(QStringList() << "f" << "filterdepth",
                QCoreApplication::translate("main", "Specify the filter depth parameter (default is 2)"),
                QCoreApplication::translate("main", "1 to 3"));
    parser.addOption(filterDepthParameterOption);

    // Option to select start frame (sequential) (-s)
    QCommandLineOption startFrameOption(QStringList() << "s" << "start",
                                        QCoreApplication::translate("main", "Specify the start frame number"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(startFrameOption);

    // Option to select length (-l)
    QCommandLineOption lengthOption(QStringList() << "l" << "length",
                                        QCoreApplication::translate("main", "Specify the length (number of frames to process)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(lengthOption);

    // Option to reverse the field order (-r)
    QCommandLineOption setReverseOption(QStringList() << "r" << "reverse",
                                       QCoreApplication::translate("main", "Reverse the field order to second/first (default first/second)"));
    parser.addOption(setReverseOption);

    // Option to set the black and white output flag (causes output to be black and white) (-b)
    QCommandLineOption setBwModeOption(QStringList() << "b" << "blackandwhite",
                                       QCoreApplication::translate("main", "Output in black and white"));
    parser.addOption(setBwModeOption);

    // Option to set the white point to 100% (rather than 75%)
    QCommandLineOption setMaxWhitePoint(QStringList() << "w" << "white",
                                       QCoreApplication::translate("main", "Use 100% white-point (default 75%)"));
    parser.addOption(setMaxWhitePoint);

    // Option to set the no adaptive 2d flag (-n)
    QCommandLineOption noAdaptive2dOption(QStringList() << "n" << "noadaptive2d",
                                       QCoreApplication::translate("main", "Do not use adaptive 2D processing (for 3D filter depth)"));
    parser.addOption(noAdaptive2dOption);

    // Option to set the no optical flow flag (-o)
    QCommandLineOption noOpticalFlowOption(QStringList() << "o" << "noopticalflow",
                                       QCoreApplication::translate("main", "Do not use optical flow processing (for 3D filter depth)"));
    parser.addOption(noOpticalFlowOption);

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC file"));

        // Positional argument to specify output video file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output RGB file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the settings from the parser
    showDebug = parser.isSet(showDebugOption);
    bool reverse = parser.isSet(setReverseOption);
    bool blackAndWhite = parser.isSet(setBwModeOption);
    bool whitePoint = parser.isSet(setMaxWhitePoint);

    bool adaptive2d = true;
    if (parser.isSet(noAdaptive2dOption)) adaptive2d = false;
    bool opticalFlow = true;
    if (parser.isSet(noOpticalFlowOption)) opticalFlow = false;

    qint32 filterDepth = 2;
    if (parser.isSet(filterDepthParameterOption)) {
        filterDepth = parser.value(filterDepthParameterOption).toInt();

        // Range check the parameter
        if (filterDepth < 1 || filterDepth > 3) {
            // Quit with error
            qCritical("Error: The filter depth specified is out of range!");
            return -1;
        }
    }

    qint32 startFrame = -1;
    qint32 length = -1;

    if (parser.isSet(startFrameOption)) {
        startFrame = parser.value(startFrameOption).toInt();

        if (startFrame < 1) {
            // Quit with error
            qCritical("Specified start frame must be at least 1");
            return -1;
        }
    }

    if (parser.isSet(lengthOption)) {
        length = parser.value(lengthOption).toInt();

        if (length < 1) {
            // Quit with error
            qCritical("Specified length must be greater than zero frames");
            return -1;
        }
    }

    QString inputFileName;
    QString outputFileName;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFileName = positionalArguments.at(0);
        outputFileName = positionalArguments.at(1);
    } else {
        // Quit with error
        qCritical("You must specify the input TBC and output RGB files");
        return -1;
    }

    if (inputFileName == outputFileName) {
        // Quit with error
        qCritical("Input and output file names cannot be the same");
        return -1;
    }

    // Process the input file
    ntscFilter.process(inputFileName, outputFileName,
                       startFrame, length, reverse,
                       filterDepth, blackAndWhite, adaptive2d, opticalFlow, whitePoint);

    // Quit with success
    return 0;
}
