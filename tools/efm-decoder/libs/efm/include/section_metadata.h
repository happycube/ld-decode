/************************************************************************

    section_metadata.h

    EFM-library - Section metadata classes
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

#ifndef SECTION_METADATA_H
#define SECTION_METADATA_H

#include <QDebug>
#include <QVector>
#include <QtGlobal>
#include <QDataStream>

// Section time class - stores ECMA-130 frame time as minutes, seconds, and frames (1/75th of a
// second)
class SectionTime 
{
public:
    SectionTime();
    explicit SectionTime(qint32 frames);
    SectionTime(quint8 minutes, quint8 seconds, quint8 frames);

    qint32 frames() const { return m_frames; }
    void setFrames(qint32 frames);
    void setTime(quint8 minutes, quint8 seconds, quint8 frames);

    qint32 minutes() const { return m_frames / (75 * 60); }
    qint32 seconds() const { return (m_frames / 75) % 60; }
    qint32 frameNumber() const { return m_frames % 75; }

    QString toString() const;
    QByteArray toBcd() const;

    bool operator==(const SectionTime &other) const { return m_frames == other.m_frames; }
    bool operator!=(const SectionTime &other) const { return m_frames != other.m_frames; }
    bool operator<(const SectionTime &other) const { return m_frames < other.m_frames; }
    bool operator>(const SectionTime &other) const { return m_frames > other.m_frames; }
    bool operator<=(const SectionTime &other) const { return !(*this > other); }
    bool operator>=(const SectionTime &other) const { return !(*this < other); }
    SectionTime operator+(const SectionTime &other) const
    {
        return SectionTime(m_frames + other.m_frames);
    }
    SectionTime operator-(const SectionTime &other) const
    {
        return SectionTime(m_frames - other.m_frames);
    }
    SectionTime &operator++()
    {
        ++m_frames;
        return *this;
    }
    SectionTime operator++(int)
    {
        SectionTime tmp(*this);
        m_frames++;
        return tmp;
    }
    SectionTime &operator--()
    {
        --m_frames;
        return *this;
    }
    SectionTime operator--(int)
    {
        SectionTime tmp(*this);
        m_frames--;
        return tmp;
    }

    SectionTime operator+(int frames) const
    {
        return SectionTime(m_frames + frames);
    }

    SectionTime operator-(int frames) const
    {
        return SectionTime(m_frames - frames);
    }

    friend QDataStream &operator>>(QDataStream &in, SectionTime &time);
    friend QDataStream &operator<<(QDataStream &out, const SectionTime &time);

private:
    qint32 m_frames;
    static quint8 intToBcd(quint32 value);
};

// Section type class - stores the type of section (LEAD_IN, LEAD_OUT, USER_DATA)
class SectionType
{
public:
    enum Type { LeadIn, LeadOut, UserData };

    SectionType() : m_type(UserData) { }
    explicit SectionType(Type type) : m_type(type) { }

    Type type() const { return m_type; }
    void setType(Type type) { m_type = type; }

    QString toString() const;

    bool operator==(const SectionType &other) const { return m_type == other.m_type; }
    bool operator!=(const SectionType &other) const { return m_type != other.m_type; }

    friend QDataStream &operator>>(QDataStream &in, SectionType &type);
    friend QDataStream &operator<<(QDataStream &out, const SectionType &type);

private:
    Type m_type;
};

// Section metadata class - stores the Section type, Section time, absolute Section time, and track
// number This data is common for Data24, F1 and F2 Sections
class SectionMetadata
{
public:
    enum QMode { QMode1, QMode2, QMode3, QMode4 };

    SectionMetadata() :
        m_sectionType(SectionType::UserData),
        m_sectionTime(SectionTime()),
        m_absoluteSectionTime(SectionTime()),
        m_trackNumber(0),
        m_isValid(false),
        m_isAudio(true),
        m_isCopyProhibited(true),
        m_hasPreemphasis(false),
        m_is2Channel(true),
        m_pFlag(true),
        m_qMode(QMode1),
        m_upcEanCode(0),
        m_isrcCode(0),
        m_isRepaired(false)
    {}

    SectionType sectionType() const { return m_sectionType; }
    void setSectionType(const SectionType &sectionType, quint8 trackNumber);

    SectionTime sectionTime() const { return m_sectionTime; }
    void setSectionTime(const SectionTime &sectionTime) { m_sectionTime = sectionTime; }

    SectionTime absoluteSectionTime() const { return m_absoluteSectionTime; }
    void setAbsoluteSectionTime(const SectionTime &sectionTime)
    {
        m_absoluteSectionTime = sectionTime;
    }

    quint8 trackNumber() const { return m_trackNumber; }
    void setTrackNumber(quint8 trackNumber);

    QMode qMode() const { return m_qMode; }
    void setQMode(QMode qMode) { m_qMode = qMode; }

    bool isAudio() const { return m_isAudio; }
    void setAudio(bool audio) { m_isAudio = audio; }
    bool isCopyProhibited() const { return m_isCopyProhibited; }
    void setCopyProhibited(bool copyProhibited) { m_isCopyProhibited = copyProhibited; }
    bool hasPreemphasis() const { return m_hasPreemphasis; }
    void setPreemphasis(bool preemphasis) { m_hasPreemphasis = preemphasis; }
    bool is2Channel() const { return m_is2Channel; }
    void set2Channel(bool is2Channel) { m_is2Channel = is2Channel; }

    void setUpcEanCode(quint32 upcEanCode) { m_upcEanCode = upcEanCode; }
    quint32 upcEanCode() const { return m_upcEanCode; }
    void setIsrcCode(quint32 isrcCode) { m_isrcCode = isrcCode; }
    quint32 isrcCode() const { return m_isrcCode; }

    bool pFlag() const { return m_pFlag; }
    void setPFlag(bool pFlag) { m_pFlag = pFlag; }

    bool isValid() const { return m_isValid; }
    void setValid(bool valid) { m_isValid = valid; }

    bool isRepaired() const { return m_isRepaired; }
    void setRepaired(bool repaired) { m_isRepaired = repaired; }

    friend QDataStream &operator>>(QDataStream &in, SectionMetadata &metadata);
    friend QDataStream &operator<<(QDataStream &out, const SectionMetadata &metadata);

private:
    // P-Channel metadata
    bool m_pFlag;

    // Q-Channel metadata
    QMode m_qMode;
    SectionType m_sectionType;
    SectionTime m_sectionTime;
    SectionTime m_absoluteSectionTime;
    quint8 m_trackNumber;
    bool m_isValid;
    bool m_isRepaired;

    // Q-Channel control metadata
    bool m_isAudio;
    bool m_isCopyProhibited;
    bool m_hasPreemphasis;
    bool m_is2Channel;

    // Q-Channel mode 2 and 3 metadata
    quint32 m_upcEanCode;
    quint32 m_isrcCode;
};

#endif // SECTION_METADATA_H