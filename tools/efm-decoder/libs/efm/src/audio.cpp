/************************************************************************

    audio.cpp

    EFM-library - Audio frame type class
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

#include "audio.h"

// Audio class
// Set the data for the audio, ensuring it matches the frame size
void Audio::setData(const QVector<qint16> &data)
{
    if (data.size() != frameSize()) {
        qFatal("Audio::setData(): Data size of %d does not match frame size of %d", data.size(), frameSize());
    }
    m_audioData = data;
}

// Set the left and right channel data for the audio, ensuring they match the frame size
void Audio::setDataLeftRight(const QVector<qint16> &dataLeft, const QVector<qint16> &dataRight)
{
    if (dataLeft.size() + dataRight.size() != frameSize()) {
        qFatal("Audio::setDataLeftRight(): Data size of %d does not match frame size of %d", dataLeft.size() + dataRight.size(), frameSize());
    }
    
    m_audioData.clear();
    for (int i = 0; i < frameSize(); i += 2) {
        m_audioData.append(dataLeft[i]);
        m_audioData.append(dataRight[i]);
    }
}

// Get the data for the audio, returning a zero-filled vector if empty
QVector<qint16> Audio::data() const
{
    if (m_audioData.isEmpty()) {
        qDebug() << "Audio::data(): Frame is empty, returning zero-filled vector";
        return QVector<qint16>(frameSize(), 0);
    }
    return m_audioData;
}

// Get the left channel data for the audio, returning a zero-filled vector if empty
QVector<qint16> Audio::dataLeft() const
{
    if (m_audioData.isEmpty()) {
        qDebug() << "Audio::dataLeft(): Frame is empty, returning zero-filled vector";
        return QVector<qint16>(frameSize(), 0);
    }
    
    QVector<qint16> dataLeft;
    for (int i = 0; i < frameSize(); i += 2) {
        dataLeft.append(m_audioData[i]);
    }
    return dataLeft;
}

// Get the right channel data for the audio, returning a zero-filled vector if empty
QVector<qint16> Audio::dataRight() const
{
    if (m_audioData.isEmpty()) {
        qDebug() << "Audio::dataRight(): Frame is empty, returning zero-filled vector";
        return QVector<qint16>(frameSize(), 0);
    }
    
    QVector<qint16> dataRight;
    for (int i = 1; i < frameSize(); i += 2) {
        dataRight.append(m_audioData[i]);
    }
    return dataRight;
}

// Set the error data for the audio, ensuring it matches the frame size
void Audio::setErrorData(const QVector<bool> &errorData)
{
    if (errorData.size() != frameSize()) {
        qFatal("Audio::setErrorData(): Error data size of %d does not match frame size of %d", errorData.size(), frameSize());
    }
    m_audioErrorData = errorData;
}

// Set the left and right channel error data for the audio, ensuring they match the frame size
void Audio::setErrorDataLeftRight(const QVector<bool> &errorDataLeft, const QVector<bool> &errorDataRight)
{
    if (errorDataLeft.size() + errorDataRight.size() != frameSize()) {
        qFatal("Audio::setErrorDataLeftRight(): Error data size of %d does not match frame size of %d", errorDataLeft.size() + errorDataRight.size(), frameSize());
    }
    
    m_audioErrorData.clear();
    for (int i = 0; i < frameSize(); i += 2) {
        m_audioErrorData.append(errorDataLeft[i]);
        m_audioErrorData.append(errorDataRight[i]);
    }
}

// Get the error_data for the audio, returning a zero-filled vector if empty
QVector<bool> Audio::errorData() const
{
    if (m_audioErrorData.isEmpty()) {
        qDebug() << "Audio::errorData(): Error frame is empty, returning zero-filled vector";
        return QVector<bool>(frameSize(), false);
    }
    return m_audioErrorData;
}

// Get the left channel error data for the audio, returning a zero-filled vector if empty
QVector<bool> Audio::errorDataLeft() const
{
    if (m_audioErrorData.isEmpty()) {
        qDebug() << "Audio::errorDataLeft(): Error frame is empty, returning zero-filled vector";
        return QVector<bool>(frameSize(), false);
    }
    
    QVector<bool> errorDataLeft;
    for (int i = 0; i < frameSize(); i += 2) {
        errorDataLeft.append(m_audioErrorData[i]);
    }
    return errorDataLeft;
}

// Get the right channel error data for the audio, returning a zero-filled vector if empty
QVector<bool> Audio::errorDataRight() const
{
    if (m_audioErrorData.isEmpty()) {
        qDebug() << "Audio::errorDataRight(): Error frame is empty, returning zero-filled vector";
        return QVector<bool>(frameSize(), false);
    }
    
    QVector<bool> errorDataRight;
    for (int i = 1; i < frameSize(); i += 2) {
        errorDataRight.append(m_audioErrorData[i]);
    }
    return errorDataRight;
}

// Count the number of errors in the audio
quint32 Audio::countErrors() const
{
    quint32 errorCount = 0;
    for (int i = 0; i < frameSize(); ++i) {
        if (m_audioErrorData[i] == true) {
            errorCount++;
        }
    }
    return errorCount;
}

// Count the number of errors in the left channel of the audio
quint32 Audio::countErrorsLeft() const
{
    quint32 errorCount = 0;
    for (int i = 0; i < frameSize(); i += 2) {
        if (m_audioErrorData[i] == true) {
            errorCount++;
        }
    }
    return errorCount;
}

// Count the number of errors in the right channel of the audio
quint32 Audio::countErrorsRight() const
{
    quint32 errorCount = 0;
    for (int i = 1; i < frameSize(); i += 2) {
        if (m_audioErrorData[i] == true) {
            errorCount++;
        }
    }
    return errorCount;
}

// Check if the audio is full (i.e., has data)
bool Audio::isFull() const
{
    return !isEmpty();
}

// Check if the audio is empty (i.e., has no data)
bool Audio::isEmpty() const
{
    return m_audioData.isEmpty();
}

// Show the audio data and errors in debug
void Audio::showData()
{
    QString dataString;
    bool hasError = false;
    for (int i = 0; i < m_audioData.size(); ++i) {
        if (m_audioErrorData[i] == false) {
            dataString.append(QString("%1%2 ")
                .arg(m_audioData[i] < 0 ? "-" : "+")
                .arg(qAbs(m_audioData[i]), 4, 16, QChar('0')));
        } else {
            dataString.append(QString("XXXXX "));
            hasError = true;
        }
    }

    qDebug().noquote() << dataString.trimmed().toUpper();
}

int Audio::frameSize() const
{
    return 12;
}

void Audio::setConcealedData(const QVector<bool> &concealedData)
{
    if (concealedData.size() != frameSize()) {
        qFatal("Audio::setConcealedData(): Concealed data size of %d does not match frame size of %d", concealedData.size(), frameSize());
    }
    m_audioConcealedData = concealedData;
}

QVector<bool> Audio::concealedData() const
{
    if (m_audioConcealedData.isEmpty()) {
        qDebug() << "Audio::concealedData(): Concealed data is empty, returning zero-filled vector";
        return QVector<bool>(frameSize(), false);
    }
    return m_audioConcealedData;
}