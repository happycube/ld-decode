/************************************************************************

    adfs_fsm.h

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

#ifndef ADFS_FSM_H
#define ADFS_FSM_H

#include <QDebug>
#include <QVector>

#include "getbits.h"

class AdfsFsm
{
public:
    AdfsFsm(QByteArray sectors);

    quint32 size() const { return m_freeSpaceMap.size(); }
    quint32 freeSpace(quint32 index) const { return m_freeSpaceMap.at(index); }
    quint32 freeSpaceLength(quint32 index) const { return m_freeSpaceLengths.at(index); }

private:
    QVector<quint32> m_freeSpaceMap;
    QVector<quint32> m_freeSpaceLengths;
    QString m_RiscOsDiscName;
    quint16 m_discId;
    quint32 m_numberOfSectors;
    quint8 m_lengthOfFreeSpaceMap;

    void showStarFree();
    void showStarMap();
    void show();
};

#endif // ADFS_FSM_H