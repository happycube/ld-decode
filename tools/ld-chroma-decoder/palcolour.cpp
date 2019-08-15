/************************************************************************

    palcolour.cpp

    Performs 2D subcarrier filtering to process stand-alone fields of
    a video signal

    Copyright (C) 2018  William Andrew Steer
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

// PALcolour original copyright notice:
// Copyright (C) 2018  William Andrew Steer
// Contact the author at palcolour@techmind.org

#include "palcolour.h"

/*!
    \class PalColour

    PALcolour, originally written by William Andrew Steer, is a line-locked PAL
    decoder using 2D FIR filters.

    For a good overview of line-locked PAL decoding techniques, see
    BBC Research Department Report 1986/02 (https://www.bbc.co.uk/rd/publications/rdreport_1986_02),
    "Colour encoding and decoding techniques for line-locked sampled PAL and
    NTSC television signals" by C.K.P. Clark. PALcolour uses the architecture
    shown in Figure 23(c), except that it has three separate baseband filters,
    one each for Y, U and V, with different characteristics. Rather than
    tracking the colour subcarrier using a PLL, PALcolour detects the phase of
    the subcarrier at the colourburst, and rotates the U/V output to
    compensate when decoding.

    BBC Research Department Report 1988/11 (https://www.bbc.co.uk/rd/publications/rdreport_1988_11),
    "PAL decoding: Multi-dimensional filter design for chrominance-luminance
    separation", also by C.K.P. Clark, describes the design concerns behind
    these filters. As PALcolour is a software implementation, it can use larger
    filters with more complex coefficients than the report describes.
 */

PalColour::PalColour(QObject *parent)
    : QObject(parent), configurationSet(false)
{
}

// Return the current configuration
const PalColour::Configuration &PalColour::getConfiguration() const {
    return configuration;
}

void PalColour::updateConfiguration(const LdDecodeMetaData::VideoParameters &_videoParameters,
                                    const Configuration &_configuration)
{
    // Copy the configuration parameters
    videoParameters = _videoParameters;
    configuration = _configuration;

    // Build the look-up tables
    buildLookUpTables();

    if (configuration.useTransformFilter) {
        // Configure Transform PAL
        transformPal.updateConfiguration(videoParameters,
                                         configuration.firstActiveLine, configuration.lastActiveLine,
                                         configuration.transformThreshold);
    }

    configurationSet = true;
}

// Private method to build the look up tables
// must be called by the constructor when the object is created
void PalColour::buildLookUpTables()
{
    // Generate the reference carrier: quadrature samples of a sine wave at the
    // subcarrier frequency. We'll use this for two purposes below:
    // - product-detecting the line samples, to give us quadrature samples of
    //   the chroma information centred on 0 Hz
    // - working out what the phase of the subcarrier is on each line,
    //   so we can rotate the chroma samples to put U/V on the right axes
    // refAmpl is the sinewave amplitude.
    refAmpl = 1.28;
    refNorm = (refAmpl * refAmpl / 2);

    for (qint32 i = 0; i < videoParameters.fieldWidth; i++) {
        const double rad = 2 * M_PI * i * videoParameters.fsc / videoParameters.sampleRate;
        sine[i] = refAmpl * sin(rad);
        cosine[i] = refAmpl * cos(rad);
    }

    // Create filter profiles for colour filtering.
    //
    // One can argue over merits of different filters, but I stick with simple
    // raised cosine unless there's compelling reason to do otherwise.
    // PAL-I colour bandwidth should be around 1.1 or 1.2 MHz:
    // acc to Rec.470, +1066 or -1300kHz span of colour sidebands!
    // The width of the filter window should scale with the sample rate.
    //
    // chromaBandwidthHz values between 1.1MHz and 1.3MHz can be tried. Some
    // specific values in that range may work best at minimising residual dot
    // pattern at given sample rates due to the discrete nature of the filters.
    // It'd be good to find ways to optimise this more rigourously.
    //
    // Note in principle you could have different bandwidths for extracting the
    // luma and chroma, according to aesthetic tradeoffs. Not really very
    // justifyable though. Keeping the Y and C bandwidth the same (or at least
    // similar enough for the filters to be the same size) allows them to be
    // computed together later.
    //
    // The 0.93 is a bit empirical for the 4Fsc sampled LaserDisc scans.
    const double chromaBandwidthHz = 1100000.0 / 0.93;

    // Compute filter widths based on chroma bandwidth.
    // FILTER_SIZE must be wide enough to hold both filters (and ideally no
    // wider, else we're doing more computation than we need to).
    // XXX where does the 0.5* come from?
    const double ca = 0.5 * videoParameters.sampleRate / chromaBandwidthHz;
    const double ya = 0.5 * videoParameters.sampleRate / chromaBandwidthHz;
    assert(FILTER_SIZE >= static_cast<qint32>(ca));
    assert(FILTER_SIZE >= static_cast<qint32>(ya));

    // Note that we choose to make the y-filter *much* less selective in the
    // vertical direction: this is to prevent castellation on horizontal colour
    // boundaries.
    //
    // We may wish to broaden vertical bandwidth *slightly* so as to better
    // pass one- or two-line colour bars - underlines/graphics etc.

    double cdiv = 0, ydiv = 0;
    for (qint32 f = 0; f <= FILTER_SIZE; f++) {
        // 0-2-4-6 sequence here because we're only processing one field.
        const double fc   = qMin(ca, static_cast<double>(f));
        const double ff   = qMin(ca, sqrt(f * f + 2 * 2));
        const double fff  = qMin(ca, sqrt(f * f + 4 * 4));
        const double ffff = qMin(ca, sqrt(f * f + 6 * 6));

        // Divider because we're only making half a filter-kernel and the
        // zero-th point (vertically) is counted twice later
        const qint32 d = (f == 0) ? 2 : 1;

        // For U/V.
        // 0, 2, 1, 3 are vertical taps 0, +/- 1, +/- 2, +/- 3 (see filter loop below).
        cfilt[f][0] = 256 * (1 + cos(M_PI * fc   / ca)) / d;
        cfilt[f][2] = 256 * (1 + cos(M_PI * ff   / ca)) / d;
        cfilt[f][1] = 256 * (1 + cos(M_PI * fff  / ca)) / d;
        cfilt[f][3] = 256 * (1 + cos(M_PI * ffff / ca)) / d;

        cdiv += 1 * cfilt[f][0] + 2 * cfilt[f][2] + 2 * cfilt[f][1] + 2 * cfilt[f][3];

        const double fy   = qMin(ya, static_cast<double>(f));
        const double fffy = qMin(ya, sqrt(f * f + 4 * 4));

        // For Y, only use lines n, n+/-2: the others cancel!!!
        //  *have tried* using lines +/-1 & 3 --- can be made to work, but
        //  introduces *phase-sensitivity* to the filter -> leaks too much
        //  subcarrier if *any* phase-shifts!
        // note omission of yfilt taps 1 and 3 for PAL
        //
        // Tap 2 is only used for PAL; 0.2 factor makes it much less sensitive
        // to adjacent lines and reduces castellations and residual dot
        // patterning.
        //
        // 0, 1 are vertical taps 0, +/- 2 (see filter loop below).
        yfilt[f][0] =       256 * (1 + cos(M_PI * fy   / ya)) / d;
        yfilt[f][1] = 0.2 * 256 * (1 + cos(M_PI * fffy / ya)) / d;

        ydiv += 1 * yfilt[f][0] + 2 * 0 + 2 * yfilt[f][1] + 2 * 0;
    }

    // Normalise the filter coefficients.
    // We've already doubled above for horizontal symmetry; do it again for vertical symmetry.
    cdiv *= 2;
    ydiv *= 2;
    for (qint32 f = 0; f <= FILTER_SIZE; f++) {
        for (qint32 i = 0; i < 4; i++) {
            cfilt[f][i] /= cdiv;
        }
        for (qint32 i = 0; i < 2; i++) {
            yfilt[f][i] /= ydiv;
        }
    }

    // Calculate the frame height and resize the output buffer
    const qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;
    outputFrame.resize(videoParameters.fieldWidth * frameHeight * 6);
}

// Performs a decode of the 16-bit greyscale input frame and produces a RGB 16-16-16-bit output frame
// with 16 bit processing
QByteArray PalColour::performDecode(QByteArray firstFieldData, QByteArray secondFieldData, qint32 contrast, qint32 saturation)
{
    // Ensure the object has been configured
    if (!configurationSet) {
        qDebug() << "PalColour::performDecode(): Called, but the object has not been configured";
        return nullptr;
    }

    // Fill the output frame with zeros to ensure there is no random data in areas where there
    // is no picture data
    outputFrame.fill(0);

    if (!firstFieldData.isNull()) {
        FieldInfo field(0, contrast, saturation, configuration.firstActiveLine, configuration.lastActiveLine);
        decodeField(field, firstFieldData);
    }
    if (!secondFieldData.isNull()) {
        FieldInfo field(1, contrast, saturation, configuration.firstActiveLine, configuration.lastActiveLine);
        decodeField(field, secondFieldData);
    }

    return outputFrame;
}

PalColour::FieldInfo::FieldInfo(qint32 _number, qint32 _contrast, qint32 _saturation, qint32 firstActiveLine, qint32 lastActiveLine)
    : number(_number), contrast(_contrast), saturation(_saturation)
{
    // Work out the active lines to be decoded within this field.
    // If firstActiveLine or lastActiveLine is odd, we can end up with
    // different ranges for top/bottom fields, so we need to be careful
    // about how this is rounded.
    firstLine = (firstActiveLine + 1 - number) / 2;
    lastLine = (lastActiveLine + 1 - number) / 2;
}

void PalColour::decodeField(const FieldInfo &field, const QByteArray &fieldData)
{
    // Pointer to the input field data
    const quint16 *inputData = reinterpret_cast<const quint16 *>(fieldData.data());

    const double *chromaData = nullptr;
    if (configuration.useTransformFilter) {
        // Use Transform PAL filter to extract chroma
        chromaData = transformPal.filterField(field.number, fieldData);
    }

    for (qint32 fieldLine = field.firstLine; fieldLine < field.lastLine; fieldLine++) {
        LineInfo line(fieldLine);

        // Detect the colourburst from the composite signal
        detectBurst(line, inputData);

        if (configuration.useTransformFilter) {
            // Decode chroma and luma from the Transform PAL output
            decodeLine(field, line, chromaData, inputData);
        } else {
            // Decode chroma and luma from the composite signal
            decodeLine(field, line, inputData, inputData);
        }
    }
}

PalColour::LineInfo::LineInfo(qint32 _number)
    : number(_number)
{
}

void PalColour::detectBurst(LineInfo &line, const quint16 *inputData)
{
    // Dummy black line, used when the filter needs to look outside the field.
    static constexpr quint16 blackLine[MAX_WIDTH] = {0};

    // Get pointers to the surrounding lines of input data.
    // If a line we need is outside the field, use blackLine instead.
    // (Unlike below, we don't need to stay in the active area, since we're
    // only looking at the colourburst.)
    const quint16 *in0, *in1, *in2, *in3, *in4;
    in0 =                                                                 inputData +  (line.number      * videoParameters.fieldWidth);
    in1 = (line.number - 1) <  0                           ? blackLine : (inputData + ((line.number - 1) * videoParameters.fieldWidth));
    in2 = (line.number + 1) >= videoParameters.fieldHeight ? blackLine : (inputData + ((line.number + 1) * videoParameters.fieldWidth));
    in3 = (line.number - 2) <  0                           ? blackLine : (inputData + ((line.number - 2) * videoParameters.fieldWidth));
    in4 = (line.number + 2) >= videoParameters.fieldHeight ? blackLine : (inputData + ((line.number + 2) * videoParameters.fieldWidth));

    // Find absolute burst phase relative to the reference carrier by
    // product detection.
    //
    // To avoid hue-shifts on alternate lines, the phase is determined by
    // averaging the phase on the current-line with the average of two
    // other lines, one above and one below the current line.
    //
    // For PAL we use the next-but-one line above and below (in the field),
    // which will have the same V-switch phase as the current-line (and 180
    // degree change of phase), and we also analyse the average (bpo/bqo
    // 'old') of the line immediately above and below, which have the
    // opposite V-switch phase (and a 90 degree subcarrier phase shift).
    double bp = 0, bq = 0, bpo = 0, bqo = 0;
    for (qint32 i = videoParameters.colourBurstStart; i < videoParameters.colourBurstEnd; i++) {
        bp += ((in0[i] - ((in3[i] + in4[i]) / 2)) / 2) * sine[i];
        bq += ((in0[i] - ((in3[i] + in4[i]) / 2)) / 2) * cosine[i];
        bpo += ((in2[i] - in1[i]) / 2) * sine[i];
        bqo += ((in2[i] - in1[i]) / 2) * cosine[i];
    }

    // Normalise the sums above
    const qint32 colourBurstLength = videoParameters.colourBurstEnd - videoParameters.colourBurstStart;
    bp /= colourBurstLength;
    bq /= colourBurstLength;
    bpo /= colourBurstLength;
    bqo /= colourBurstLength;

    // Detect the V-switch state on this line.
    //
    // I forget exactly why this works, but it's essentially comparing the
    // vector magnitude /difference/ between the phases of the burst on the
    // present line and previous line to the magnitude of the burst. This
    // may effectively be a dot-product operation...
    line.Vsw = -1;
    if ((((bp - bpo) * (bp - bpo) + (bq - bqo) * (bq - bqo)) < (bp * bp + bq * bq) * 2)) {
        line.Vsw = 1;
    }

    // Average the burst phase to get -U (reference) phase out -- burst
    // phase is (-U +/-V). bp and bq will be of the order of 1000.
    line.bp = (bp - bqo) / 2;
    line.bq = (bq + bpo) / 2;

    // burstNorm normalises bp and bq to 1.
    // Kill colour if burst too weak.
    // XXX magic number 130000 !!! check!
    line.burstNorm = qMax(sqrt(line.bp * line.bp + line.bq * line.bq), 130000.0 / 128);
}

template <typename InputSample>
void PalColour::decodeLine(const FieldInfo &field, const LineInfo &line, const InputSample *inputData, const quint16 *compData)
{
    // Dummy black line, used when the filter needs to look outside the active region.
    static constexpr InputSample blackLine[MAX_WIDTH] = {0};

    // Get pointers to the surrounding lines of input data.
    // If a line we need is outside the active area, use blackLine instead.
    const InputSample *in0, *in1, *in2, *in3, *in4, *in5, *in6;
    in0 =                                                     inputData +  (line.number      * videoParameters.fieldWidth);
    in1 = (line.number - 1) <  field.firstLine ? blackLine : (inputData + ((line.number - 1) * videoParameters.fieldWidth));
    in2 = (line.number + 1) >= field.lastLine  ? blackLine : (inputData + ((line.number + 1) * videoParameters.fieldWidth));
    in3 = (line.number - 2) <  field.firstLine ? blackLine : (inputData + ((line.number - 2) * videoParameters.fieldWidth));
    in4 = (line.number + 2) >= field.lastLine  ? blackLine : (inputData + ((line.number + 2) * videoParameters.fieldWidth));
    in5 = (line.number - 2) <  field.firstLine ? blackLine : (inputData + ((line.number - 3) * videoParameters.fieldWidth));
    in6 = (line.number + 3) >= field.lastLine  ? blackLine : (inputData + ((line.number + 3) * videoParameters.fieldWidth));

    // Check that the filter isn't going to run out of data horizontally.
    assert(videoParameters.activeVideoStart - FILTER_SIZE >= videoParameters.colourBurstEnd);
    assert(videoParameters.activeVideoEnd + FILTER_SIZE + 1 <= videoParameters.fieldWidth);

    // Multiply the composite input signal by the reference carrier, giving
    // quadrature samples where the colour subcarrier is now at 0 Hz.
    // (There will be a considerable amount of energy at higher frequencies
    // resulting from the luma information and aliases of the signal, so
    // we need to low-pass filter it before extracting the colour
    // components.)
    //
    // As the 2D filters are vertically symmetrical, we can pre-compute the
    // sums of pairs of lines above and below line.number to save some work
    // in the inner loop below.
    //
    // Vertical taps 1 and 2 are swapped in the array to save one addition
    // in the filter loop, as U and V use the same sign for taps 0 and 2.
    double m[4][MAX_WIDTH], n[4][MAX_WIDTH];
    for (qint32 i = videoParameters.activeVideoStart - FILTER_SIZE; i < videoParameters.activeVideoEnd + FILTER_SIZE + 1; i++) {
        m[0][i] =  in0[i] * sine[i];
        m[2][i] =  in1[i] * sine[i] - in2[i] * sine[i];
        m[1][i] = -in3[i] * sine[i] - in4[i] * sine[i];
        m[3][i] = -in5[i] * sine[i] + in6[i] * sine[i];

        n[0][i] =  in0[i] * cosine[i];
        n[2][i] =  in1[i] * cosine[i] - in2[i] * cosine[i];
        n[1][i] = -in3[i] * cosine[i] - in4[i] * cosine[i];
        n[3][i] = -in5[i] * cosine[i] + in6[i] * cosine[i];
    }

    // p & q should be sine/cosine components' amplitudes
    // NB: Multiline averaging/filtering assumes perfect
    //     inter-line phase registration...

    double pu[MAX_WIDTH], qu[MAX_WIDTH], pv[MAX_WIDTH], qv[MAX_WIDTH], py[MAX_WIDTH], qy[MAX_WIDTH];
    for (qint32 i = videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++) {
        double PU = 0, QU = 0, PV = 0, QV = 0, PY = 0, QY = 0;

        // Carry out 2D filtering. P and Q are the two arbitrary SINE & COS
        // phases components. U filters for U, V for V, and Y for Y.
        //
        // U and V are the same for lines n ([0]), n+/-2 ([1]), but
        // differ in sign for n+/-1 ([2]), n+/-3 ([3]) owing to the
        // forward/backward axis slant.

        for (qint32 b = 0; b <= FILTER_SIZE; b++) {
            const qint32 l = i - b;
            const qint32 r = i + b;

            PY += (m[0][r] + m[0][l]) * yfilt[b][0] + (m[1][r] + m[1][l]) * yfilt[b][1];
            QY += (n[0][r] + n[0][l]) * yfilt[b][0] + (n[1][r] + n[1][l]) * yfilt[b][1];

            PU += (m[0][r] + m[0][l]) * cfilt[b][0] + (m[1][r] + m[1][l]) * cfilt[b][1]
                    + (n[2][r] + n[2][l]) * cfilt[b][2] + (n[3][r] + n[3][l]) * cfilt[b][3];
            QU += (n[0][r] + n[0][l]) * cfilt[b][0] + (n[1][r] + n[1][l]) * cfilt[b][1]
                    - (m[2][r] + m[2][l]) * cfilt[b][2] - (m[3][r] + m[3][l]) * cfilt[b][3];
            PV += (m[0][r] + m[0][l]) * cfilt[b][0] + (m[1][r] + m[1][l]) * cfilt[b][1]
                    - (n[2][r] + n[2][l]) * cfilt[b][2] - (n[3][r] + n[3][l]) * cfilt[b][3];
            QV += (n[0][r] + n[0][l]) * cfilt[b][0] + (n[1][r] + n[1][l]) * cfilt[b][1]
                    + (m[2][r] + m[2][l]) * cfilt[b][2] + (m[3][r] + m[3][l]) * cfilt[b][3];
        }

        pu[i] = PU;
        qu[i] = QU;
        pv[i] = PV;
        qv[i] = QV;
        py[i] = PY;
        qy[i] = QY;
    }

    // Pointer to composite signal data
    const quint16 *comp = compData + (line.number * videoParameters.fieldWidth);

    // Define scan line pointer to output buffer using 16 bit unsigned words
    quint16 *ptr = reinterpret_cast<quint16 *>(outputFrame.data()
                                               + (((line.number * 2) + field.number) * videoParameters.fieldWidth * 6));

    // Gain for the Y component, to put black at 0 and peak white at 65535
    const double scaledContrast = (65535.0 / (videoParameters.white16bIre - videoParameters.black16bIre)) * field.contrast / 100.0;

    // Gain for the U/V components
    const double scaledSaturation = (field.saturation / 50.0) / line.burstNorm;

    for (qint32 i = videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++) {
        // Compute luma by...
        double rY;
        if (configuration.useTransformFilter) {
            // ... subtracting pre-filtered chroma from the composite input
            rY = comp[i] - in0[i];
        } else {
            // ... resynthesising the chroma signal that the Y filter
            // extracted, and subtracting it from the composite input
            rY = comp[i] - ((py[i] * sine[i] + qy[i] * cosine[i]) / refNorm);
        }

        // Scale to 16-bit output
        rY = qBound(0.0, (rY - videoParameters.black16bIre) * scaledContrast, 65535.0);

        // Rotate the p&q components (at the arbitrary sine/cosine
        // reference phase) backwards by the burst phase (relative to the
        // reference phase), in order to recover U and V. The Vswitch is
        // applied to flip the V-phase on alternate lines for PAL.
        const double rU =            -((pu[i] * line.bp + qu[i] * line.bq)) * scaledSaturation;
        const double rV = line.Vsw * -((qv[i] * line.bp - pv[i] * line.bq)) * scaledSaturation;

        // Convert YUV to RGB, saturating levels at 0-65535 to prevent overflow.
        // This conversion is taken from Video Demystified (5th edition) page 18.
        const double R = qBound(0.0, rY + (1.140 * rV),                65535.0);
        const double G = qBound(0.0, rY - (0.395 * rU) - (0.581 * rV), 65535.0);
        const double B = qBound(0.0, rY + (2.032 * rU),                65535.0 );

        // Pack the data back into the RGB 16/16/16 buffer
        const qint32 pp = i * 3; // 3 words per pixel
        ptr[pp + 0] = static_cast<quint16>(R);
        ptr[pp + 1] = static_cast<quint16>(G);
        ptr[pp + 2] = static_cast<quint16>(B);
    }
}
