/************************************************************************

    sectorstodata.cpp

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

#include "sectorstodata.h"

SectorsToData::SectorsToData()
{
    sectorsOut = 0;
}

// Method to write status information to qInfo
void SectorsToData::reportStatus(void)
{
    qInfo() << "Sectors to data converter:";
    qInfo() << "  Total number of sectors written =" << sectorsOut;
}

// Method to open the data output file
bool SectorsToData::openOutputFile(QString filename)
{
    // Open output file for writing
    outputFileHandle = new QFile(filename);
    if (!outputFileHandle->open(QIODevice::WriteOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << outputFileHandle << "as data output file";
        return false;
    }
    qDebug() << "SectorsToData::openOutputFile(): Opened" << filename << "as data output file";

    // Exit with success
    return true;
}

// Method to close the data output file
void SectorsToData::closeOutputFile(void)
{
    // Is an output file open?
    if (outputFileHandle != nullptr) {
        outputFileHandle->close();
    }

    // Clear the file handle pointer
    delete outputFileHandle;
    outputFileHandle = nullptr;
}

// Convert sectors into data
void SectorsToData::convert(QVector<Sector> sectors)
{
    for (qint32 i = 0; i < sectors.size(); i++) {
        outputFileHandle->write(sectors[i].getUserData());
        sectorsOut++;
    }
}
