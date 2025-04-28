/************************************************************************

    monodecoder.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019-2021 Adam Sampson

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

#include "monodecoder.h"

#include "comb.h"
#include "decoderpool.h"
#include "palcolour.h"

#include "deemp.h"
#include "firfilter.h"

MonoDecoder::MonoDecoder()
{	
}

MonoDecoder::MonoDecoder(const MonoDecoder::MonoConfiguration &config)
{
    monoConfig = config;
}

bool MonoDecoder::updateConfiguration(const LdDecodeMetaData::VideoParameters &videoParameters, const MonoDecoder::MonoConfiguration &configuration) {
    // This decoder works for both PAL and NTSC.
	monoConfig.yNRLevel = configuration.yNRLevel;
    monoConfig.videoParameters = videoParameters;

    return true;
}

bool MonoDecoder::configure(const LdDecodeMetaData::VideoParameters &videoParameters) {
    // This decoder works for both PAL and NTSC.

    monoConfig.videoParameters = videoParameters;

    return true;
}

QThread *MonoDecoder::makeThread(QAtomicInt& abort, DecoderPool& decoderPool) {
    return new MonoThread(abort, decoderPool, monoConfig);
}

void MonoDecoder::decodeFrames(const QVector<SourceField>& inputFields,
                               qint32 startIndex,
                               qint32 endIndex,
                               QVector<ComponentFrame>& componentFrames)
{
	const LdDecodeMetaData::VideoParameters &videoParameters = monoConfig.videoParameters;
	bool ignoreUV = false;
	
	
	for (qint32 fieldIndex = startIndex, frameIndex = 0; fieldIndex < endIndex; fieldIndex += 2, frameIndex++) {
		componentFrames[frameIndex].init(videoParameters, ignoreUV);
		for (qint32 y = videoParameters.firstActiveFrameLine; y < videoParameters.lastActiveFrameLine; y++) {
			const SourceVideo::Data &inputFieldData = (y % 2) == 0 ? inputFields[fieldIndex].data :inputFields[fieldIndex+1].data;
			const quint16 *inputLine = inputFieldData.data() + ((y / 2) * videoParameters.fieldWidth);

			// Copy the whole composite signal to Y (leaving U and V blank)
			double *outY = componentFrames[frameIndex].y(y);
			for (qint32 x = videoParameters.activeVideoStart; x < videoParameters.activeVideoEnd; x++) {
				outY[x] = inputLine[x];
			}
		}
		doYNR(componentFrames[frameIndex]);
    }
}

void MonoDecoder::doYNR(ComponentFrame &componentFrame) {
    if (monoConfig.yNRLevel == 0.0)
        return;

    // 1. Compute coring level (same formula in both existing routines)
    double irescale = (monoConfig.videoParameters.white16bIre
                     - monoConfig.videoParameters.black16bIre) / 100.0;
    double nr_y     = monoConfig.yNRLevel * irescale;

    // 2. Choose filter taps & descriptor based on system
    bool usePal = (monoConfig.videoParameters.system == PAL || monoConfig.videoParameters.system == PAL_M);
    const auto& taps       = usePal ? c_nrpal_b
                                    : c_nr_b;
    const auto& descriptor = usePal ? f_nrpal
                                    : f_nr;

    const int delay = static_cast<int>(taps.size()) / 2;

    // 3. Process each active scanline in the frame
    for (int line = monoConfig.videoParameters.firstActiveFrameLine;
             line < monoConfig.videoParameters.lastActiveFrameLine;
           ++line)
    {
        double* Y = componentFrame.y(line);

        // 4. High‑pass buffer & FIR filter
        std::vector<double> hpY(monoConfig.videoParameters.activeVideoEnd + delay);
        auto yFilter(descriptor);  // uses the chosen taps internally

        // Flush zeros before active start
        for (int x = monoConfig.videoParameters.activeVideoStart - delay;
                 x < monoConfig.videoParameters.activeVideoStart;
               ++x)
        {
            yFilter.feed(0.0);
        }
        // Filter active region
        for (int x = monoConfig.videoParameters.activeVideoStart;
                 x < monoConfig.videoParameters.activeVideoEnd;
               ++x)
        {
            hpY[x] = yFilter.feed(Y[x]);
        }
        // Flush zeros after active end
        for (int x = monoConfig.videoParameters.activeVideoEnd;
                 x < monoConfig.videoParameters.activeVideoEnd + delay;
               ++x)
        {
            yFilter.feed(0.0);
        }

        // 5. Clamp & subtract
        for (int x = monoConfig.videoParameters.activeVideoStart;
                 x < monoConfig.videoParameters.activeVideoEnd;
               ++x)
        {
            double a = hpY[x + delay];
            if (std::fabs(a) > nr_y)
                a = (a > 0.0) ? nr_y : -nr_y;
            Y[x] -= a;
        }
    }
}

MonoThread::MonoThread(QAtomicInt& _abort, DecoderPool& _decoderPool,
                       const MonoDecoder::MonoConfiguration &_monoConfig, QObject *parent)
    : DecoderThread(_abort, _decoderPool, parent), monoConfig(_monoConfig)
{
}

void MonoThread::decodeFrames(const QVector<SourceField>& inputFields,
                              qint32 startIndex, qint32 endIndex,
                              QVector<ComponentFrame>& componentFrames)
{
    // Delegate to the centralized, public API
    auto &baseDecoder = static_cast<MonoDecoder&>(decoderPool.getDecoder());
    baseDecoder.decodeFrames(inputFields, startIndex, endIndex, componentFrames);
}
