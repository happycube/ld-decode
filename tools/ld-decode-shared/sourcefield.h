/************************************************************************

    sourceframe.h

    ld-decode-tools shared library
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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

#ifndef SOURCEFIELD_H
#define SOURCEFIELD_H

#include "ld-decode-shared_global.h"

#include <QObject>
#include <QDebug>

class LDDECODESHAREDSHARED_EXPORT SourceField : public QObject
{
    Q_OBJECT

public:
    explicit SourceField(QObject *parent = nullptr);
    void setFieldData(QByteArray fieldGreyscaleData);
    QByteArray getFieldData(void);

private:
    QByteArray greyScaleData;
    bool isFieldValid;

    void configureParameters(void);

};

#endif // SOURCEFIELD_H
