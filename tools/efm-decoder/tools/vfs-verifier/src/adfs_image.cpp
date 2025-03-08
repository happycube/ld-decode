/************************************************************************

    adfs_image.cpp

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

#include "adfs_image.h"

AdfsImage::AdfsImage() :
    m_isValid(false)
{}

bool AdfsImage::open(QString filename)
{
    // Open the input file
    m_file = new QFile(filename);
    if (!m_file->open(QIODevice::ReadOnly)) {
        qCritical() << "AdfsImage::open() - Could not open file" << filename << "for reading";
        return false;
    }
    qDebug() << "AdfsImage::open() - Opened file" << filename << "for reading";

    m_isValid = true;

    // Locate sector 0 position
    findSector0();

    return true;
}

void AdfsImage::close()
{
    if (m_file->isOpen()) {
        m_file->close();
        qDebug() << "AdfsImage::close() - Closed file" << m_file->fileName();
    }
}

QByteArray AdfsImage::readSectors(quint64 sector, quint64 count, bool verifyChecksums)
{
    QByteArray buffer;

    if (!m_file->isOpen()) {
        qCritical() << "AdfsImage::readSectors() - File is not open";
        return buffer;
    }

    // Seek to the correct position
    m_file->seek(m_sector0Position + (sector * 256));
    buffer = m_file->read(count * 256);

    if (verifyChecksums) {
        // Verify the checksums of the read sectors
        for (quint64 i = 0; i < count; ++i) {
            if (static_cast<quint16>(buffer.at((i * 256) + 255)) != calculateChecksum(buffer.mid(i * 256, 256))) {
                qCritical() << "AdfsImage::readSectors() - Checksum failed for sector" << sector + i
                    << "checksum" << static_cast<quint16>(buffer.at((i * 256) + 255)) << "expected" << calculateChecksum(buffer.mid(i * 256, 256));
            }
        }
    }

    return buffer;
}

bool AdfsImage::isValid() const
{
    return m_isValid;
}

quint16 AdfsImage::calculateChecksum(const QByteArray &buffer)
{
    quint16 sum = 255;
    for (int a = 254; a >= 0; --a) {
        if (sum > 255) {
            sum = (sum & 0xff) + 1;
        }
        sum += static_cast<quint16>(buffer[a]);
    }

    return (sum+1) & 0xff;
}

void AdfsImage::findSector0()
{
    // Search for the ADFS signature of "Hugo" that marks the start of the root directory
    // This is an ASCII string, so we can search for it directly
    // Note: This is logical sector 2, so there are 2 sectors before it that must be captured
    while (!m_file->atEnd()) {
        QByteArray buffer = m_file->read(1);
        if (buffer == "H") {
            // Found the first character of the signature, so read the next 3 characters
            buffer += m_file->read(3);
            if (buffer == "Hugo") {
                // Found the signature
                m_sector0Position = m_file->pos() - 5;
                qDebug().nospace().noquote() << "AdfsImage::findSector0() - Found ADFS signature Hugo at offset 0x" << QString::number(m_sector0Position, 16).toUpper();
                break;
            }
        }
    }

    if (m_sector0Position != 0) {
        // Seek back to sector 0 and set the position correctly
        // Sectors are 256 bytes, so we need to seek back 512 bytes
        m_file->seek(m_sector0Position - 512);
        m_sector0Position -= 512;
    } else {
        // Not a valid image file
        qDebug() << "AdfsImage::findSector0() - Could not find ADFS signature Hugo in file" << m_file->fileName() << "- input file is not a valid ADFS image";
        m_isValid = false;
    }
}

quint32 AdfsImage::adfsSectorToEfmSector(quint32 adfsSector)
{
    // ADFS sectors are 256 bytes, EFM sectors are 2048 bytes
    // EFM sector 0 is at the beginning of the file, so we
    // have to offset by the sector 0 position
    return ((adfsSector * 256) + m_sector0Position) / 2048;

}