/************************************************************************

    main.cpp

    efm-decoder-d24 - EFM F2Section to Data24 Section decoder
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
    QCoreApplication::setApplicationName("efm-decoder-d24");
    QCoreApplication::setApplicationVersion(
            QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
            "efm-decoder-d24 - EFM F2 Section to Data24 Section decoder\n"
            "\n"
            "(c)2025 Simon Inns\n"
            "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Group of options for showing frame data
    QList<QCommandLineOption> displayFrameDataOptions = {
        QCommandLineOption("show-f1", QCoreApplication::translate("main", "Show F1 frame data")),
        QCommandLineOption("show-data24",
                           QCoreApplication::translate("main", "Show Data24 frame data")),
    };
    parser.addOptions(displayFrameDataOptions);

    // Group of options for advanced debugging
    QList<QCommandLineOption> advancedDebugOptions = {
        QCommandLineOption("show-f2-debug",
                           QCoreApplication::translate("main", "Show F2 to F1 decoding debug")),
        QCommandLineOption("show-f1-debug",
                           QCoreApplication::translate("main", "Show F1 to Data24 decoding debug")),
        QCommandLineOption(("show-all-debug"),
                           QCoreApplication::translate("main", "Show all debug options"))
    };
    parser.addOptions(advancedDebugOptions);

    // -- Positional arguments --
    parser.addPositionalArgument("input",
                                 QCoreApplication::translate("main", "Specify input F2 Section file"));
    parser.addPositionalArgument("output",
                                 QCoreApplication::translate("main", "Specify output Data24 Section file"));

    // Process the command line options and arguments given by the user
    parser.process(app);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Check for frame data options
    bool showF1 = parser.isSet("show-f1");
    bool showData24 = parser.isSet("show-data24");

    // Check for advanced debug options
    bool showF2Debug = parser.isSet("show-f2-debug");
    bool showF1Debug = parser.isSet("show-f1-debug");
    bool showAllDebug = parser.isSet("show-all-debug");

    if (showAllDebug) {
        showF2Debug = true;
        showF1Debug = true;
    }

    // Get the filename arguments from the parser
    QString inputFilename;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();

    if (positionalArguments.count() != 2) {
        qWarning() << "You must specify the input F2 Section filename and the output Data24 Section filename";
        return 1;
    }
    inputFilename = positionalArguments.at(0);
    outputFilename = positionalArguments.at(1);

    // Perform the processing
    qInfo() << "Beginning EFM decoding of" << inputFilename;
    EfmProcessor efmProcessor;

    efmProcessor.setShowData(showData24, showF1);
    efmProcessor.setDebug(showF2Debug, showF1Debug);

    if (!efmProcessor.process(inputFilename, outputFilename)) {
        return 1;
    }

    // Quit with success
    return 0;
}