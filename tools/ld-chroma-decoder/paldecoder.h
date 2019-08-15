/************************************************************************

    paldecoder.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018-2019 Simon Inns
    Copyright (C) 2019 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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

#ifndef PALDECODER_H
#define PALDECODER_H

#include <QObject>
#include <QAtomicInt>
#include <QThread>
#include <QDebug>

#include "lddecodemetadata.h"
#include "sourcevideo.h"

#include "decoder.h"
#include "palcolour.h"

class DecoderPool;

// 2D PAL decoder using PALcolour
class PalDecoder : public Decoder {
public:
    PalDecoder(bool blackAndWhite, bool useTransformFilter = false, double transformThreshold = 0.4);
    bool configure(const LdDecodeMetaData::VideoParameters &videoParameters) override;
    QThread *makeThread(QAtomicInt& abort, DecoderPool& decoderPool) override;

    // Parameters used by PalDecoder and PalThread
    struct Configuration : public Decoder::Configuration {
        bool blackAndWhite;
        PalColour::Configuration pal;
    };

private:
    Configuration config;
};

class PalThread : public QThread
{
    Q_OBJECT
public:
    explicit PalThread(QAtomicInt &abort, DecoderPool &decoderPool,
                       const PalDecoder::Configuration &config,
                       QObject *parent = nullptr);

protected:
    void run() override;

private:
    // Decoder pool
    QAtomicInt& abort;
    DecoderPool& decoderPool;

    // Settings
    const PalDecoder::Configuration &config;

    // PAL colour object
    PalColour palColour;
};

#endif // PALDECODER
