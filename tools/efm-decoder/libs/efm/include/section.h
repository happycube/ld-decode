/************************************************************************

    section.h

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

#ifndef SECTION_H
#define SECTION_H

#include <QVector>
#include <QDataStream>
#include "frame.h"
#include "audio.h"
#include "section_metadata.h"

class F2Section
{
public:
    F2Section();
    void pushFrame(const F2Frame &inFrame);
    F2Frame frame(int index) const;
    void setFrame(int index, const F2Frame &inFrame);
    bool isComplete() const;
    void clear();
    void showData();

    friend QDataStream& operator<<(QDataStream& stream, const F2Section& section);
    friend QDataStream& operator>>(QDataStream& stream, F2Section& section);

    SectionMetadata metadata;

private:
    QVector<F2Frame> m_frames;
    bool m_isPadding;
};

class F1Section
{
public:
    F1Section();
    void pushFrame(const F1Frame &inFrame);
    F1Frame frame(int index) const;
    void setFrame(int index, const F1Frame &inFrame);
    bool isComplete() const;
    void clear();
    void showData();

    SectionMetadata metadata;

private:
    QVector<F1Frame> m_frames;
    bool m_isPadding;
};

class Data24Section
{
public:
    Data24Section();
    void pushFrame(const Data24 &inFrame);
    Data24 frame(int index) const;
    void setFrame(int index, const Data24 &inFrame);
    bool isComplete() const;
    void clear();
    void showData();

    friend QDataStream& operator<<(QDataStream& stream, const Data24Section& section);
    friend QDataStream& operator>>(QDataStream& stream, Data24Section& section);

    SectionMetadata metadata;

private:
    QVector<Data24> m_frames;
};

class AudioSection
{
public:
    AudioSection();
    void pushFrame(const Audio &inFrame);
    Audio frame(int index) const;
    void setFrame(int index, const Audio &inFrame);
    bool isComplete() const;
    void clear();
    void showData();

    SectionMetadata metadata;

private:
    QVector<Audio> m_frames;
};

#endif // SECTION_H
