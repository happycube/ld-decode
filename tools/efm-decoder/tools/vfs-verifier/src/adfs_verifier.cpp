/************************************************************************

    adfs_verifier.cpp

    vfs-verifier - Acorn VFS (Domesday) image verifier
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    This application is free software: you can redistribute it and/or
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

#include "adfs_verifier.h"

AdfsVerifier::AdfsVerifier()
{}

bool AdfsVerifier::process(const QString &filename, const QString &bsmFilename)
{
    // Open the VFS image file
    m_image.open(filename);
    if (!m_image.isValid()) {
        qCritical() << "AdfsVerifier::process() - Could not open VFS image file" << filename;
        return false;
    }

    // Open the BSM file
    BadSectors badSectors;
    if (!badSectors.open(bsmFilename)) {
        qCritical() << "AdfsVerifier::process() - Could not open BSM metadata file" << bsmFilename;
        return false;
    }

    // Read the free space map
    AdfsFsm adfsFsm(m_image.readSectors(0, 2, true));

    // Read the root directory
    AdfsDirectory adfsDirectory(m_image.readSectors(2, 5, false));

    QVector<quint32> usedEfmSectors;
    QVector<quint32> errorEfmSectors;

    // Verify the root directory entries one at a time
    for (int i = 0; i < adfsDirectory.entries().size(); ++i) {
        
        qint32 startSector = adfsDirectory.entries().at(i).startSector();
        qint32 byteLength = adfsDirectory.entries().at(i).byteLength();
        qint32 sectorLength = (byteLength + 255) / 256;

        // Show the file data
        qDebug() << "Directory entry" << i << "start sector" << startSector << "length" << sectorLength << "sectors - object name" << adfsDirectory.entries().at(i).objectName();

        // Ensure that all the used sectors are not in the bad sector list
        for (int j = 0; j < sectorLength; ++j) {
            quint32 efmSector = m_image.adfsSectorToEfmSector(startSector + j);
            if (badSectors.isSectorBad(efmSector) && !errorEfmSectors.contains(efmSector)) {
                qWarning().noquote() << "AdfsVerifier::process() - Bad EFM sector" << efmSector << "found in file" << adfsDirectory.entries().at(i).objectName() << "ADFS sector" << toString24bits(startSector + j);
                errorEfmSectors.append(efmSector);

                // Display the bad sector data
                QByteArray badSectorData = m_image.readSectors(efmSector,1, false);
                hexDump(badSectorData, startSector + j);
            }
        }
    }

    // Did verification fail?
    if (errorEfmSectors.size() > 0) {
        qInfo() << "AdfsVerifier::process() - Verification failed -" << errorEfmSectors.size() << "bad sectors found in VFS image file" << filename;
    } else {
        qInfo() << "AdfsVerifier::process() - Verification passed - no bad sectors found in VFS image file" << filename;
    }

    // Close the image
    m_image.close();
    badSectors.close();
    return true;
}

// Display a hex dump of a series of ADFS sectors
void AdfsVerifier::hexDump(QByteArray &data, qint32 startSector) const
{
    const int bytesPerLine = 32;
    for (int i = 0; i < data.size(); i += bytesPerLine) {
        QString line = QString("%1: ").arg(i, 8, 16, QChar('0'));
        
        // Hex values
        for (int j = 0; j < bytesPerLine; ++j) {
            if (i + j < data.size())
                line += QString("%1 ").arg(static_cast<quint8>(data[i + j]), 2, 16, QChar('0'));
            else
                line += "   ";
        }
        
        line += " |";
        
        // ASCII representation
        for (int j = 0; j < bytesPerLine && i + j < data.size(); ++j) {
            char c = data[i + j];
            line += QChar((c >= 32 && c <= 126) ? c : '.');
        }
        line += "|";
        
        qDebug().noquote() << line;
    }
}
