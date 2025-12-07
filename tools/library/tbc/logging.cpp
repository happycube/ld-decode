/************************************************************************

    logging.cpp

    ld-decode-tools TBC library
    Copyright (C) 2018-2020 Simon Inns
    Copyright (C) 2021 Adam Sampson

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

#include "tbc/logging.h"
#include <QDateTime>
#include <QTextStream>

// Global for debug output
static bool showDebug = false;
static bool saveDebug = false;
static bool quietDebug = false;
static bool firstDebug = true;
static QFile *debugFile;

// Define the standard logging command line options
static QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                          QCoreApplication::translate("main", "Show application debug messages"));
static QCommandLineOption setQuietOption({"q", "quiet"},
                                         QCoreApplication::translate("main", "Suppress info and warning messages"));

// Qt debug message handler
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Use:
    // context.file - to show the filename
    // context.line - to show the line number
    // context.function - to show the function name

    QString outputMessage;
    switch (type) {
    case QtDebugMsg: // These are debug messages meant for developers
        outputMessage = "Debug";
        break;
    case QtInfoMsg: // These are information messages meant for end-users
        outputMessage = "Info";
        break;
    case QtWarningMsg:
        outputMessage = "Warning";
        break;
    case QtCriticalMsg:
        outputMessage = "Critical";
        break;
    case QtFatalMsg:
        outputMessage = "Fatal";
        break;
    }

    // If the code was compiled as 'release' the context.file will be NULL
    if (context.file != nullptr) {
        outputMessage += QString(": [%1:%2] %3\n").arg(context.file).arg(context.line).arg(msg);
    } else {
        outputMessage += QString(": %1\n").arg(msg);
    }

    // If quiet mode is set, suppress all output
    if (!quietDebug) {
        // First debug output?
        if (firstDebug && showDebug) {
            firstDebug = false;
            QTextStream(stderr) << QString("Debug: Version - Git branch: %1 / commit: %2\n").arg(APP_BRANCH, APP_COMMIT);
        }

        // Display the output message on stderr
        // Show debug messages only when enabled, otherwise warnings/info/critical/fatal always
        if (showDebug || (type != QtDebugMsg)) QTextStream(stderr) << outputMessage;
    }

    // Optional output to file
    if (saveDebug) {
        QTextStream(debugFile) << outputMessage;
    }

    // If the error was fatal, then we should abort
    if (type == QtFatalMsg) abort();
}

// Application-level debug output that is not suppressed in release builds
void tbcDebug(const QString &msg)
{
    if (!showDebug || quietDebug) return;

    // First debug output?
    if (firstDebug) {
        firstDebug = false;
        QTextStream(stderr) << QString("[%1] Debug: Version - Git branch: %2 / commit: %3\n")
                               .arg(QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz"),
                                    APP_BRANCH,
                                    APP_COMMIT);
    }

    const QString timestamp = QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz");
    QString formatted = QString("[%1] Debug: %2\n").arg(timestamp, msg);
    QTextStream(stderr) << formatted;

    if (saveDebug) {
        QTextStream(debugFile) << formatted;
    }
}

// Stream-style helper implementation -----------------------------------------------------------

TbcDebugStream::TbcDebugStream()
    : buffer(), enabled(getDebugState()), debug(&buffer)
{
    // Match qDebug default spacing
    debug.setAutoInsertSpaces(true);
}

TbcDebugStream::~TbcDebugStream()
{
    if (enabled) {
        tbcDebug(buffer);
    }
}

TbcDebugStream &TbcDebugStream::nospace()
{
    debug.nospace();
    return *this;
}

TbcDebugStream &TbcDebugStream::noquote()
{
    debug.noquote();
    return *this;
}

TbcDebugStream tbcDebugStream()
{
    return TbcDebugStream();
}

// Open debug file
void openDebugFile(QString filename)
{
    // Open output files for writing
    debugFile = new QFile(filename);
    if (!debugFile->open(QIODevice::WriteOnly)) {
        // Failed to open source sample file
        tbcDebugStream() << "Could not open" << filename << "as debug output file";
    } else saveDebug = true;
}

// Close debug file
void closeDebugFile(void)
{
    if (saveDebug) debugFile->close();
}

// Control the show debug flag (debug to stderr if true)
void setDebug(bool state)
{
    showDebug = state;
}

// Control the quiet flag (if set all output is suppressed)
void setQuiet(bool state)
{
    quietDebug = state;
}

// Ensure the stdout/stdin file descriptors are in binary mode
void setBinaryMode(void)
{
#ifdef _WIN32
    _setmode(_fileno(stdout), O_BINARY);
    _setmode(_fileno(stdin), O_BINARY);	
#endif
}

// Method to add the standard debug options to the command line parser
void addStandardDebugOptions(QCommandLineParser &parser)
{
    // Option to show debug (-d / --debug) - application messages only
    parser.addOption(showDebugOption);

    // Option to set quiet mode (-q)
    parser.addOption(setQuietOption);
}

// Method to process the standard debug options
void processStandardDebugOptions(QCommandLineParser &parser)
{
    // Process any options added by the addStandardDebugOptions method
    if (parser.isSet(showDebugOption)) setDebug(true); else setDebug(false);
    if (parser.isSet(setQuietOption)) setQuiet(true); else setQuiet(false);
}

// Method to get the current debug logging state
bool getDebugState()
{
    return showDebug;
}
