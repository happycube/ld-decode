/************************************************************************

    logging.h

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

#ifndef LOGGING_H
#define LOGGING_H

#include <QCoreApplication>
#include <QDebug>

#include <QLoggingCategory>
Q_DECLARE_LOGGING_CATEGORY(efm_process)
Q_DECLARE_LOGGING_CATEGORY(efm_efmToF3)
Q_DECLARE_LOGGING_CATEGORY(efm_f3ToF2)
Q_DECLARE_LOGGING_CATEGORY(efm_f2ToF1)
Q_DECLARE_LOGGING_CATEGORY(efm_f1ToSectors)
Q_DECLARE_LOGGING_CATEGORY(efm_f2ToAudio)
Q_DECLARE_LOGGING_CATEGORY(efm_f3ToSections)
Q_DECLARE_LOGGING_CATEGORY(efm_sectorsTodata)

// Prototypes
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg);
void setDebug(bool state);

#endif // LOGGING_H
