/************************************************************************

    main.cpp

    ld-chroma-encoder - PAL encoder for testing
    Copyright (C) 2019-2020 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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
#include <QFile>
#include <QtGlobal>
#include <QCommandLineParser>
#include <cstdio>

#include "lddecodemetadata.h"
#include "logging.h"

#include "ntscencoder.h"
#include "palencoder.h"

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-chroma-encoder");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-chroma-encoder - PAL/NTSC encoder for testing\n"
                "\n"
                "(c)2019-2020 Adam Sampson\n"
                "(c)2022 Phillip Blucas\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // -- General options --

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Option to produce subcarrier-locked output (-c)
    QCommandLineOption scLockedOption(QStringList() << "c" << "sc-locked",
                                      QCoreApplication::translate("main", "Output samples are subcarrier-locked. PAL only. (default: line-locked)"));
    parser.addOption(scLockedOption);

    // Option to select color system (-f)
    QCommandLineOption systemOption(QStringList() << "f" << "system",
                                     QCoreApplication::translate("main", "Select color system, PAL or NTSC. (default PAL)"),
                                     QCoreApplication::translate("main", "system"));
    parser.addOption(systemOption);

    // Option to select chroma mode (--chroma-mode)
    QCommandLineOption chromaOption(QStringList() << "chroma-mode",
                                     QCoreApplication::translate("main", "NTSC only. Chroma encoder mode to use (wideband-yuv, wideband-yiq; default: wideband-yuv)"),
                                     QCoreApplication::translate("main", "chroma-mode"));
    parser.addOption(chromaOption);

    // -- Positional arguments --

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input RGB file (- for piped input)"));

    // Positional argument to specify output video file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output TBC file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the options from the parser
    const bool scLocked = parser.isSet(scLockedOption);

    // Get the arguments from the parser
    QString inputFileName;
    QString outputFileName;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFileName = positionalArguments.at(0);
        outputFileName = positionalArguments.at(1);
    } else {
        // Quit with error
        qCritical("You must specify the input RGB and output TBC files");
        return -1;
    }

    if (inputFileName == outputFileName) {
        // Quit with error
        qCritical("Input and output files cannot be the same");
        return -1;
    }

    VideoSystem system = PAL;
    QString systemName;
    if (parser.isSet(systemOption)) {
        systemName = parser.value(systemOption);
        if (!parseVideoSystemName(systemName.toUpper(), system)
            || (system != NTSC && system != PAL)) {
            // Quit with error
            qCritical("Unsupported color system");
            return -1;
        }
    }

    ChromaMode chromaMode = WIDEBAND_YUV;
    QString chromaName;
    if (parser.isSet(chromaOption)) {
        chromaName = parser.value(chromaOption);
        if (chromaName == "wideband-yiq") {
            chromaMode = WIDEBAND_YIQ;
        } else if (chromaName == "wideband-yuv") {
            chromaMode = WIDEBAND_YUV;
        } else {
            // Quit with error
            qCritical("Unsupported chroma encoder mode");
            return -1;
        }

    }
    // Open the input file
    QFile rgbFile(inputFileName);
    if (inputFileName == "-") {
        if (!rgbFile.open(stdin, QFile::ReadOnly)) {
            qCritical("Cannot open stdin");
            return -1;
        }
    } else {
        if (!rgbFile.open(QFile::ReadOnly)) {
            qCritical() << "Cannot open input file:" << inputFileName;
            return -1;
        }
    }

    // Open the output file
    QFile tbcFile(outputFileName);
    if (!tbcFile.open(QFile::WriteOnly)) {
        qCritical() << "Cannot open output file:" << outputFileName;
        return -1;
    }

    // Encode the data
    LdDecodeMetaData metaData;
    if( system == NTSC ) {
        NTSCEncoder encoder(rgbFile, tbcFile, metaData, chromaMode);
        if (!encoder.encode()) {
            return -1;
        }
    } else {
        PALEncoder encoder(rgbFile, tbcFile, metaData, scLocked);
        if (!encoder.encode()) {
            return -1;
        }
    }

    // Write the metadata
    if (!metaData.write(outputFileName + ".json")) {
        return -1;
    }

    // Quit with success
    return 0;
}
