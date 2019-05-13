/************************************************************************

    sectiontometa.h

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

#ifndef SECTIONTOMETA_H
#define SECTIONTOMETA_H

#include <QCoreApplication>
#include <QDebug>

#include "section.h"

class SectionToMeta
{
public:
    SectionToMeta();

    bool openOutputFile(QString filename);
    void closeOutputFile(void);

    void reportStatus(void);
    void process(QVector<Section> sections);

private:
    qint32 qMode0Count;
    qint32 qMode1Count;
    qint32 qMode2Count;
    qint32 qMode3Count;
    qint32 qMode4Count;
    qint32 qModeICount;

    QString jsonFilename;

    QVector<qint32> qMetaModeVector;
    QVector<Section::QMetadata> qMetaDataVector;
};

#endif // SECTIONTOMETA_H
