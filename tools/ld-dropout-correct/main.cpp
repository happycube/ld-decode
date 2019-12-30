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
    QCoreApplication::setApplicationVersion("1.5");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser ---------------------------------------------------------------------------------
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-dropout-correct - Multi-source dropout correction for ld-decode\n"
                "\n"
                "(c)2018-2020 Simon Inns\n"
                "(C)2019-2020 Adam Sampson\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to specify a different JSON input file
    QCommandLineOption inputJsonOption(QStringList() << "input-json",
                                       QCoreApplication::translate("main", "Specify the input JSON file for the first input file (default input.json)"),
                                       QCoreApplication::translate("main", "filename"));
    parser.addOption(inputJsonOption);

    // Option to specify a different JSON output file
    QCommandLineOption outputJsonOption(QStringList() << "output-json",
                                        QCoreApplication::translate("main", "Specify the output JSON file (default output.json)"),
                                        QCoreApplication::translate("main", "filename"));
    parser.addOption(outputJsonOption);

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
                                        QCoreApplication::translate(
                                         "main", "Specify the number of concurrent threads (default is the number of logical CPUs)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(threadsOption);

    // Positional argument to specify input video file
    parser.addPositionalArgument("inputs", QCoreApplication::translate(
                                     "main", "Specify input TBC files (- as first source for piped input)"));

    // Positional argument to specify output video file
    parser.addPositionalArgument("output", QCoreApplication::translate(
                                     "main", "Specify output TBC file (omit or - for piped output)"));

    // Process the command line options and arguments given by the user -----------------------------------------------
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

    // Require source and target filenames
    QVector<QString> inputFilenames;
    QString outputFilename = "-";
    QStringList positionalArguments = parser.positionalArguments();
    qint32 totalNumberOfInputFiles = positionalArguments.count() - 1;

    // Ensure we don't have more than 32 sources
    if (totalNumberOfInputFiles > 32) {
        qCritical() << "A maximum of 32 input TBC files are supported";
        return -1;
    }

    // Get the input TBC sources
    if (positionalArguments.count() >= 2) {
        // Resize the input filenames vector according to the number of input files supplied
        inputFilenames.resize(totalNumberOfInputFiles);

        for (qint32 i = 0; i < positionalArguments.count() - 1; i++) {
            inputFilenames[i] = positionalArguments.at(i);
        }
    } else {
        // Quit with error
        qCritical("You must specify at least 1 input and 1 output TBC file");
        return -1;
    }

    // Get the output TBC (should be the last argument of the command line
    outputFilename = positionalArguments.at(positionalArguments.count() - 1);

    // If the first input filename is "-" (piped input) - verify a JSON file has been specified
    if (inputFilenames[0] == "-" && !parser.isSet(inputJsonOption)) {
        // Quit with error
        qCritical("With piped input, you must also specify the input JSON file with --input-json");
        return -1;
    }

    // If the output filename is "-" (piped output) - verify a JSON file has been specified
    if (outputFilename == "-" && !parser.isSet(outputJsonOption)) {
        // Quit with error
        qCritical("With piped output, you must also specify the output JSON file with --output-json");
        return -1;
    }

    // Check that none of the input filenames are used as the output file
    for (qint32 i = 0; i < totalNumberOfInputFiles; i++) {
        if (inputFilenames[i] == outputFilename) {
            // Quit with error
            qCritical("Input and output files cannot have the same filenames");
            return -1;
        }
    }

    // Check that none of the input filenames are repeated
    for (qint32 i = 0; i < totalNumberOfInputFiles; i++) {
        for (qint32 j = 0; j < totalNumberOfInputFiles; j++) {
            if (i != j) {
                if (inputFilenames[i] == inputFilenames[j]) {
                    // Quit with error
                    qCritical("Each input file should only be specified once - some filenames were repeated");
                    return -1;
                }
            }
        }
    }

    // Process the command line options
    if (isDebugOn) showDebug = true; else showDebug = false;

    // Metadata filename for output TBC
    QString outputJsonFilename = outputFilename + ".json";
    if (parser.isSet(outputJsonOption)) {
        outputJsonFilename = parser.value(outputJsonOption);
    }

    // Prepare for DOC process ----------------------------------------------------------------------------------------

    qInfo() << "Starting preparation for dropout correction processes...";
    // Open the source video metadata
    qDebug() << "main(): Opening source video metadata files..";
    QVector<LdDecodeMetaData> ldDecodeMetaData;
    ldDecodeMetaData.resize(totalNumberOfInputFiles);
    for (qint32 i = 0; i < totalNumberOfInputFiles; i++) {
        // Work out the metadata filename
        QString jsonFilename = inputFilenames[i] + ".json";
        if (parser.isSet(inputJsonOption) && i == 0) jsonFilename = parser.value(inputJsonOption);
        qInfo().nospace().noquote() << "Reading input #" << i << " JSON metadata from " << jsonFilename;

        // Open it
        if (!ldDecodeMetaData[i].read(jsonFilename)) {
            qCritical() << "Unable to open TBC JSON metadata file - cannot continue";
            return -1;
        }
    }

    // Reverse field order if required
    if (reverse) {
        qInfo() << "Expected field order is reversed to second field/first field";
        for (qint32 i = 0; i < totalNumberOfInputFiles; i++)
            ldDecodeMetaData[i].setIsFirstFieldFirst(false);
    }

    // Intrafield only correction if required
    if (intraField) {
        qInfo() << "Using intra-field correction only - dropouts will only be corrected within the affected field";
    }

    // Overcorrection if required
    if (overCorrect) {
        qInfo() << "Using over correction mode - dropout lengths will be extended to compensate for slow ramping start and end points";
    }

    // Show and open input source TBC files
    qDebug() << "main(): Opening source video files...";
    QVector<SourceVideo> sourceVideos;
    sourceVideos.resize(totalNumberOfInputFiles);

    for (qint32 i = 0; i < totalNumberOfInputFiles; i++) {
        LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData[i].getVideoParameters();

        qInfo().nospace() << "Opening input #" << i << ": " << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight <<
                    " - input filename is " << inputFilenames[i];

        // Open the source TBC
        if (!sourceVideos[i].open(inputFilenames[i], videoParameters.fieldWidth * videoParameters.fieldHeight)) {
            // Could not open source video file
            qInfo() << "Unable to open input source" << i;
            qInfo() << "Please verify that the specified source video files exist with the correct file permissions";
            return 1;
        }

        // Verify TBC and JSON input fields match
        if (sourceVideos[i].getNumberOfAvailableFields() != ldDecodeMetaData[0].getNumberOfFields()) {
            qInfo() << "Warning: TBC file contains" << sourceVideos[i].getNumberOfAvailableFields() <<
                       "fields but the JSON indicates" << ldDecodeMetaData[0].getNumberOfFields() <<
                       "fields - some fields will be ignored";
            qInfo() << "Update your copy of ld-decode and try again, this shouldn't happen unless the JSON metadata has been corrupted";
        }

        // Additional checks when using multiple input sources
        if (totalNumberOfInputFiles > 1) {
            // Ensure source video has VBI data
            if (!ldDecodeMetaData[i].getFieldVbi(1).inUse) {
                qInfo() << "Source video" << i << "does not appear to have valid VBI data in the JSON metadata.";
                qInfo() << "Please try running ld-process-vbi on the source video and then try again";
                return 1;
            }

            // Ensure that the video source standard matches the primary source
            if (ldDecodeMetaData[0].getVideoParameters().isSourcePal != videoParameters.isSourcePal) {
                qInfo() << "All additional input sources must have the same video format (PAL/NTSC) as the initial source!";
                return 1;
            }

            if (!videoParameters.isMapped) {
                qInfo() << "Source video" << i << "has not been mapped - run ld-discmap on all source video and try again";
                qInfo() << "Multi-source dropout correction relies on accurate VBI frame numbering to match source frames together";
                return 1;
            }
        }
    }

    // Perform the DOC process ----------------------------------------------------------------------------------------
    qInfo() << "Initial source checks are ok and sources are loaded";
    CorrectorPool correctorPool(outputFilename, outputJsonFilename, maxThreads,
                                ldDecodeMetaData, sourceVideos,
                                reverse, intraField, overCorrect);
    if (!correctorPool.process()) return 1;

    // Quit with success
    return 0;
}
