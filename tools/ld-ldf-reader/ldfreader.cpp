/******************************************************************************
 * ldfreader.cpp
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

#include "ldfreader.h"

#include <QDebug>
#include <QFileInfo>
#include <QTextStream>
#include <cstdio>

#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

LdfReader::LdfReader(const QString &inputFilename, qint64 startOffset)
    : m_inputFilename(inputFilename)
    , m_startOffset(startOffset)
    , m_formatContext(nullptr)
    , m_audioDecoderContext(nullptr)
    , m_audioStream(nullptr)
    , m_audioStreamIndex(-1)
    , m_frame(nullptr)
    , m_packet(nullptr)
{
}

LdfReader::~LdfReader()
{
    cleanup();
}

bool LdfReader::process()
{
    qInfo() << "Processing LDF file:" << m_inputFilename;
    if (m_startOffset > 0) {
        qInfo() << "Start offset:" << m_startOffset << "samples";
    }

    // Check if input file exists
    QFileInfo inputFileInfo(m_inputFilename);
    if (!inputFileInfo.exists()) {
        qCritical() << "Input file does not exist:" << m_inputFilename;
        return false;
    }

#ifdef _WIN32
    if (_setmode(_fileno(stdout), _O_BINARY) == -1) {
        qCritical() << "Could not set stdout to binary mode";
        return false;
    }
    if (_setmode(_fileno(stdin), _O_BINARY) == -1) {
        qCritical() << "Could not set stdin to binary mode";
        return false;
    }
#endif

#if LIBAVFORMAT_VERSION_INT < AV_VERSION_INT(58, 7, 100)
    av_register_all();
#else
    // Later versions of ffmpeg register all codecs automatically
#endif

    if (!openFile()) {
        return false;
    }

    if (!openCodecContext()) {
        return false;
    }

    // Display stream information
    qInfo() << "Sample rate:" << m_audioDecoderContext->sample_rate << "Hz";
    qInfo() << "Duration:" << m_formatContext->duration << "μs";

    // Allocate frame and packet
    m_frame = av_frame_alloc();
    if (!m_frame) {
        qCritical() << "Could not allocate frame";
        return false;
    }

    m_packet = av_packet_alloc();
    if (!m_packet) {
        qCritical() << "Could not allocate packet";
        return false;
    }

    // Seek to start position if specified
    if (m_startOffset > 0) {
        qint64 seekSeconds = m_startOffset / m_audioDecoderContext->sample_rate;
        int ret = avformat_seek_file(m_formatContext, -1, 
                                   (seekSeconds - 1) * 1000000, 
                                   seekSeconds * 1000000, 
                                   seekSeconds * 1000000, 
                                   AVSEEK_FLAG_ANY);
        if (ret < 0) {
            qWarning() << "Seek failed, starting from beginning";
            m_startOffset = 0;
        }
    }

    // Read and decode frames
    int ret = 0;
    while (av_read_frame(m_formatContext, m_packet) >= 0) {
        if (m_packet->stream_index == m_audioStreamIndex) {
            ret = decodePacket(m_packet);
        }
        av_packet_unref(m_packet);
        if (ret < 0) {
            break;
        }
    }

    // Flush the decoder
    decodePacket(nullptr);

    // Flush any remaining data to stdout
    fflush(stdout);

    qInfo() << "LDF reading completed successfully";
    return ret >= 0;
}

bool LdfReader::openFile()
{
    // Open input file and allocate format context
    int ret = avformat_open_input(&m_formatContext, m_inputFilename.toLocal8Bit().constData(), nullptr, nullptr);
    if (ret < 0) {
        qCritical() << "Could not open source file:" << m_inputFilename << "Error:" << ret;
        return false;
    }

    // Retrieve stream information
    ret = avformat_find_stream_info(m_formatContext, nullptr);
    if (ret < 0) {
        qCritical() << "Could not find stream information";
        return false;
    }

    return true;
}

bool LdfReader::openCodecContext()
{
    // Find the best audio stream
    int ret = av_find_best_stream(m_formatContext, AVMEDIA_TYPE_AUDIO, -1, -1, nullptr, 0);
    if (ret < 0) {
        qCritical() << "Could not find audio stream in input file:" << m_inputFilename;
        return false;
    }

    m_audioStreamIndex = ret;
    m_audioStream = m_formatContext->streams[m_audioStreamIndex];

    // Find decoder for the stream
    const AVCodec *decoder = avcodec_find_decoder(m_audioStream->codecpar->codec_id);
    if (!decoder) {
        qCritical() << "Failed to find audio codec";
        return false;
    }

    // Allocate a codec context for the decoder
    m_audioDecoderContext = avcodec_alloc_context3(decoder);
    if (!m_audioDecoderContext) {
        qCritical() << "Failed to allocate audio codec context";
        return false;
    }

    // Copy codec parameters from input stream to output codec context
    ret = avcodec_parameters_to_context(m_audioDecoderContext, m_audioStream->codecpar);
    if (ret < 0) {
        qCritical() << "Failed to copy audio codec parameters to decoder context";
        return false;
    }

    // Initialize the decoder
    ret = avcodec_open2(m_audioDecoderContext, decoder, nullptr);
    if (ret < 0) {
        qCritical() << "Failed to open audio codec";
        return false;
    }

    return true;
}

int LdfReader::decodePacket(const AVPacket *packet)
{
    int ret = 0;

    // Submit the packet to the decoder
    ret = avcodec_send_packet(m_audioDecoderContext, packet);
    if (ret < 0) {
        qCritical() << "Error submitting a packet for decoding";
        return ret;
    }

    // Get all the available frames from the decoder
    while (ret >= 0) {
        ret = avcodec_receive_frame(m_audioDecoderContext, m_frame);
        if (ret < 0) {
            // Those two return values are special and mean there is no output
            // frame available, but there were no errors during decoding
            if (ret == AVERROR_EOF || ret == AVERROR(EAGAIN)) {
                return 0;
            }
            qCritical() << "Error during decoding";
            return ret;
        }

        // If we won't reach the start position during this frame, don't output anything
        if ((m_frame->pts + m_frame->nb_samples) <= m_startOffset) {
            av_frame_unref(m_frame);
            continue;
        }

        // The start position may be in the middle of a frame -- work out how
        // much data to skip at the start
        size_t bytesPerSample = av_get_bytes_per_sample(static_cast<AVSampleFormat>(m_frame->format));
        qint64 offset = (m_startOffset - m_frame->pts) * bytesPerSample;
        if (offset < 0) {
            // None -- output the whole frame
            offset = 0;
        }
        size_t length = (m_frame->nb_samples * bytesPerSample) - offset;

        // Write the raw audio data samples to stdout
        size_t written = fwrite(m_frame->extended_data[0] + offset, sizeof(uint8_t), length, stdout);
        if (written != length) {
            qCritical() << "Write error at offset:" << offset;
            return -1;
        }

        av_frame_unref(m_frame);
    }

    return 0;
}

void LdfReader::cleanup()
{
    if (m_audioDecoderContext) {
        avcodec_free_context(&m_audioDecoderContext);
        m_audioDecoderContext = nullptr;
    }

    if (m_formatContext) {
        avformat_close_input(&m_formatContext);
        m_formatContext = nullptr;
    }

    if (m_packet) {
        av_packet_free(&m_packet);
        m_packet = nullptr;
    }

    if (m_frame) {
        av_frame_free(&m_frame);
        m_frame = nullptr;
    }

    m_audioStream = nullptr;
    m_audioStreamIndex = -1;
}