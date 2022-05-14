/************************************************************************

    testmetadata.cpp

    Unit tests for metadata classes
    Copyright (C) 2022 Adam Sampson

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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
#include <QCommandLineParser>
#include <cstdlib>
#include <iostream>

#include "lddecodemetadata.h"

int main(int argc, char *argv[])
{
    // Initialise Qt
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName("testmetadata");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription("testmetadata - unit tests for ld-decode's metadata library");
    parser.addHelpOption();
    parser.addVersionOption();

    // Test options
    QCommandLineOption statsOption(QStringList() << "s" << "stats",
                                   "parse all fields and show statistics");
    parser.addOption(statsOption);
    QCommandLineOption exitOption(QStringList() << "x" << "exit",
                                  "call exit(0) after parsing, to analyse memory usage");
    parser.addOption(exitOption);

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", "Input JSON file");

    // Positional argument to specify output video file
    parser.addPositionalArgument("output", "Output JSON file (omit to only read input)");

    // Parse the command line
    parser.process(app);

    // Process the positional args
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() < 1 || positionalArguments.count() > 2) {
        qCritical("You must specify one input file and (optionally) one output file");
        return 1;
    }

    // Read the input file
    LdDecodeMetaData metaData;
    if (!metaData.read(positionalArguments.at(0))) {
        qCritical("Unable to read input file");
        return 1;
    }

    // Show statistics
    if (parser.isSet(statsOption)) {
        // These are not very useful, but they ensure that LdDecodeMetaData has
        // actually fully parsed all of the metadata.

        qint32 numFields = metaData.getNumberOfFields();
        qint32 numMetrics = 0;
        double meanWSNR = 0.0;
        qint32 numDropOuts = 0;

        for (qint32 i = 1; i <= numFields; i++) {
            const LdDecodeMetaData::Field &field = metaData.getField(i);

            if (field.vitsMetrics.inUse) {
                ++numMetrics;
                meanWSNR += field.vitsMetrics.wSNR;
            }

            numDropOuts += field.dropOuts.size();
        }

        if (numMetrics > 0) meanWSNR /= numMetrics;

        std::cout << "fields=" << numFields << " metrics=" << numMetrics << " wSNR=" << meanWSNR << " dropouts=" << numDropOuts << "\n";
    }

    // Force an exit if requested
    if (parser.isSet(exitOption)) {
        // We use the C exit function so that C++ destructors don't get called.
        // We can then use a memory debugger like valgrind to analyse the
        // memory that was "leaked", and see how much the parser allocated.
        exit(0);
    }

    // Write the output file, if given
    if (positionalArguments.count() == 2) {
        if (!metaData.write(positionalArguments.at(1))) {
            qCritical("Unable to write output file");
            return 1;
        }
    }

    return 0;
}
