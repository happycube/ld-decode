/************************************************************************

    csv.h

    ld-export-metadata - Export JSON metadata into other formats
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-export-metadata is free software: you can redistribute it and/or
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

#ifndef CSV_H
#define CSV_H

#include <QString>

#include "lddecodemetadata.h"

/*!
    Write the per-field VITS metrics as a CSV file.

    Returns true on success, false on failure.
*/
bool writeVitsCsv(LdDecodeMetaData &metaData, const QString &fileName);

/*!
    Write the per-frame VBI information as a CSV file.

    Returns true on success, false on failure.
*/
bool writeVbiCsv(LdDecodeMetaData &metaData, const QString &fileName);

#endif
