/************************************************************************

    filters.h

    ld-decode-tools TBC library
    Copyright (C) 2018-2019 Simon Inns

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

#ifndef FILTERS_H
#define FILTERS_H

#include <QObject>
#include <QVector>
#include <QDebug>

class Filters : public QObject
{
    Q_OBJECT
public:
    explicit Filters(QObject *parent = nullptr);

    void palLumaFirFilter(quint16 *data, qint32 dataPoints);
    void palLumaFirFilter(QVector<qint32> &data);

    void ntscLumaFirFilter(quint16 *data, qint32 dataPoints);
    void ntscLumaFirFilter(QVector<qint32> &data);

private:
    void palLumaFirFilterDouble(QVector<double> &floatData);
    void ntscLumaFirFilterDouble(QVector<double> &floatData);
};

#endif // FILTERS_H
