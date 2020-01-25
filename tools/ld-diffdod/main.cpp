/************************************************************************

    main.cpp

    ld-diffdod - TBC Differential Drop-Out Detection tool
    Copyright (C) 2019-2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-diffdod is free software: you can redistribute it and/or
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
#include "diffdod.h"

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-diffdod");
    QCoreApplication::setApplicationVersion("1.0");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-diffdod - TBC Differential Drop-Out Detection tool\n"
                "\n"
                "(c)2019-2020 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Option to reverse the field order (-r / --reverse)
    QCommandLineOption setReverseOption(QStringList() << "r" << "reverse",
                                       QCoreApplication::translate("main", "Reverse the field order to second/first (default first/second)"));
    parser.addOption(setReverseOption);

    // Option to turn off luma clip detection (-n / --lumaclip)
    QCommandLineOption setLumaOption(QStringList() << "n" << "lumaclip",
                                       QCoreApplication::translate("main", "Perform luma clip signal dropout detection"));
    parser.addOption(setLumaOption);

    // Option to select DOD threshold (-x / --dod-threshold)
    QCommandLineOption dodThresholdOption(QStringList() << "x" << "dod-threshold",
                                        QCoreApplication::translate("main", "Specify the DOD threshold (100-65435 default: 600"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(dodThresholdOption);

    // Option to select the start VBI frame (-s / --start)
    QCommandLineOption startVbiOption(QStringList() << "s" << "start",
                                        QCoreApplication::translate("main", "Specify the start VBI frame"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(startVbiOption);

    // Option to select the maximum number of VBI frames to process (-l / --length)
    QCommandLineOption lengthVbiOption(QStringList() << "l" << "length",
                                        QCoreApplication::translate("main", "Specify the maximum number of VBI frames to process"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(lengthVbiOption);

    // Positional argument to specify input TBC files
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC files (minimum of 3)"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the options from the parser
    bool reverse = parser.isSet(setReverseOption);
    bool lumaClip = parser.isSet(setLumaOption);

    QVector<QString> inputFilenames;
    QStringList positionalArguments = parser.positionalArguments();

    // Require source and target filenames
    if (positionalArguments.count() > 65) {
        qCritical() << "A maximum of 64 input sources are supported";
        return -1;
    }

    if (positionalArguments.count() >= 3) {
        for (qint32 i = 0; i < positionalArguments.count(); i++) {
            inputFilenames.append(positionalArguments.at(i));
        }
    } else {
        // Quit with error
        qCritical("You must specify at least 3 input TBC files");
        return -1;
    }

    qint32 dodThreshold = 600;
    if (parser.isSet(dodThresholdOption)) {
        dodThreshold = parser.value(dodThresholdOption).toInt();

        if (dodThreshold < 100 || dodThreshold > 65435) {
            // Quit with error
            qCritical("DOD threshold must be between 100 and 65435");
            return -1;
        }
    }

    qint32 vbiFrameStart = 0;
    if (parser.isSet(startVbiOption)) {
        vbiFrameStart = parser.value(startVbiOption).toInt();

        if (vbiFrameStart < 1 || vbiFrameStart > 160000) {
            // Quit with error
            qCritical("Start VBI frame must be between 1 and 160000");
            return -1;
        }
    }

    qint32 vbiFrameLength = -1;
    if (parser.isSet(lengthVbiOption)) {
        vbiFrameLength = parser.value(lengthVbiOption).toInt();

        if (vbiFrameLength < 1 || vbiFrameLength > 160000) {
            // Quit with error
            qCritical("VBI frame length must be between 1 and 160000");
            return -1;
        }
    }

    // Process the TBC file
    Diffdod diffdod;
    if (!diffdod.process(inputFilenames, reverse, dodThreshold, lumaClip, vbiFrameStart, vbiFrameLength)) {
        return 1;
    }

    // Quit with success
    return 0;
}
