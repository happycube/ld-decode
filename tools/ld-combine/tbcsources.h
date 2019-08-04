/************************************************************************

    tbcsources.h

    ld-combine - TBC combination and enhancement tool
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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

#ifndef TBCSOURCES_H
#define TBCSOURCES_H

#include <QObject>
#include <QImage>
#include <QList>
#include <QtConcurrent/QtConcurrent>
#include <QDebug>

// TBC library includes
#include "sourcevideo.h"
#include "lddecodemetadata.h"

// Local includes
#include "discmap.h"

class TbcSources : public QObject
{
    Q_OBJECT
public:
    explicit TbcSources(QObject *parent = nullptr);

    struct RawFrame {
        QByteArray firstFieldData;
        QByteArray secondFieldData;

        qint32 fieldHeight;
        qint32 fieldWidth;
    };

    void loadSource(QString filename);
    QString getLoadingMessage();
    bool unloadSource();
    bool setCurrentSource(qint32 sourceNumber);
    qint32 getCurrentSource();
    qint32 getNumberOfAvailableSources();
    QVector<QString> getListOfAvailableSources();
    QImage getCurrentFrameImage();
    RawFrame getCurrentFrameData();
    qint32 getNumberOfFrames();
    qint32 getCurrentFrameNumber();
    void setCurrentFrameNumber(qint32 frameNumber);
    QString getCurrentSourceFilename();
    QStringList getCurrentMapReport();

signals:
    void setBusy(QString message, bool showProgress, qint32 progress);
    void clearBusy();
    void updateSources(bool isSuccessful);

public slots:

private slots:
    void finishBackgroundLoad();

private:
    struct Source {
        SourceVideo sourceVideo;
        LdDecodeMetaData ldDecodeMetaData;
        qint32 currentFrameNumber;
        QString filename;
        DiscMap discMap;
    };

    QVector<Source*> sourceVideos;
    qint32 currentSource;
    QString backgroundLoadErrorMessage;

    // Background loader globals
    QFutureWatcher<void> watcher;
    QFuture <void> future;
    bool backgroundLoadSuccessful;

    void performBackgroundLoad(QString filename);
};

#endif // TBCSOURCES_H
