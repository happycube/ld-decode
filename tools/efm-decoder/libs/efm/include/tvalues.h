/************************************************************************

    tvalues.h

    EFM-library - T-values to bit string conversion
    Copyright (C) 2025 Simon Inns

    This file is part of EFM-Tools.

    This is free software: you can redistribute it and/or
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

#ifndef TVALUES_H
#define TVALUES_H

#include <cstdint>
#include <QString>
#include <QVector>

class Tvalues
{
public:
    Tvalues();

    QString tvaluesToBitString(const QByteArray &tvalues);

    quint32 invalidHighTValuesCount() const { return m_invalidHighTValuesCount; }
    quint32 invalidLowTValuesCount() const { return m_invalidLowTValuesCount; }
    quint32 validTValuesCount() const { return m_validTValuesCount; }

private:
    quint32 m_invalidHighTValuesCount;
    quint32 m_invalidLowTValuesCount;
    quint32 m_validTValuesCount;
};

#endif // TVALUES_H