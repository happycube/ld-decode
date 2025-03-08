/************************************************************************

    adfs_directory.h

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

#ifndef ADFS_DIRECTORY_H
#define ADFS_DIRECTORY_H

#include <QDebug>

#include "getbits.h"

class AdfsDirectoryEntry
{
public:
    AdfsDirectoryEntry(QByteArray data);

    // Public accessors
    QString objectName() const { return m_objectName; }
    bool readable() const { return m_readable; }
    bool writable() const { return m_writable; }
    bool locked() const { return m_locked; }
    bool isDirectory() const { return m_directory; }
    bool executeOnly() const { return m_executeOnly; }
    bool publiclyReadable() const { return m_publiclyReadable; }
    bool publiclyWritable() const { return m_publiclyWritable; }
    bool publiclyExecuteOnly() const { return m_publiclyExecuteOnly; }
    bool isPrivate() const { return m_private; }
    quint32 loadAddress() const { return m_loadAddress; }
    quint32 execAddress() const { return m_execAddress; }
    quint32 byteLength() const { return m_byteLength; }
    quint32 startSector() const { return m_startSector; }
    quint8 sequenceNumber() const { return m_sequenceNumber; }
    
    void show();

private:
    QString m_objectName;
    bool m_readable;
    bool m_writable;
    bool m_locked;
    bool m_directory;
    bool m_executeOnly;
    bool m_publiclyReadable;
    bool m_publiclyWritable;
    bool m_publiclyExecuteOnly;
    bool m_private;

    quint32 m_loadAddress;
    quint32 m_execAddress;
    quint32 m_byteLength;
    quint32 m_startSector;
    quint32 m_sequenceNumber;
};

class AdfsDirectory
{
public:
    AdfsDirectory(QByteArray sectors);

    QVector<AdfsDirectoryEntry> entries() const;

    void show();

private:
    QVector<AdfsDirectoryEntry> m_adfsDirectoryEntries;

    qint8 m_masterSequenceNumber;

};

#endif // ADFS_DIRECTORY_H