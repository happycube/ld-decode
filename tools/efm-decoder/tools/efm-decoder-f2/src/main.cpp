/************************************************************************

    main.cpp

    efm-decoder-f2 - EFM T-values to F2 Section decoder
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

#include "logging.h"
#include "efm_processor.h"

int main(int argc, char *argv[])
{
    // Set 'binary mode' for stdin and stdout on windows
    setBinaryMode();
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication app(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("efm-decoder-f2");
    QCoreApplication::setApplicationVersion(
            QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
            "efm-decoder-f2 - EFM T-values to F2 Section decoder\n"
            "\n"
            "(c)2025 Simon Inns\n"
            "GPLv3 Open-Source - github: https://github.com/simoninns/efm-tools");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Group of options for showing frame data
    QList<QCommandLineOption> displayFrameDataOptions = {
        QCommandLineOption("show-f3", QCoreApplication::translate("main", "Show F3 frame data")),
        QCommandLineOption("show-f2", QCoreApplication::translate("main", "Show F2 frame data")),
    };
    parser.addOptions(displayFrameDataOptions);

    // Group of options for advanced debugging
    QList<QCommandLineOption> advancedDebugOptions = {
        QCommandLineOption(
                "show-tvalues-debug",
                QCoreApplication::translate("main", "Show T-values to channel decoding debug")),
        QCommandLineOption(
                "show-channel-debug",
                QCoreApplication::translate("main", "Show channel to F3 decoding debug")),
        QCommandLineOption(
                "show-f3-debug",
                QCoreApplication::translate("main", "Show F3 to F2 section decoding debug")),
        QCommandLineOption(
                "show-f2-correct-debug",
                QCoreApplication::translate("main", "Show F2 section correction debug")),
        QCommandLineOption(
                "show-all-debug",
                QCoreApplication::translate("main", "Show all debug")),
    };
    parser.addOptions(advancedDebugOptions);

    // -- Positional arguments --
    parser.addPositionalArgument("input",
                                 QCoreApplication::translate("main", "Specify input EFM file"));
    parser.addPositionalArgument("output",
                                 QCoreApplication::translate("main", "Specify output F2 section file"));

    // Process the command line options and arguments given by the user
    parser.process(app);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Check for frame data options
    bool showF2 = parser.isSet("show-f2");
    bool showF3 = parser.isSet("show-f3");

    // Check for advanced debug options
    bool showTValuesDebug = parser.isSet("show-tvalues-debug");
    bool showChannelDebug = parser.isSet("show-channel-debug");
    bool showF3Debug = parser.isSet("show-f3-debug");
    bool showF2CorrectDebug = parser.isSet("show-f2-correct-debug");
    bool showAllDebug = parser.isSet("show-all-debug");

    if (showAllDebug) {
        showTValuesDebug = true;
        showChannelDebug = true;
        showF3Debug = true;
        showF2CorrectDebug = true;
    }

    // Get the filename arguments from the parser
    QString inputFilename;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();

    if (positionalArguments.count() != 2) {
        qWarning() << "You must specify the input EFM filename and the output F2 section filename";
        return 1;
    }
    inputFilename = positionalArguments.at(0);
    outputFilename = positionalArguments.at(1);

    // Perform the processing
    qInfo() << "Beginning EFM decoding of" << inputFilename;
    EfmProcessor efmProcessor;

    efmProcessor.setShowData(showF2, showF3);
    efmProcessor.setDebug(showTValuesDebug, showChannelDebug, showF3Debug, showF2CorrectDebug);

    if (!efmProcessor.process(inputFilename, outputFilename)) {
        return 1;
    }

    // Quit with success
    return 0;
}