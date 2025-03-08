/************************************************************************

    sector.h

    EFM-library - EFM Section classes
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

#ifndef SECTOR_H
#define SECTOR_H

#include <QDebug>
#include <QByteArray>

// Sector Address class - stores ECMA-130 sector address in minutes, seconds, and frames
// (1/75th of a second)
class SectorAddress 
{
public:
SectorAddress();
    explicit SectorAddress(qint32 frames);
    SectorAddress(quint8 minutes, quint8 seconds, quint8 frames);

    qint32 address() const { return m_address; }
    void setAddress(qint32 frames);
    void setTime(quint8 minutes, quint8 seconds, quint8 frames);

    qint32 minutes() const { return m_address / (75 * 60); }
    qint32 seconds() const { return (m_address / 75) % 60; }
    qint32 frameNumber() const { return m_address % 75; }

    QString toString() const;

    bool operator==(const SectorAddress &other) const { return m_address == other.m_address; }
    bool operator!=(const SectorAddress &other) const { return m_address != other.m_address; }
    bool operator<(const SectorAddress &other) const { return m_address < other.m_address; }
    bool operator>(const SectorAddress &other) const { return m_address > other.m_address; }
    bool operator<=(const SectorAddress &other) const { return !(*this > other); }
    bool operator>=(const SectorAddress &other) const { return !(*this < other); }
    SectorAddress operator+(const SectorAddress &other) const
    {
        return SectorAddress(m_address + other.m_address);
    }
    SectorAddress operator-(const SectorAddress &other) const
    {
        return SectorAddress(m_address - other.m_address);
    }
    SectorAddress &operator++()
    {
        ++m_address;
        return *this;
    }
    SectorAddress operator++(int)
    {
        SectorAddress tmp(*this);
        m_address++;
        return tmp;
    }
    SectorAddress &operator--()
    {
        --m_address;
        return *this;
    }
    SectorAddress operator--(int)
    {
        SectorAddress tmp(*this);
        m_address--;
        return tmp;
    }

    SectorAddress operator+(int frames) const
    {
        return SectorAddress(m_address + frames);
    }

    SectorAddress operator-(int frames) const
    {
        return SectorAddress(m_address - frames);
    }

private:
    qint32 m_address;
    static quint8 intToBcd(quint32 value);
};

class RawSector
{
public:
    RawSector();
    void pushData(const QByteArray &inData);
    void pushErrorData(const QByteArray &inData);
    void pushPaddedData(const QByteArray &inData);
    QByteArray data() const;
    QByteArray errorData() const;
    QByteArray paddedData() const;
    quint32 size() const;
    void showData();

private:
    QByteArray m_data;
    QByteArray m_errorData;
    QByteArray m_paddedData;

    quint8 bcdToInt(quint8 bcd);
};

class Sector
{
public:
    Sector();
    void pushData(const QByteArray &inData);
    void pushErrorData(const QByteArray &inData);
    void pushPaddedData(const QByteArray &inData);
    QByteArray data() const;
    QByteArray errorData() const;
    QByteArray paddedData() const;
    quint32 size() const;
    void showData();

    void setAddress(SectorAddress address);
    SectorAddress address() const;
    void setMode(qint32 mode);
    qint32 mode() const;

    void dataValid(bool isValid) { m_validData = isValid; }
    bool isDataValid() const { return m_validData; }

private:
    QByteArray m_data;
    QByteArray m_errorData;
    QByteArray m_paddedData;

    SectorAddress m_address;
    qint32 m_mode;
    bool m_validData;
};

#endif // SECTOR_H
