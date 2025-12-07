/************************************************************************

    main.cpp

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018-2025 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vbi is free software: you can redistribute it and/or
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

#include "tbc/logging.h"
#include "decoderpool.h"

int main(int argc, char *argv[])
{
    // Set 'binary mode' for stdin and stdout on Windows
    setBinaryMode();

    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-process-vbi");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode\n"
                "\n"
                "(c)2018-2025 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Option to specify a different metadata input file
    QCommandLineOption inputMetadataOption(QStringList() << "input-metadata",
                                       QCoreApplication::translate("main", "Specify the input metadata file (default input.db)"),
                                       QCoreApplication::translate("main", "filename"));
    parser.addOption(inputMetadataOption);

    // Option to specify a different metadata output file
    QCommandLineOption outputMetadataOption(QStringList() << "output-metadata",
                                        QCoreApplication::translate("main", "Specify the output metadata file (default same as input)"),
                                        QCoreApplication::translate("main", "filename"));
    parser.addOption(outputMetadataOption);

    // Option to disable metadata back-up (-n)
    QCommandLineOption showNoBackupOption(QStringList() << "n" << "nobackup",
                                       QCoreApplication::translate("main", "Do not create a backup of the input metadata"));
    parser.addOption(showNoBackupOption);

    // Option to select the number of threads (-t)
    QCommandLineOption threadsOption(QStringList() << "t" << "threads",
                                        QCoreApplication::translate("main", "Specify the number of concurrent threads (default is the number of logical CPUs)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(threadsOption);

    // Positional argument to specify input TBC file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the options from the parser
    bool noBackup = parser.isSet(showNoBackupOption);

    qint32 maxThreads = QThread::idealThreadCount();
    if (parser.isSet(threadsOption)) {
        maxThreads = parser.value(threadsOption).toInt();

        if (maxThreads < 1) {
            // Quit with error
            qCritical("Specified number of threads must be greater than zero");
            return -1;
        }
    }

    // Get the arguments from the parser
    QString inputFilename;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 1) {
        inputFilename = positionalArguments.at(0);
    } else {
        // Quit with error
        qCritical("You must specify an input TBC file");
        return -1;
    }

    // Work out the metadata filenames
    QString inputMetadataFilename = inputFilename + ".db";
    if (parser.isSet(inputMetadataOption)) {
        inputMetadataFilename = parser.value(inputMetadataOption);
    }
    QString outputMetadataFilename = inputMetadataFilename;
    if (parser.isSet(outputMetadataOption)) {
        outputMetadataFilename = parser.value(outputMetadataOption);
    }

    // Open the source video metadata
    LdDecodeMetaData metaData;
    qInfo().nospace().noquote() << "Reading metadata from " << inputMetadataFilename;
    if (!metaData.read(inputMetadataFilename)) {
        qCritical() << "Unable to open TBC metadata file";
        return 1;
    }

    // If we're overwriting the input metadata file, back it up first
    if (inputMetadataFilename == outputMetadataFilename && !noBackup) {
        qInfo().nospace().noquote() << "Backing up metadata to " << inputMetadataFilename << ".bup";
        if (!QFile::copy(inputMetadataFilename, inputMetadataFilename + ".bup")) {
            qCritical() << "Unable to back-up input metadata file - back-up already exists?";
            return 1;
        }
    }

    // Perform the processing
    qInfo() << "Beginning VBI processing...";
    DecoderPool decoderPool(inputFilename, outputMetadataFilename, maxThreads, metaData);
    if (!decoderPool.process()) return 1;

    // Quit with success
    return 0;
}
