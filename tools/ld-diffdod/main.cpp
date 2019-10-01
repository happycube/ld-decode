/************************************************************************

    main.cpp

    ld-diffdod - TBC Differential Drop-Out Detection tool
    Copyright (C) 2019 Simon Inns

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

    // Option to select DOD on threshold (dod-on-threshold) (-x)
    QCommandLineOption dodOnThresholdOption(QStringList() << "x" << "dod-on-threshold",
                                        QCoreApplication::translate("main", "Specify the DOD on threshold (100-65435 default: 2000"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(dodOnThresholdOption);

    // Option to select DOD off threshold (dod-off-threshold) (-y)
    QCommandLineOption dodOffThresholdOption(QStringList() << "y" << "dod-off-threshold",
                                        QCoreApplication::translate("main", "Specify the DOD off threshold (100-65435 default: 1000"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(dodOffThresholdOption);

    // Positional argument to specify input TBC files
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC files (minimum of 3)"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool reverse = parser.isSet(setReverseOption);

    // Process the command line options
    if (isDebugOn) setDebug(true); else setDebug(false);

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

    qint32 dodOnThreshold = 2000;
    qint32 dodOffThreshold = 1000;

    if (parser.isSet(dodOnThresholdOption)) {
        dodOnThreshold = parser.value(dodOnThresholdOption).toInt();

        if (dodOnThreshold < 100 || dodOnThreshold > 65435) {
            // Quit with error
            qCritical("DOD threshold must be between 100 and 65435");
            return -1;
        }
    }

    if (parser.isSet(dodOffThresholdOption)) {
        dodOffThreshold = parser.value(dodOffThresholdOption).toInt();

        if (dodOffThreshold < 100 || dodOffThreshold > 65435) {
            // Quit with error
            qCritical("DOD threshold must be between 100 and 65435");
            return -1;
        }
    }

    if (dodOffThreshold > dodOnThreshold) {
        qCritical("DOD on threshold must be higher or equal to DOD off threshold");
    }

    // Process the TBC file
    Diffdod diffdod;
    if (!diffdod.process(inputFilenames, reverse, dodOnThreshold, dodOffThreshold)) {
        return 1;
    }

    // Quit with success
    return 0;
}
