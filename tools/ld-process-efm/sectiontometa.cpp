/************************************************************************

    sectiontometa.cpp

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

#include "sectiontometa.h"

SectionToMeta::SectionToMeta()
{
    // Subcode block Q mode counters
    qMode0Count = 0;
    qMode1Count = 0;
    qMode2Count = 0;
    qMode3Count = 0;
    qMode4Count = 0;
    qModeICount = 0;
}

// Method to write status information to qInfo
void SectionToMeta::reportStatus(void)
{
    qint32 totalSections = qMode0Count + qMode1Count + qMode2Count + qMode3Count + qMode4Count + qModeICount;

    qInfo() << "Sections to metadata processing:";
    qInfo() << "  Total number of sections processed =" << totalSections << "(" << totalSections * 98 << "F3 frames )";
    qInfo() << "  Q Mode 0 sections =" << qMode0Count << "(Data)";
    qInfo() << "  Q Mode 1 sections =" << qMode1Count << "(CD Audio)";
    qInfo() << "  Q Mode 2 sections =" << qMode2Count << "(Disc ID)";
    qInfo() << "  Q Mode 3 sections =" << qMode3Count << "(Track ID)";
    qInfo() << "  Q Mode 4 sections =" << qMode4Count << "(Non-CD Audio)";
    qInfo() << "  Sections with failed Q CRC =" << qModeICount;
    qInfo() << "";
}

// Method to process the decoded sections
void SectionToMeta::process(QVector<Section> sections)
{
    // Did we get any sections?
    if (sections.size() != 0) {
        for (qint32 i = 0; i < sections.size(); i++) {
            qint32 qMode = sections[i].getQMode();

            // Depending on the section Q Mode, process the section
            if (qMode == 0) {
                // Data
                qMode0Count++;
                qDebug() << "SectionToMeta::process(): Section Q mode 0 - Data";
            } else if (qMode == 1) {
                // CD Audio
                qMode1Count++;
                Section::QMetadata qMetaData = sections[i].getQMetadata();

                if (qMetaData.qMode4.isLeadIn) {
                    // Lead in
                    qDebug() << "SectionToMeta::process(): Section Q mode 1 - CD Audio - Lead in: Track =" << qMetaData.qMode4.trackNumber << "- point =" << qMetaData.qMode4.point <<
                                "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                } else if (qMetaData.qMode4.isLeadOut) {
                    // Lead out
                    if (qMetaData.qMode4.x == 0) {
                        // Encoding paused
                        qDebug() << "SectionToMeta::process(): Section Q mode 1 - CD Audio - Lead out (Encoding paused): Track =" << qMetaData.qMode4.trackNumber <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    } else {
                        // Encoding running
                        qDebug() << "SectionToMeta::process(): Section Q mode 1 - CD Audio - Lead out (Encoding running): Track =" << qMetaData.qMode4.trackNumber <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    }
                } else {
                    // Audio
                    if (qMetaData.qMode4.x == 0) {
                        // Encoding paused
                        qDebug() << "SectionToMeta::process(): Section Q mode 1 - CD Audio - Audio (Encoding paused): Track =" << qMetaData.qMode4.trackNumber << "- Subdivision =" << qMetaData.qMode4.x <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    } else {
                        // Encoding running
                        qDebug() << "SectionToMeta::process(): Section Q mode 1 - CD Audio - Audio (Encoding running): Track =" << qMetaData.qMode4.trackNumber << "- Subdivision =" << qMetaData.qMode4.x <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    }
                }
            } else if (qMode == 2) {
                // Unique ID for disc
                qMode2Count++;
                qDebug() << "SectionToMeta::process(): Section Q mode 2 - Unique ID for disc";
            } else if (qMode == 3) {
                // Unique ID for track
                qMode3Count++;
                qDebug() << "SectionToMeta::process(): Section Q mode 3 - Unique ID for track";
            } else if (qMode == 4) {
                // 4 = non-CD Audio (LaserDisc)
                qMode4Count++;
                Section::QMetadata qMetaData = sections[i].getQMetadata();

                if (qMetaData.qMode4.isLeadIn) {
                    // Lead in
                    qDebug() << "SectionToMeta::process(): Section Q mode 4 - LD Audio - Lead in: Track =" << qMetaData.qMode4.trackNumber << "- point =" << qMetaData.qMode4.point <<
                                "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                } else if (qMetaData.qMode4.isLeadOut) {
                    // Lead out
                    if (qMetaData.qMode4.x == 0) {
                        // Encoding paused
                        qDebug() << "SectionToMeta::process(): Section Q mode 4 - LD Audio - Lead out (Encoding paused): Track =" << qMetaData.qMode4.trackNumber <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    } else {
                        // Encoding running
                        qDebug() << "SectionToMeta::process(): Section Q mode 4 - LD Audio - Lead out (Encoding running): Track =" << qMetaData.qMode4.trackNumber <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    }
                } else {
                    // Audio
                    if (qMetaData.qMode4.x == 0) {
                        // Encoding paused
                        qDebug() << "SectionToMeta::process(): Section Q mode 4 - LD Audio - Audio (Encoding paused): Track =" << qMetaData.qMode4.trackNumber << "- Subdivision =" << qMetaData.qMode4.x <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    } else {
                        // Encoding running
                        qDebug() << "SectionToMeta::process(): Section Q mode 4 - LD Audio - Audio (Encoding running): Track =" << qMetaData.qMode4.trackNumber << "- Subdivision =" << qMetaData.qMode4.x <<
                                    "- Time =" << qMetaData.qMode4.trackTime.getTimeAsQString() << "- Disc Time =" << qMetaData.qMode4.discTime.getTimeAsQString();
                    }
                }
            } else {
                // Invalid section
                qModeICount++;
                qDebug() << "SectionToMeta::process(): Invalid section";
            }
        }
    }
}
