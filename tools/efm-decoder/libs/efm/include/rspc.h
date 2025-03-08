/************************************************************************

    rspc.h

    EFM-library - Reed-Solomon Product-like Code (RSPC) functions
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

#ifndef RSPC_H
#define RSPC_H

#include <QDebug>

class Rspc
{
public:
    Rspc();
    void qParityEcc(QByteArray &inputData, QByteArray &errorData, bool m_showDebug);
    void pParityEcc(QByteArray &inputData, QByteArray &errorData, bool m_showDebug);
};

#endif // RSPC_H