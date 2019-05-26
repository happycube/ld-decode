/************************************************************************

    logging.cpp

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

#include "logging.h"

Q_LOGGING_CATEGORY(efm_process, "efm.process")
Q_LOGGING_CATEGORY(efm_efmToF3, "efm.efmToF3")
Q_LOGGING_CATEGORY(efm_f3ToF2, "efm.f3ToF2")
Q_LOGGING_CATEGORY(efm_f2ToF1, "efm.f2ToF1")
Q_LOGGING_CATEGORY(efm_f1ToSectors, "efm.f1ToSectors")
Q_LOGGING_CATEGORY(efm_f2ToAudio, "efm.f2ToAudio")
Q_LOGGING_CATEGORY(efm_f3ToSections, "efm.f3ToSections")
Q_LOGGING_CATEGORY(efm_sectorsTodata, "efm.sectorsTodata")

// Global for debug output
static bool showDebug = false;

// Qt debug message handler
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Use:
    // context.file - to show the filename
    // context.line - to show the line number
    // context.function - to show the function name

    QByteArray localMsg = msg.toLocal8Bit();
    switch (type) {
    case QtDebugMsg: // These are debug messages meant for developers
        if (showDebug) {
            // If the code was compiled as 'release' the context.file will be NULL
            if (context.file != nullptr) fprintf(stderr, "Debug (%s): [%s:%d] %s\n", context.category, context.file, context.line, localMsg.constData());
            else fprintf(stderr, "Debug (%s): %s\n", context.category, localMsg.constData());
        }
        break;
    case QtInfoMsg: // These are information messages meant for end-users
        if (context.file != nullptr) fprintf(stderr, "Info (%s): [%s:%d] %s\n", context.category, context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Info: %s\n", localMsg.constData());
        break;
    case QtWarningMsg:
        if (context.file != nullptr) fprintf(stderr, "Warning (%s): [%s:%d] %s\n", context.category, context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Warning: %s\n", localMsg.constData());
        break;
    case QtCriticalMsg:
        if (context.file != nullptr) fprintf(stderr, "Critical (%s): [%s:%d] %s\n", context.category, context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Critical: %s\n", localMsg.constData());
        break;
    case QtFatalMsg:
        if (context.file != nullptr) fprintf(stderr, "Fatal (%s): [%s:%d] %s\n", context.category, context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Fatal: %s\n", localMsg.constData());
        abort();
    }
}

void setDebug(bool state)
{
    showDebug = state;
}
