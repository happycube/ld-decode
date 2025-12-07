/************************************************************************

    main.cpp

    efm-decoder-audio - EFM Data24 to Audio decoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    This application is free software: you can redistribute it and/or
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
#include <QLoggingCategory>

#include "tbc/logging.h"
#include "efm_processor.h"

int main(int argc, char *argv[])
{
    // Set 'binary mode' for stdin and stdout on Windows
    setBinaryMode();

    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication app(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("efm-decoder-audio");
    QCoreApplication::setApplicationVersion(
            QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
            "efm-decoder-audio - EFM Data24 to Audio decoder\n"
            "\n"
            "(c)2025 Simon Inns\n"
            "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Group of options for specifying output data file type
    QList<QCommandLineOption> outputTypeOptions = {
        QCommandLineOption(
                "audacity-labels",
                QCoreApplication::translate("main", "Output WAV metadata as Audacity labels")),
        QCommandLineOption(
                "no-audio-concealment",
                QCoreApplication::translate("main", "Do not conceal errors in the audio data")),
        QCommandLineOption(
                "zero-pad",
                QCoreApplication::translate("main", "Zero pad the audio data from 00:00:00")),
        QCommandLineOption(
                "no-wav-header",
                QCoreApplication::translate("main", "Output raw audio data without WAV header")),
    };
    parser.addOptions(outputTypeOptions);

    // Group of options for showing frame data
    QList<QCommandLineOption> displayFrameDataOptions = {
        QCommandLineOption("show-audio",
                           QCoreApplication::translate("main", "Show Audio frame data")),
    };
    parser.addOptions(displayFrameDataOptions);

    // Group of options for advanced debugging
    QList<QCommandLineOption> advancedDebugOptions = {
        QCommandLineOption(
                "show-audio-debug",
                QCoreApplication::translate("main", "Show Data24 to audio decoding debug")),
        QCommandLineOption("show-audio-correction-debug",
                           QCoreApplication::translate("main", "Show Audio correction debug")),
        QCommandLineOption("show-all-debug",
                           QCoreApplication::translate("main", "Show all decoding debug")),
    };
    parser.addOptions(advancedDebugOptions);

    // -- Positional arguments --
    parser.addPositionalArgument("input",
                                 QCoreApplication::translate("main", "Specify input Data24 Section file (use '-' for stdin, optional if using stdin)"));
    parser.addPositionalArgument("output",
                                 QCoreApplication::translate("main", "Specify output wav file (use '-' for stdout, optional if using stdout)"));

    // Process the command line options and arguments given by the user
    parser.process(app);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Check for output data type options
    bool outputWavMetadata = parser.isSet("audacity-labels");
    bool noAudioConcealment = parser.isSet("no-audio-concealment");
    bool zeroPad = parser.isSet("zero-pad");
    bool noWavHeader = parser.isSet("no-wav-header");

    // Check for frame data options
    bool showAudio = parser.isSet("show-audio");

    // Check for advanced debug options
    bool showAudioDebug = parser.isSet("show-audio-debug");
    bool showAudioCorrectionDebug = parser.isSet("show-audio-correction-debug");
    bool showAllDebug = parser.isSet("show-all-debug");

    if (showAllDebug) {
        showAudioDebug = true;
        showAudioCorrectionDebug = true;
    }

    // If any debug-specific switch is used, enable Qt debug mode automatically
    // otherwise a specific --debug switch would be needed to see any qDebug output
    if (showAudioDebug || showAudioCorrectionDebug || showAllDebug) {
        setDebug(true);

        // Enable Qt debug logging if debug mode is enabled (as Qt 5.2+ suppresses qDebug by default)
        // Not sure how wide this effect is but without it Fedora 43 shows no qDebug output at all
        QLoggingCategory::setFilterRules("*.debug=true");
    }

    // Get the filename arguments from the parser
    QString inputFilename;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();

    // Handle various argument combinations
    if (positionalArguments.count() == 0) {
        // No arguments: stdin -> stdout
        inputFilename = "-";
        outputFilename = "-";
    } else if (positionalArguments.count() == 1) {
        // One argument: could be input or output, need to determine
        QString arg = positionalArguments.at(0);
        if (arg == "-") {
            // Single "-" means stdin -> stdout
            inputFilename = "-";
            outputFilename = "-";
        } else {
            // Assume it's input file, output to stdout
            inputFilename = arg;
            outputFilename = "-";
        }
    } else if (positionalArguments.count() == 2) {
        // Two arguments: input and output
        inputFilename = positionalArguments.at(0);
        outputFilename = positionalArguments.at(1);
    } else {
        qWarning() << "Too many arguments. Expected: [input] [output] (use '-' for stdin/stdout)";
        return 1;
    }

    // Validate --no-wav-header requirement for stdout pipeline
    if (outputFilename == "-" && !noWavHeader) {
        qCritical() << "ERROR: When piping output to stdout, --no-wav-header is mandatory";
        qCritical() << "WAV headers cannot be written to stdout as they require seeking to update file size information";
        return 1;
    }

    // Perform the processing
    if (inputFilename == "-") {
        qInfo() << "Beginning EFM decoding from stdin";
    } else {
        qInfo() << "Beginning EFM decoding of" << inputFilename;
    }
    EfmProcessor efmProcessor;

    efmProcessor.setShowData(showAudio);
    efmProcessor.setOutputType(outputWavMetadata, noAudioConcealment, zeroPad, noWavHeader);
    efmProcessor.setDebug(showAudioDebug, showAudioCorrectionDebug);

    if (!efmProcessor.process(inputFilename, outputFilename)) {
        return 1;
    }

    // Quit with success
    return 0;
}
