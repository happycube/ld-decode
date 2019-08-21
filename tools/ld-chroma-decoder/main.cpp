/************************************************************************

    main.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018-2019 Simon Inns
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
#include <QtGlobal>
#include <QCommandLineParser>
#include <QScopedPointer>
#include <QThread>

#include "decoderpool.h"
#include "lddecodemetadata.h"

#include "ntscdecoder.h"
#include "paldecoder.h"

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
    QCoreApplication::setApplicationName("ld-chroma-decoder");
    QCoreApplication::setApplicationVersion("1.1");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-chroma-decoder - Colourisation filter for ld-decode\n"
                "\n"
                "(c)2018-2019 Simon Inns\n"
                "(c)2019 Adam Sampson\n"
                "Contains PALcolour: Copyright (c)2018  William Andrew Steer\n"
                "Contains Transform PAL: Copyright (c)2014 Jim Easterbrook\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // -- General options --

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

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

    // Option to set quiet mode (-q)
    QCommandLineOption setQuietOption(QStringList() << "q" << "quiet",
                                       QCoreApplication::translate("main", "Suppress info and warning messages"));
    parser.addOption(setQuietOption);

    // Option to select which decoder to use (-f)
    QCommandLineOption decoderOption(QStringList() << "f" << "decoder",
                                     QCoreApplication::translate("main", "Decoder to use (pal2d, transform2d, ntsc2d, ntsc3d; default automatic)"),
                                     QCoreApplication::translate("main", "decoder"));
    parser.addOption(decoderOption);

    // Option to select the number of threads (-t)
    QCommandLineOption threadsOption(QStringList() << "t" << "threads",
                                        QCoreApplication::translate("main", "Specify the number of concurrent threads (default number of logical CPUs)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(threadsOption);

    // -- NTSC decoder options --

    // Option to show the optical flow map (-o)
    QCommandLineOption showOpticalFlowOption(QStringList() << "o" << "oftest",
                                             QCoreApplication::translate("main", "NTSC: Show the optical flow map (only used for testing)"));
    parser.addOption(showOpticalFlowOption);

    // Option to set the white point to 75% (rather than 100%)
    QCommandLineOption whitePointOption(QStringList() << "w" << "white",
                                        QCoreApplication::translate("main", "NTSC: Use 75% white-point (default 100%)"));
    parser.addOption(whitePointOption);

    // -- PAL decoder options --

    // Option to select the Transform PAL threshold
    QCommandLineOption transformThresholdOption(QStringList() << "transform-threshold",
                                                QCoreApplication::translate("main", "Transform: Similarity threshold for the chroma filter (default 0.4)"),
                                                QCoreApplication::translate("main", "number"));
    parser.addOption(transformThresholdOption);


    // -- Positional arguments --

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC file"));

    // Positional argument to specify output video file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output RGB file (omit for piped output)"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool blackAndWhite = parser.isSet(setBwModeOption);
    bool showOpticalFlow = parser.isSet(showOpticalFlowOption);
    bool whitePoint = parser.isSet(whitePointOption);
    if (parser.isSet(setQuietOption)) showOutput = false;

    // Get the arguments from the parser
    QString inputFileName;
    QString outputFileName;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFileName = positionalArguments.at(0);
        outputFileName = positionalArguments.at(1);
    } else {
        if (positionalArguments.count() == 1) {
            // Use piped output
            inputFileName = positionalArguments.at(0);
            outputFileName.clear(); // Use pipe
        } else {
            // Quit with error
            qCritical("You must specify the input TBC and output RGB files");
            return -1;
        }
    }

    if (inputFileName == outputFileName) {
        // Quit with error
        qCritical("Input and output files cannot be the same");
        return -1;
    }

    qint32 startFrame = -1;
    qint32 length = -1;
    qint32 maxThreads = QThread::idealThreadCount();
    double transformThreshold = 0.4;

    if (parser.isSet(startFrameOption)) {
        startFrame = parser.value(startFrameOption).toInt();

        if (startFrame < 1) {
            // Quit with error
            qCritical("Specified startFrame must be at least 1");
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

    if (parser.isSet(threadsOption)) {
        maxThreads = parser.value(threadsOption).toInt();

        if (maxThreads < 1) {
            // Quit with error
            qCritical("Specified number of threads must be greater than zero");
            return -1;
        }
    }

    if (parser.isSet(transformThresholdOption)) {
        transformThreshold = parser.value(transformThresholdOption).toDouble();
    }

    // Process the command line options
    if (isDebugOn) showDebug = true;

    // Load the source video metadata
    LdDecodeMetaData metaData;
    if (!metaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return -1;
    }

    // Reverse field order if required
    if (parser.isSet(setReverseOption)) {
        qInfo() << "Expected field order is reversed to second field/first field";
        metaData.setIsFirstFieldFirst(false);
    }

    // Work out which decoder to use
    QString decoderName;
    if (parser.isSet(decoderOption)) {
        decoderName = parser.value(decoderOption);
    } else if (metaData.getVideoParameters().isSourcePal) {
        decoderName = "pal2d";
    } else {
        decoderName = "ntsc2d";
    }

    // Require ntsc3d if the optical flow map overlay is selected
    if (showOpticalFlow && decoderName != "ntsc3d") {
        qCritical() << "Can only show optical flow with the ntsc3d decoder";
        return -1;
    }

    // Select the decoder
    QScopedPointer<Decoder> decoder;
    if (decoderName == "pal2d") {
        decoder.reset(new PalDecoder(blackAndWhite));
    } else if (decoderName == "transform2d") {
        decoder.reset(new PalDecoder(blackAndWhite, true, transformThreshold));
    } else if (decoderName == "ntsc2d") {
        decoder.reset(new NtscDecoder(blackAndWhite, whitePoint, false, false));
    } else if (decoderName == "ntsc3d") {
        decoder.reset(new NtscDecoder(blackAndWhite, whitePoint, true, showOpticalFlow));
    } else {
        qCritical() << "Unknown decoder " << decoderName;
        return -1;
    }

    // Perform the processing
    DecoderPool decoderPool(*decoder, inputFileName, metaData, outputFileName, startFrame, length, maxThreads);
    if (!decoderPool.process()) {
        return -1;
    }

    // Quit with success
    return 0;
}
