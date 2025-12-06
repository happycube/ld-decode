/******************************************************************************
 * ldfreader.h
 * ld-ldf-reader - LDF reader tool for ld-decode
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2019-2021 Chad Page
 * SPDX-FileCopyrightText: 2020-2022 Adam Sampson
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is derived from FFmpeg's doc/examples/demuxing_decoding.c
 * Original FFmpeg copyright applies to the corresponding parts.
 * The original FFmpeg code is licensed under LGPL-2.1-or-later
 *
 * This derived work is redistributed under the terms of the GNU General
 * Public License version 3.0 or later.
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef LDFREADER_H
#define LDFREADER_H

#include <QString>
#include <QTextStream>

extern "C" {
#include <libavutil/samplefmt.h>
#include <libavutil/timestamp.h>
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
}

class LdfReader
{
public:
    LdfReader(const QString &inputFilename, qint64 startOffset = 0);
    ~LdfReader();

    bool process();

private:
    QString m_inputFilename;
    qint64 m_startOffset;

    AVFormatContext *m_formatContext;
    AVCodecContext *m_audioDecoderContext;
    AVStream *m_audioStream;
    int m_audioStreamIndex;
    AVFrame *m_frame;
    AVPacket *m_packet;

    bool openFile();
    bool openCodecContext();
    int decodePacket(const AVPacket *packet);
    void cleanup();
};

#endif // LDFREADER_H