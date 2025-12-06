/******************************************************************************
 * main.cpp
 * ld-ldf-reader - LDF reader tool for ld-decode
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2019-2021 Chad Page
 * SPDX-FileCopyrightText: 2020-2022 Adam Sampson
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is derived from FFmpeg's doc/examples/demuxing_decoding.c
 * Original FFmpeg copyright applies to the corresponding parts.
 * The original FFmpeg code is licensed under LGPL-2.1-or-later
 *
 * This derived work is redistributed under the terms of the GNU General
 * Public License version 3.0 or later.
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include <QCoreApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>

#include "logging.h"
#include "ldfreader.h"

int main(int argc, char *argv[])
{
    // Set 'binary mode' for stdin and stdout on Windows
    setBinaryMode();

    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-ldf-reader");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-ldf-reader - LDF reader tool for ld-decode\n"
                "\n"
                "(c)2019-2021 Chad Page\n"
                "(c)2020-2022 Adam Sampson\n"
                "(c)2025 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Option to specify start offset in samples
    QCommandLineOption startOffsetOption(QStringList() << "s" << "start-offset",
                                         QCoreApplication::translate("main", "Start offset in samples"),
                                         QCoreApplication::translate("main", "samples"),
                                         "0");
    parser.addOption(startOffsetOption);

    // Add the input filename as a positional argument
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Input LDF file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the input filename from the parser
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() != 1) {
        qCritical("You must specify exactly one input LDF file");
        return -1;
    }
    QString inputFilename = positionalArguments.at(0);

    // Get the start offset
    bool ok;
    qint64 startOffset = parser.value(startOffsetOption).toLongLong(&ok);
    if (!ok || startOffset < 0) {
        qCritical("Start offset must be a non-negative integer");
        return -1;
    }

    // Perform the LDF reading processing
    qInfo() << "Beginning LDF reading processing...";
    LdfReader ldfReader(inputFilename, startOffset);
    if (!ldfReader.process()) return 1;

    // Quit with success
    return 0;
}