/************************************************************************

    main.cpp

    efm-decoder-data - EFM Data24 to data decoder
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
    QCoreApplication::setApplicationName("efm-decoder-data");
    QCoreApplication::setApplicationVersion(
            QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
            "efm-decoder-data - EFM Data24 to data decoder\n"
            "\n"
            "(c)2025 Simon Inns\n"
            "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Group of options for specifying output data file type
    QList<QCommandLineOption> outputTypeOptions = {
        QCommandLineOption("output-metadata",
                QCoreApplication::translate("main", "Output bad sector map metadata")),
    };
    parser.addOptions(outputTypeOptions);

    // Group of options for showing frame data
    QList<QCommandLineOption> displayFrameDataOptions = {
        QCommandLineOption("show-rawsector",
                           QCoreApplication::translate("main", "Show Raw Sector frame data")),
    };
    parser.addOptions(displayFrameDataOptions);

    // Group of options for advanced debugging
    QList<QCommandLineOption> advancedDebugOptions = {
        QCommandLineOption("show-rawsector-debug",
                QCoreApplication::translate("main", "Show Data24 to raw sector decoding debug")),
        QCommandLineOption("show-sector-debug",
                QCoreApplication::translate("main", "Show raw sector to sector decoding debug")),
        QCommandLineOption("show-sector-correction-debug",
                QCoreApplication::translate("main", "Show sector correction decoding debug")),
        QCommandLineOption("show-all-debug",
                QCoreApplication::translate("main", "Show all decoding debug")),
    };
    parser.addOptions(advancedDebugOptions);

    // -- Positional arguments --
    parser.addPositionalArgument("input",
                                 QCoreApplication::translate("main", "Specify input Data24 Section file (use '-' for stdin, optional if using stdin)"));
    parser.addPositionalArgument("output",
                                 QCoreApplication::translate("main", "Specify output data file (use '-' for stdout, optional if using stdout)"));

    // Process the command line options and arguments given by the user
    parser.process(app);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Check for output data type options
    bool outputDataMetadata = parser.isSet("output-metadata");

    // Check for frame data options
    bool showRawSector = parser.isSet("show-rawsector");

    // Check for advanced debug options
    bool showRawSectorDebug = parser.isSet("show-rawsector-debug");
    bool showSectorDebug = parser.isSet("show-sector-debug");
    bool showSectorCorrectionDebug = parser.isSet("show-sector-correction-debug");
    bool showAllDebug = parser.isSet("show-all-debug");

    if (showAllDebug) {
        showRawSectorDebug = true;
        showSectorDebug = true;
        showSectorCorrectionDebug = true;
    }

    // If any debug-specific switch is used, enable Qt debug mode automatically
    // otherwise a specific --debug switch would be needed to see any qDebug output
    if (showRawSectorDebug || showSectorDebug || showSectorCorrectionDebug || showAllDebug) {
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

    // Check for incompatible options
    if (outputDataMetadata && outputFilename == "-") {
        qWarning() << "Error: --output-metadata cannot be used when outputting to stdout. Please specify a file for output.";
        return 1;
    }

    // Perform the processing
    if (inputFilename == "-") {
        qInfo() << "Beginning Data24 to ECMA-130 Data decoding from stdin";
    } else {
        qInfo() << "Beginning Data24 to ECMA-130 Data decoding of" << inputFilename;
    }
    EfmProcessor efmProcessor;

    efmProcessor.setShowData(showRawSector);
    efmProcessor.setOutputType(outputDataMetadata);
    efmProcessor.setDebug(showRawSectorDebug, showSectorDebug, showSectorCorrectionDebug);

    if (!efmProcessor.process(inputFilename, outputFilename)) {
        return 1;
    }

    // Quit with success
    return 0;
}
