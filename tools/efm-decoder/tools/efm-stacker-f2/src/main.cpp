/************************************************************************

    main.cpp

    efm-stacker-f2 - EFM F2 Section stacker
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
#include <QFileInfo>

#include "logging.h"
#include "f2_stacker.h"

int main(int argc, char *argv[])
{
    // Set 'binary mode' for stdin and stdout on windows
    setBinaryMode();
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication app(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("efm-stacker-f2");
    QCoreApplication::setApplicationVersion(
            QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
            "efm-stacker-f2 - EFM F2 Section stacker\n"
            "\n"
            "(c)2025 Simon Inns\n"
            "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Positional arguments
    parser.addPositionalArgument("inputs",
                                 QCoreApplication::translate("main", "Specify input F2 section files"));
    parser.addPositionalArgument("output",
                                 QCoreApplication::translate("main", "Specify output F2 section file"));

    // Process the command line options and arguments given by the user
    parser.process(app);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the filename arguments from the parser
    QVector<QString> inputFilenames;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();
    qint32 totalNumberOfInputFiles = positionalArguments.count() - 1;

    // Ensure we don't have more than 32 sources
    if (totalNumberOfInputFiles > 32) {
        qCritical() << "A maximum of 32 input F2 section files are supported";
        return -1;
    }

    // Get the input F2 section sources
    if (positionalArguments.count() >= 3) {
        // Resize the input filenames vector according to the number of input files supplied
        inputFilenames.resize(totalNumberOfInputFiles);

        for (qint32 i = 0; i < positionalArguments.count() - 1; i++) {
            inputFilenames[i] = positionalArguments.at(i);
        }

        // Warn if only 2 sources are used
        if (positionalArguments.count() == 3) {
            qInfo() << "Only 2 input sources specified (3 or more sources are recommended)";
        }
    } else {
        // Quit with error
        qCritical("You must specify at least 2 input F2 section files and 1 output F2 section file");
        return -1;
    }

    // Get the output F2 section file (should be the last argument of the command line)
    outputFilename = positionalArguments.at(positionalArguments.count() - 1);

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
                    qCritical("Each input file should only be specified once - some F2 section files were repeated");
                    return -1;
                }
            }
        }
    }
    
    // Perform the processing
    qInfo() << "Beginning F2 Section stacking...";

    F2Stacker f2Stacker;
    if (!f2Stacker.process(inputFilenames, outputFilename)) {
        // Quit with error
        qCritical("F2 Section stacking failed");
        return -1;
    }

    // Quit with success
    return 0;
}