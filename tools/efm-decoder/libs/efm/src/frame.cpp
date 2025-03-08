/************************************************************************

    frame.cpp

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

#include "frame.h"

// Frame class
// --------------------------------------------------------------------------------------------------------

// Set the data for the frame, ensuring it matches the frame size
void Frame::setData(const QVector<quint8> &data)
{
    if (data.size() != frameSize()) {
        qFatal("Frame::setData(): Data size of %d does not match frame size of %d", data.size(),
               frameSize());
    }
    m_frameData = data;
}

// Get the data for the frame, returning a zero-filled vector if empty
QVector<quint8> Frame::data() const
{
    if (m_frameData.isEmpty()) {
        qDebug() << "Frame::getData(): Frame is empty, returning zero-filled vector";
        return QVector<quint8>(frameSize(), 0);
    }
    return m_frameData;
}

// Set the error data for the frame, ensuring it matches the frame size
// Note: This is a vector of boolean, where false is no error and true is an error
void Frame::setErrorData(const QVector<bool> &errorData)
{
    if (errorData.size() != frameSize()) {
        qFatal("Frame::setErrorData(): Error data size of %d does not match frame size of %d",
               errorData.size(), frameSize());
    }

    m_frameErrorData = errorData;
}

// Get the error_data for the frame, returning a zero-filled vector if empty
// Note: This is a vector of boolean, where false is no error and true is an error
QVector<bool> Frame::errorData() const
{
    if (m_frameErrorData.isEmpty()) {
        qDebug() << "Frame::getErrorData(): Error frame is empty, returning zero-filled vector";
        return QVector<bool>(frameSize(), 0);
    }
    return m_frameErrorData;
}

// Count the number of errors in the frame
quint32 Frame::countErrors() const
{
    quint32 errorCount = 0;
    for (int i = 0; i < m_frameErrorData.size(); ++i) {
        if (m_frameErrorData[i] == true) {
            errorCount++;
        }
    }
    return errorCount;
}

// Set the padded data for the frame, ensuring it matches the frame size
// Note: This is a vector of boolean, where false is no padding and true is padding
void Frame::setPaddedData(const QVector<bool> &paddedData)
{
    if (paddedData.size() != frameSize()) {
        qFatal("Frame::setPaddedData(): Padded data size of %d does not match frame size of %d",
            paddedData.size(), frameSize());
    }

    m_framePaddedData = paddedData;
}

// Get the padded data for the frame, returning a zero-filled vector if empty
// Note: This is a vector of boolean, where false is no padding and true is padding
QVector<bool> Frame::paddedData() const
{
    if (m_framePaddedData.isEmpty()) {
        qDebug() << "Frame::paddedData(): Padded data is empty, returning zero-filled vector";
        return QVector<bool>(frameSize(), 0);
    }
    return m_framePaddedData;
}

// Count the number of padded bytes in the frame
quint32 Frame::countPadded() const
{
    quint32 paddingCount = 0;
    for (int i = 0; i < m_framePaddedData.size(); ++i) {
        if (m_framePaddedData[i] == true) {
            paddingCount++;
        }
    }
    return paddingCount;
}

// Check if the frame is full (i.e., has data)
bool Frame::isFull() const
{
    return !m_frameData.isEmpty();
}

// Check if the frame is empty (i.e., has no data)
bool Frame::isEmpty() const
{
    return m_frameData.isEmpty();
}

QDataStream& operator<<(QDataStream& out, const Frame& frame)
{
    // Write frame data
    out << frame.m_frameData;
    // Write error data
    out << frame.m_frameErrorData;
    // Write padding data
    out << frame.m_framePaddedData;
    return out;
}

QDataStream& operator>>(QDataStream& in, Frame& frame)
{
    // Read frame data
    in >> frame.m_frameData;
    // Read error data
    in >> frame.m_frameErrorData;
    // Read padded data
    in >> frame.m_framePaddedData;
    return in;
}

// Constructor for Data24, initializes data to the frame size
Data24::Data24()
{
    m_frameData.resize(frameSize());
    m_frameErrorData.resize(frameSize());
    m_frameErrorData.fill(false);
    m_framePaddedData.resize(frameSize());
    m_framePaddedData.fill(false);
}

// We override the set_data function to ensure the data is 24 bytes
// since it's possible to have less than 24 bytes of data
void Data24::setData(const QVector<quint8> &data)
{
    m_frameData = data;

    // If there are less than 24 bytes, pad data with zeros to 24 bytes
    if (m_frameData.size() < 24) {
        m_frameData.resize(24);
        for (int i = m_frameData.size(); i < 24; ++i) {
            m_frameData[i] = 0;
        }
    }
}

void Data24::setErrorData(const QVector<bool> &errorData)
{
    m_frameErrorData = errorData;

    // If there are less than 24 values, pad data with false to 24 values
    if (m_frameErrorData.size() < 24) {
        m_frameErrorData.resize(24);
        for (int i = m_frameErrorData.size(); i < 24; ++i) {
            m_frameErrorData[i] = false;
        }
    }
}

// Get the frame size for Data24
int Data24::frameSize() const
{
    return 24;
}

void Data24::showData()
{
    QString dataString;
    bool hasError = false;
    for (int i = 0; i < m_frameData.size(); ++i) {
        if (m_frameErrorData[i] == false && m_framePaddedData[i] == false) {
            dataString.append(QString("%1 ").arg(m_frameData[i], 2, 16, QChar('0')));
        } else {
            if (m_framePaddedData[i] == true) {
                dataString.append(QString("PP "));
            } else {
                dataString.append(QString("XX "));
                hasError = true;
            }
        }
    }
    if (hasError) {
        qInfo().noquote() << "Data24:" << dataString.trimmed() << "ERROR";
    } else {
        qInfo().noquote() << "Data24:" << dataString.trimmed();
    }
}

// Constructor for F1Frame, initializes data to the frame size
F1Frame::F1Frame()
{
    m_frameData.resize(frameSize());
    m_frameErrorData.resize(frameSize());
    m_frameErrorData.fill(false);
    m_framePaddedData.resize(frameSize());
    m_framePaddedData.fill(false);
}

// Get the frame size for F1Frame
int F1Frame::frameSize() const
{
    return 24;
}

void F1Frame::showData()
{
    QString dataString;
    bool hasError = false;
    for (int i = 0; i < m_frameData.size(); ++i) {
        if (m_frameErrorData[i] == false && m_framePaddedData[i] == false) {
            dataString.append(QString("%1 ").arg(m_frameData[i], 2, 16, QChar('0')));
        } else {
            if (m_framePaddedData[i] == true) {
                dataString.append(QString("PP "));
            } else {
                dataString.append(QString("XX "));
                hasError = true;
            }
        }
    }
    if (hasError) {
        qInfo().noquote() << "F1Frame:" << dataString.trimmed() << "ERROR";
    } else {
        qInfo().noquote() << "F1Frame:" << dataString.trimmed();
    }
}

// Constructor for F2Frame, initializes data to the frame size
F2Frame::F2Frame()
{
    m_frameData.resize(frameSize());
    m_frameErrorData.resize(frameSize());
    m_frameErrorData.fill(false);
    m_framePaddedData.resize(frameSize());
    m_framePaddedData.fill(false);
}

// Get the frame size for F2Frame
int F2Frame::frameSize() const
{
    return 32;
}

void F2Frame::showData()
{
    QString dataString;
    bool hasError = false;
    for (int i = 0; i < m_frameData.size(); ++i) {
        if (m_frameErrorData[i] == false && m_framePaddedData[i] == false) {
            dataString.append(QString("%1 ").arg(m_frameData[i], 2, 16, QChar('0')));
        } else {
            if (m_framePaddedData[i] == true) {
                dataString.append(QString("PP "));
            } else {
                dataString.append(QString("XX "));
                hasError = true;
            }
        }
    }
    if (hasError) {
        qInfo().noquote() << "F2Frame:" << dataString.trimmed() << "ERROR";
    } else {
        qInfo().noquote() << "F2Frame:" << dataString.trimmed();
    }
}

// Constructor for F3Frame, initializes data to the frame size
F3Frame::F3Frame()
{
    m_frameData.resize(frameSize());
    m_subcodeByte = 0;
    m_f3FrameType = Subcode;
}

// Get the frame size for F3Frame
int F3Frame::frameSize() const
{
    return 32;
}

// Set the frame type as subcode and set the subcode value
void F3Frame::setFrameTypeAsSubcode(quint8 subcodeValue)
{
    m_f3FrameType = Subcode;
    m_subcodeByte = subcodeValue;
}

// Set the frame type as sync0 and set the subcode value to 0
void F3Frame::setFrameTypeAsSync0()
{
    m_f3FrameType = Sync0;
    m_subcodeByte = 0;
}

// Set the frame type as sync1 and set the subcode value to 0
void F3Frame::setFrameTypeAsSync1()
{
    m_f3FrameType = Sync1;
    m_subcodeByte = 0;
}

// Get the F3 frame type
F3Frame::F3FrameType F3Frame::f3FrameType() const
{
    return m_f3FrameType;
}

// Get the F3 frame type as a QString
QString F3Frame::f3FrameTypeAsString() const
{
    switch (m_f3FrameType) {
    case Subcode:
        return "Subcode";
    case Sync0:
        return "Sync0";
    case Sync1:
        return "Sync1";
    default:
        return "UNKNOWN";
    }
}

// Get the subcode value
quint8 F3Frame::subcodeByte() const
{
    return m_subcodeByte;
}

void F3Frame::showData()
{
    QString dataString;
    bool hasError = false;
    for (int i = 0; i < m_frameData.size(); ++i) {
        if (m_frameErrorData[i] == false) {
            dataString.append(QString("%1 ").arg(m_frameData[i], 2, 16, QChar('0')));
        } else {
            dataString.append(QString("XX "));
            hasError = true;
        }
    }

    QString errorString;
    if (hasError)
        errorString = "ERROR";
    else
        errorString = "";

    if (m_f3FrameType == Subcode) {
        qInfo().noquote() << "F3Frame:" << dataString.trimmed()
                          << " subcode:" << QString("0x%1").arg(m_subcodeByte, 2, 16, QChar('0'))
                          << errorString;
    } else if (m_f3FrameType == Sync0) {
        qInfo().noquote() << "F3Frame:" << dataString.trimmed() << " Sync0" << errorString;
    } else if (m_f3FrameType == Sync1) {
        qInfo().noquote() << "F3Frame:" << dataString.trimmed() << " Sync1" << errorString;
    } else {
        qInfo().noquote() << "F3Frame:" << dataString.trimmed() << " UNKNOWN" << errorString;
    }
}
