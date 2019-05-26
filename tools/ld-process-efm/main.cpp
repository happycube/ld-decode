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

#include <QCoreApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>

#include "logging.h"
#include "efmprocess.h"

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-process-efm");
    QCoreApplication::setApplicationVersion("1.1");
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

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to show verbose F3 framing debug (-v)
    QCommandLineOption verboseDebugOption(QStringList() << "x" << "verbose",
                                       QCoreApplication::translate("main", "Show verbose F3 framing debug"));
    parser.addOption(verboseDebugOption);

    // Option to specify input EFM file (-i)
    QCommandLineOption inputEfmFileOption(QStringList() << "i" << "input",
                QCoreApplication::translate("main", "Specify input EFM file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(inputEfmFileOption);

    // Option to specify output audio file (-a)
    QCommandLineOption outputAudioFileOption(QStringList() << "a" << "audio",
                QCoreApplication::translate("main", "Specify output audio file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(outputAudioFileOption);

    // Option to specify output sector data file (-s)
    QCommandLineOption outputDataFileOption(QStringList() << "s" << "data",
                QCoreApplication::translate("main", "Specify output sector data file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(outputDataFileOption);

    // Option to specify output log file (-l)
    QCommandLineOption outputLogFileOption(QStringList() << "l" << "log",
                QCoreApplication::translate("main", "Specify optional log file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(outputLogFileOption);

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool verboseDebug = parser.isSet(verboseDebugOption);

    // Get the arguments from the parser
    QString inputEfmFilename = parser.value(inputEfmFileOption);
    QString outputAudioFilename = parser.value(outputAudioFileOption);
    QString outputDataFilename = parser.value(outputDataFileOption);
    QString outputLogFilename = parser.value(outputLogFileOption);

    // Check the parameters
    if (inputEfmFilename.isEmpty()) {
        qCritical() << "You must specify an input EFM file using --input";
        return -1;
    }

    if (outputAudioFilename.isEmpty() && outputDataFilename.isEmpty()) {
        qCritical() << "You must specify either audio output (with --audio <filename>) or sector data output (with --sector <filename>)";
        return -1;
    }

    if (!outputLogFilename.isEmpty()) {
        openDebugFile(outputLogFilename);
    }

    // Process the command line options
    if (isDebugOn) setDebug(true); else setDebug(false);

    // Perform the processing
    EfmProcess efmProcess;
    efmProcess.process(inputEfmFilename, outputAudioFilename, outputDataFilename, verboseDebug);

    // Close the log file
    if (!outputLogFilename.isEmpty()) {
        closeDebugFile();
    }

    // Quit with success
    return 0;
}
