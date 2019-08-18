/************************************************************************

    main.cpp

    ld-combine - TBC combination and enhancement tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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

#include "logging.h"
#include "combine.h"

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-combine");
    QCoreApplication::setApplicationVersion("3.0");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-combine - TBC combination and enhancement tool\n"
                "\n"
                "(c)2019 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Option to show debug (-d / --debug)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to reverse the field order (-r / --reverse)
    QCommandLineOption setReverseOption(QStringList() << "r" << "reverse",
                                       QCoreApplication::translate("main", "Reverse the field order to second/first (default first/second)"));
    parser.addOption(setReverseOption);

    // Option to select DOD threshold (dodthreshold) (-x)
    QCommandLineOption dodThresholdOption(QStringList() << "x" << "dodthreshold",
                                        QCoreApplication::translate("main", "Specify the DOD threshold (100-65435 default: 6000"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(dodThresholdOption);

    // Option to select start frame (start) (-s)
    QCommandLineOption startFrameOption(QStringList() << "s" << "start",
                                        QCoreApplication::translate("main", "Specify the start VBI frame number"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(startFrameOption);

    // Option to select length (-l)
    QCommandLineOption lengthOption(QStringList() << "l" << "length",
                                        QCoreApplication::translate("main", "Specify the length (number of frames to process)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(lengthOption);

    // Positional argument to specify input TBC files
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC files (minimum 3)"));

    // Positional argument to specify output TBC file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output TBC file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool reverse = parser.isSet(setReverseOption);

    // Process the command line options
    if (isDebugOn) setDebug(true); else setDebug(false);

    QVector<QString> inputFilenames;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();

    // Require source and target filenames
    if (positionalArguments.count() > 65) {
        qCritical() << "A maximum of 64 input sources are supported";
        return -1;
    }

    if (positionalArguments.count() >= 4) {
        for (qint32 i = 0; i < positionalArguments.count() - 1; i++) {
            inputFilenames.append(positionalArguments.at(i));
        }
        outputFilename = positionalArguments.at(positionalArguments.count() - 1);
    } else {
        // Quit with error
        qCritical("You must specify at least 3 input TBC files and one output TBC file");
        return -1;
    }

    qint32 vbiStartFrame = -1;
    qint32 length = -1;
    qint32 dodThreshold = 6000;

    if (parser.isSet(startFrameOption)) {
        vbiStartFrame = parser.value(startFrameOption).toInt();

        if (vbiStartFrame < 1) {
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

    if (parser.isSet(dodThresholdOption)) {
        dodThreshold = parser.value(dodThresholdOption).toInt();

        if (dodThreshold < 100 || dodThreshold > 65435) {
            // Quit with error
            qCritical("DOD threshold must be between 100 and 65435");
            return -1;
        }
    }

    // Process the TBC file
    Combine combine;
    if (!combine.process(inputFilenames, outputFilename, reverse, vbiStartFrame, length, dodThreshold)) {
        return 1;
    }

    // Quit with success
    return 0;
}
