/************************************************************************

    frame.h

    EFM-library - EFM Frame type classes
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

#ifndef FRAME_H
#define FRAME_H

#include <QVector>
#include <QDataStream>
#include <cstdint>
#include <QDebug>

// Frame class - base class for F1, F2, and F3 frames
class Frame
{
public:
    virtual ~Frame() {} // Virtual destructor
    virtual int frameSize() const = 0; // Pure virtual function to get frame size

    virtual void setData(const QVector<quint8> &data);
    virtual QVector<quint8> data() const;

    virtual void setErrorData(const QVector<bool> &errorData);
    virtual QVector<bool> errorData() const;
    virtual quint32 countErrors() const;

    virtual void setPaddedData(const QVector<bool> &errorData);
    virtual QVector<bool> paddedData() const;
    virtual quint32 countPadded() const;

    bool isFull() const;
    bool isEmpty() const;

    // Add serialization operators
    friend QDataStream& operator<<(QDataStream& out, const Frame& frame);
    friend QDataStream& operator>>(QDataStream& in, Frame& frame);

protected:
    QVector<quint8> m_frameData;
    QVector<bool> m_frameErrorData;
    QVector<bool> m_framePaddedData;
};

class Data24 : public Frame
{
public:
    Data24();
    int frameSize() const override;
    void showData();
    void setData(const QVector<quint8> &data) override;
    void setErrorData(const QVector<bool> &errorData) override;
};

class F1Frame : public Frame
{
public:
    F1Frame();
    int frameSize() const override;
    void showData();
};

class F2Frame : public Frame
{
public:
    F2Frame();
    int frameSize() const override;
    void showData();
};

class F3Frame : public Frame
{
public:
    enum F3FrameType { Subcode, Sync0, Sync1 };

    F3Frame();
    int frameSize() const override;

    void setFrameTypeAsSubcode(quint8 subcode);
    void setFrameTypeAsSync0();
    void setFrameTypeAsSync1();

    F3FrameType f3FrameType() const;
    QString f3FrameTypeAsString() const;
    quint8 subcodeByte() const;

    void showData();

private:
    F3FrameType m_f3FrameType;
    quint8 m_subcodeByte;
};

#endif // FRAME_H