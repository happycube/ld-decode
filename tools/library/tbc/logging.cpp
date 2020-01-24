/************************************************************************

    logging.cpp

    ld-decode-tools TBC library
    Copyright (C) 2018-2020 Simon Inns

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

#include "logging.h"

// Global for debug output
static bool showDebug = false;
static bool saveDebug = false;
static QFile *debugFile;

// Qt debug message handler
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Use:
    // context.file - to show the filename
    // context.line - to show the line number
    // context.function - to show the function name

    QByteArray localMsg = msg.toLocal8Bit();
    QString outputMessage;

    switch (type) {
    case QtDebugMsg: // These are debug messages meant for developers
        // If the code was compiled as 'release' the context.file will be NULL
        if (context.file != nullptr) outputMessage.sprintf("Debug: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else outputMessage.sprintf("Debug: %s\n", localMsg.constData());
        break;
    case QtInfoMsg: // These are information messages meant for end-users
        if (context.file != nullptr) outputMessage.sprintf("Info: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else outputMessage.sprintf("Info: %s\n", localMsg.constData());
        break;
    case QtWarningMsg:
        if (context.file != nullptr) outputMessage.sprintf("Warning: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else outputMessage.sprintf("Warning: %s\n", localMsg.constData());
        break;
    case QtCriticalMsg:
        if (context.file != nullptr) outputMessage.sprintf("Critical: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else outputMessage.sprintf("Critical: %s\n", localMsg.constData());
        break;
    case QtFatalMsg:
        if (context.file != nullptr) outputMessage.sprintf("Fatal: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else outputMessage.sprintf("Fatal: %s\n", localMsg.constData());
        break;
    }

    // Display the output message on stderr
    if (showDebug || (type != QtDebugMsg)) QTextStream(stderr) << outputMessage;

    // Optional output to file
    if (saveDebug) QTextStream(debugFile) << outputMessage;

    // If the error was fatal, then we should abort
    if (type == QtFatalMsg) abort();
}

// Open debug file
void openDebugFile(QString filename)
{
    // Open output files for writing
    debugFile = new QFile(filename);
    if (!debugFile->open(QIODevice::WriteOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << filename << "as debug output file";
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
