/************************************************************************

    main.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "mainwindow.h"
#include <QApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>

#include "logging.h"

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-process-efm");
    QCoreApplication::setApplicationVersion("3.0");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-process-efm - EFM data decoder\n"
                "\n"
                "(c)2019 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Option to show debug (-d / --debug)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to show debug (-d / --debug)
    QCommandLineOption nonInteractiveOption(QStringList() << "n" << "noninteractive",
                                       QCoreApplication::translate("main", "Run in non-interactive mode"));
    parser.addOption(nonInteractiveOption);

    // -- Positional arguments --

    // Positional argument to specify input EFM file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input EFM file"));

    // Positional argument to specify output audio file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output audio file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool isNonInteractiveOn = parser.isSet(nonInteractiveOption);

    // Process the command line options
    if (isDebugOn) setDebug(true); else setDebug(false);

    // Get the arguments from the parser
    QString inputEfmFilename;
    QString outputAudioFilename;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputEfmFilename = positionalArguments.at(0);
        outputAudioFilename = positionalArguments.at(1);
    } else if (positionalArguments.count() == 1) {
        inputEfmFilename = positionalArguments.at(0);
    }

    if (isNonInteractiveOn) {
        if (inputEfmFilename.isEmpty() || outputAudioFilename.isEmpty()) {
            qWarning() << "You must specify the input EFM filename and the output audio filename in non-interactive mode";
            return 1;
        }
    }

    // Start the GUI application
    MainWindow w(isDebugOn, isNonInteractiveOn, outputAudioFilename);
    if (!inputEfmFilename.isEmpty()) {
        // Load the file to decode
        if (!w.loadInputEfmFile(inputEfmFilename)) {
            if (isNonInteractiveOn) {
                return 1;
            }
        } else {
            if (isNonInteractiveOn) {
                // Start the decode
                w.startDecodeNonInteractive();
            }
        }
    }

    if (!isNonInteractiveOn) w.show();

    return a.exec();
}
