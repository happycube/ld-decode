/************************************************************************

    section.cpp

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

#include "section.h"

F2Section::F2Section()
{
    m_frames.reserve(98);
}

void F2Section::pushFrame(const F2Frame &inFrame)
{
    if (m_frames.size() >= 98) {
        qFatal("F2Section::pushFrame - Section is full");
    }
    m_frames.push_back(inFrame);
}

F2Frame F2Section::frame(qint32 index) const
{
    if (index >= m_frames.size() || index < 0) {
        qFatal("F2Section::frame - Index %d out of range", index);
    }
    return m_frames.at(index);
}

void F2Section::setFrame(qint32 index, const F2Frame &inFrame)
{
    if (index >= m_frames.size() || index < 0) {
        qFatal("F2Section::setFrame - Index %d out of range", index);
    }
    m_frames[index] = inFrame;
}

bool F2Section::isComplete() const
{
    return m_frames.size() == 98;
}

void F2Section::clear()
{
    m_frames.clear();
}

void F2Section::showData()
{
    for (qint32 i = 0; i < m_frames.size(); ++i) {
        m_frames[i].showData();
    }
}

F1Section::F1Section()
{
    m_frames.reserve(98);
}

void F1Section::pushFrame(const F1Frame &inFrame)
{
    if (m_frames.size() >= 98) {
        qFatal("F1Section::pushFrame - Section is full");
    }
    m_frames.push_back(inFrame);
}

F1Frame F1Section::frame(qint32 index) const
{
    if (index >= m_frames.size() || index < 0) {
        qFatal("F1Section::frame - Index %d out of range", index);
    }
    return m_frames.at(index);
}

void F1Section::setFrame(qint32 index, const F1Frame &inFrame)
{
    if (index >= 98 || index < 0) {
        qFatal("F1Section::setFrame - Index %d out of range", index);
    }
    m_frames[index] = inFrame;
}

bool F1Section::isComplete() const
{
    return m_frames.size() == 98;
}

void F1Section::clear()
{
    m_frames.clear();
}

void F1Section::showData()
{
    for (qint32 i = 0; i < m_frames.size(); ++i) {
        m_frames[i].showData();
    }
}

Data24Section::Data24Section()
{
    m_frames.reserve(98);
}

void Data24Section::pushFrame(const Data24 &inFrame)
{
    if (m_frames.size() >= 98) {
        qFatal("Data24Section::pushFrame - Section is full");
    }
    m_frames.push_back(inFrame);
}

Data24 Data24Section::frame(qint32 index) const
{
    if (index >= m_frames.size() || index < 0) {
        qFatal("Data24Section::frame - Index %d out of range", index);
    }
    return m_frames.at(index);
}

void Data24Section::setFrame(qint32 index, const Data24 &inFrame)
{
    if (index >= m_frames.size() || index < 0) {
        qFatal("Data24Section::setFrame - Index %d out of range", index);
    }
    m_frames[index] = inFrame;
}

bool Data24Section::isComplete() const
{
    return m_frames.size() == 98;
}

void Data24Section::clear()
{
    m_frames.clear();
}

void Data24Section::showData()
{
    for (qint32 i = 0; i < m_frames.size(); ++i) {
        m_frames[i].showData();
    }
}

AudioSection::AudioSection()
{
    m_frames.reserve(98);
}

void AudioSection::pushFrame(const Audio &inFrame)
{
    if (m_frames.size() >= 98) {
        qFatal("AudioSection::pushFrame - Section is full");
    }
    m_frames.push_back(inFrame);
}

Audio AudioSection::frame(qint32 index) const
{
    if (index >= m_frames.size() || index < 0) {
        qFatal("AudioSection::frame - Index %d out of range", index);
    }
    return m_frames.at(index);
}

void AudioSection::setFrame(qint32 index, const Audio &inFrame)
{
    if (index >= m_frames.size() || index < 0) {
        qFatal("AudioSection::setFrame - Index %d out of range", index);
    }
    m_frames[index] = inFrame;
}

bool AudioSection::isComplete() const
{
    return m_frames.size() == 98;
}

void AudioSection::clear()
{
    m_frames.clear();
}

void AudioSection::showData()
{
    for (qint32 i = 0; i < m_frames.size(); ++i) {
        m_frames[i].showData();
    }
}

// Stream write and read operators for F2Section and Data24Section
QDataStream& operator<<(QDataStream& stream, const F2Section& section)
{
    // Write metadata
    stream << section.metadata;
    
    // Write number of frames
    stream << static_cast<qint32>(section.m_frames.size());
    
    // Write frames
    for (const auto& frame : section.m_frames) {
        stream << frame;
    }
    
    return stream;
}

QDataStream& operator>>(QDataStream& stream, F2Section& section)
{
    // Clear existing data
    section.clear();
    
    // Read metadata
    stream >> section.metadata;
    
    // Read number of frames
    qint32 frameCount;
    stream >> frameCount;
    
    // Read frames
    for (qint32 i = 0; i < frameCount; ++i) {
        F2Frame frame;
        stream >> frame;
        section.pushFrame(frame);
    }
    
    return stream;
}

QDataStream& operator<<(QDataStream& stream, const Data24Section& section)
{
    // Write metadata
    stream << section.metadata;
    
    // Write number of frames
    stream << static_cast<qint32>(section.m_frames.size());
    
    // Write frames
    for (const auto& frame : section.m_frames) {
        stream << frame;
    }
    
    return stream;
}

QDataStream& operator>>(QDataStream& stream, Data24Section& section)
{
    // Clear existing data
    section.clear();
    
    // Read metadata
    stream >> section.metadata;
    
    // Read number of frames
    qint32 frameCount;
    stream >> frameCount;
    
    // Read frames
    for (qint32 i = 0; i < frameCount; ++i) {
        Data24 frame;
        stream >> frame;
        section.pushFrame(frame);
    }
    
    return stream;
}