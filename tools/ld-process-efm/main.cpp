/************************************************************************

    main.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019-2022 Simon Inns

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
#include <QThread>

#include "logging.h"
#include "efmdecoder.h"

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-process-efm");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-process-efm - EFM data decoder\n"
                "\n"
                "(c)2019-2022 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Audio processing options
    QCommandLineOption concealAudioOption(QStringList() << "c" << "conceal",
                                       QCoreApplication::translate("main", "Conceal corrupt audio data (default)"));
    parser.addOption(concealAudioOption);

    QCommandLineOption silenceAudioOption(QStringList() << "s" << "silence",
                                       QCoreApplication::translate("main", "Silence corrupt audio data"));
    parser.addOption(silenceAudioOption);

    QCommandLineOption passThroughAudioOption(QStringList() << "g" << "pass-through",
                                       QCoreApplication::translate("main", "Pass-through corrupt audio data"));
    parser.addOption(passThroughAudioOption);

    // General decoder options
    QCommandLineOption padOption(QStringList() << "p" << "pad",
                                       QCoreApplication::translate("main", "Pad start of audio from 00:00 to match initial disc time"));
    parser.addOption(padOption);

    QCommandLineOption decodeAsDataOption(QStringList() << "b" << "data",
                                       QCoreApplication::translate("main", "Decode F1 frames as data instead of audio"));
    parser.addOption(decodeAsDataOption);

    QCommandLineOption noTimeStampOption(QStringList() << "t" << "time",
                                       QCoreApplication::translate("main", "Non-standard audio decode (no time-stamp information"));
    parser.addOption(noTimeStampOption);


    // -- Positional arguments --

    // Positional argument to specify input EFM file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input EFM file"));

    // Positional argument to specify output audio file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the padding options from the parser
    bool concealAudio = parser.isSet(concealAudioOption);
    bool silenceAudio = parser.isSet(silenceAudioOption);
    bool passThroughAudio = parser.isSet(passThroughAudioOption);

    bool pad = parser.isSet(padOption);
    bool decodeAsData = parser.isSet(decodeAsDataOption);
    bool noTimeStamp = parser.isSet(noTimeStampOption);

    // Get the filename arguments from the parser
    QString inputFilename;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFilename = positionalArguments.at(0);
        outputFilename = positionalArguments.at(1);
    } else {
        qWarning() << "You must specify the input EFM filename and the output filename";
        return 1;
    }

    // Perform the processing
    qInfo() << "Beginning EFM processing...";
    EfmDecoder efmDecoder;
    if (!efmDecoder.startDecoding(inputFilename, outputFilename,
                                  concealAudio, silenceAudio, passThroughAudio,
                                  pad, decodeAsData, noTimeStamp)) return 1;

    // Quit with success
    return 0;
}
