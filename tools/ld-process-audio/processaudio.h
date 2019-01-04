/************************************************************************

    processaudio.h

    ld-process-audio - Analogue audio processing for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-audio is free software: you can redistribute it and/or
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

#ifndef PROCESSAUDIO_H
#define PROCESSAUDIO_H

#include <QObject>
#include <QFileInfo>

#include "sourcevideo.h"
#include "lddecodemetadata.h"

class ProcessAudio : public QObject
{
    Q_OBJECT
public:
    explicit ProcessAudio(QObject *parent = nullptr);

    bool process(QString inputFileName);

signals:

public slots:

private:
    LdDecodeMetaData ldDecodeMetaData;
    LdDecodeMetaData::VideoParameters videoParameters;

    QFile *audioInputFile;
    QFile *audioOutputFile;

    struct AudioData {
        qint16 left;
        qint16 right;
    };

    QVector<ProcessAudio::AudioData> silenceAudioSample(QVector<ProcessAudio::AudioData> audioData);
    void writeFieldAudio(QVector<ProcessAudio::AudioData> audioData);
    QVector<ProcessAudio::AudioData> readFieldAudio(qint32 fieldNumber);
    bool openInputAudioFile(QString filename);
    void closeInputAudioFile(void);
    bool openOutputAudioFile(QString filename);
    void closeOutputAudioFile(void);
};

#endif // PROCESSAUDIO_H
