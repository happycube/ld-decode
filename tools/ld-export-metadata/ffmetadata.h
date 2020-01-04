/************************************************************************

    ffmetadata.h

    ld-export-metadata - Export JSON metadata into other formats
    Copyright (C) 2020 Adam Sampson

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

#ifndef FFMETADATA_H
#define FFMETADATA_H

#include <QString>

#include "lddecodemetadata.h"

/*!
    Write an FFMETADATA1 file containing navigation information.

    This is FFmpeg's generic metadata format, and can be used to provide
    metadata for chapter-supporting formats like Matroska.
    Format description: <https://ffmpeg.org/ffmpeg-formats.html#Metadata-1>

    Returns true on success, false on failure.
*/
bool writeFfmetadata(LdDecodeMetaData &metaData, const QString &fileName);

#endif
