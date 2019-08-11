/************************************************************************

    palcolour.cpp

    Performs 2D subcarrier filtering to process stand-alone fields of
    a video signal

    Copyright (C) 2018  William Andrew Steer
    Copyright (C) 2018-2019 Simon Inns

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

PalColour::PalColour(QObject *parent) : QObject(parent)
{
    configurationSet = false;
}

void PalColour::updateConfiguration(LdDecodeMetaData::VideoParameters videoParametersParam,
                                    qint32 firstActiveLineParam, qint32 lastActiveLineParam)
{
    // Copy the configuration parameters
    videoParameters = videoParametersParam;
    firstActiveLine = firstActiveLineParam;
    lastActiveLine = lastActiveLineParam;

    // Build the look-up tables
    buildLookUpTables();

    configurationSet = true;
}

// Private method to build the look up tables
// must be called by the constructor when the object is created
void PalColour::buildLookUpTables()
{
    // Generate quadrature samples of a sine wave at the subcarrier frequency.
    // We'll use this for two purposes below:
    // - product-detecting the line samples, to give us quadrature samples of
    //   the chroma information centred on 0 Hz
    // - working out what the phase of the subcarrier is on each line,
    //   so we can rotate the chroma samples to put U/V on the right axes
    // refAmpl is the sinewave amplitude.
    refAmpl = 1.28;
    refNorm = (refAmpl * refAmpl / 2);

    double rad;
    for (qint32 i = 0; i < videoParameters.fieldWidth; i++)
    {
        rad=(2 * M_PI * i * videoParameters.fsc / videoParameters.sampleRate);
        sine[i] = refAmpl * sin(rad);
        cosine[i] = refAmpl * cos(rad);
    }

    // Next create filter-profiles for colour filtering.
    //  One can argue over merits of different filters, but I stick with simple raised cosine
    //  unless there's compelling reason to do otherwise.
    // PAL-I colour bandwidth should be around 1.1 or 1.2 MHz
    //  acc to Rec.470, +1066 or -1300kHz span of colour sidebands!

    // width of filter-window should therefore scale with samplerate

    // Create filter-profile lookup
    // chromaBandwidthHz values between 1.1MHz and 1.3MHz can be tried. Some specific values in that range may work best at minimising residual
    // dot pattern at given sample rates due to the discrete nature of the filters. It'd be good to find ways to optimise this more rigourously.
    // Note in principle you could have different bandwidths for extracting the luma and chroma, according to aesthetic tradeoffs. Not really very justifyable though.
    double chromaBandwidthHz=1100000.0 /0.93; // the 0.93 is a bit empirical for the 4Fsc sampled LaserDisc scans

    // Compute filter widths based on chroma bandwidth.
    // FILTER_SIZE must be wide enough to hold both filters (and ideally no
    // wider, else we're doing more computation than we need to).
    double ca=0.5*videoParameters.sampleRate/chromaBandwidthHz, ya=0.5*videoParameters.sampleRate/chromaBandwidthHz; // where does the 0.5* come from?
    assert(FILTER_SIZE >= static_cast<qint32>(ca));
    assert(FILTER_SIZE >= static_cast<qint32>(ya));

    double cdiv=0;
    double ydiv=0;

    // Note that we choose to make the y-filter *much* less selective in the vertical direction:
    // - this is to prevent castellation on horizontal colour boundaries.

    // may wish to broaden vertical bandwidth *slightly* so as to better pass
    // one- or two-line colour bars - underlines/graphics etc.

    // Note also that if Y-bandwidth was made the same as C,
    // and that 'lines' of the masks were equivalent, then
    // significant time-savings could be made.

    for (qint32 f = 0; f <= FILTER_SIZE; f++) {
        double  fc=f; if (fc>ca) fc=ca;
        double  ff=sqrt(f*f+2*2); if ( ff>ca)  ff=ca;  // 2 -- 4 -- 6 sequence
        double fff=sqrt(f*f+4*4); if (fff>ca) fff=ca;  // because only one FIELD!
        double ffff=sqrt(f*f+6*6); if (ffff>ca) ffff=ca;

        qint32 d;
        if (f==0) d=2; else d=1; // divider because we're only making half a filter-kernel and the zero-th poqint32 is counted twice later.

        // 0, 2, 1, 3 are vertical taps 0, +/- 1, +/- 2, +/- 3 (see filter loop below).
        cfilt[f][0]=256*(1+cos(M_PI*fc/ca))/d;
        cfilt[f][2]=256*(1+cos(M_PI*ff/ca))/d;
        cfilt[f][1]=256*(1+cos(M_PI*fff/ca))/d;
        cfilt[f][3]=256*(1+cos(M_PI*ffff/ca))/d;

        cdiv+=cfilt[f][0]+2*cfilt[f][2]+2*cfilt[f][1]+2*cfilt[f][3];

        double  fy=f; if (fy>ya) fy=ya;
        double fffy=sqrt(f*f+4*4); if (fffy>ya) fffy=ya;

        // For Y, only use lines n, n+/-2: the others cancel!!!
        //  *have tried* using lines +/-1 & 3 --- can be made to work, but
        //  introduces *phase-sensitivity* to the filter -> leaks too much
        //  subcarrier if *any* phase-shifts!
        // note omission of yfilt taps 1 and 3 for PAL

        // 0, 1 are vertical taps 0, +/- 2 (see filter loop below).
        yfilt[f][0]=256*(1+cos(M_PI*fy/ya))/d;
        yfilt[f][1]=0.2*256*(1+cos(M_PI*fffy/ya))/d;  // only used for PAL NB 0.2 makes much less sensitive to adjacent lines and reduces castellations and residual dot patterning

        ydiv+=yfilt[f][0]+2*0+2*yfilt[f][1]+2*0;
    }
    cdiv*=2; ydiv*=2;

    for (qint32 f = 0; f <= FILTER_SIZE; f++) {
        for (qint32 i = 0; i < 4; i++) {
            cfilt[f][i] /= cdiv;
        }
        for (qint32 i = 0; i < 2; i++) {
            yfilt[f][i] /= ydiv;
        }
    }

    // Calculate the frame height and resize the output buffer
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;
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

    // Scaling factor to put black at 0 and peak white at 65535
    double scaledContrast = (65535.0 / (videoParameters.white16bIre - videoParameters.black16bIre)) * contrast / 100.0;

    // Dummy black line, used when the 2D filter needs to look outside the active region.
    static constexpr quint16 blackLine[MAX_WIDTH] = {0};

    if (!firstFieldData.isNull() && !secondFieldData.isNull()) {
        double pu[MAX_WIDTH], qu[MAX_WIDTH], pv[MAX_WIDTH], qv[MAX_WIDTH], py[MAX_WIDTH], qy[MAX_WIDTH];
        double m[4][MAX_WIDTH], n[4][MAX_WIDTH];

        for (qint32 field = 0; field < 2; field++) {
            const quint16 *fieldData = reinterpret_cast<const quint16 *>(field == 0 ? firstFieldData.data()
                                                                                    : secondFieldData.data());

            // Work out the active lines to be decoded within this field.
            // If firstActiveLine or lastActiveLine is odd, we can end up with
            // different ranges for the two fields, so we need to be careful
            // about how this is rounded.
            const qint32 firstFieldLine = (firstActiveLine + 1 - field) / 2;
            const qint32 lastFieldLine = (lastActiveLine + 1 - field) / 2;

            for (qint32 fieldLine = firstFieldLine; fieldLine < lastFieldLine; fieldLine++) {
                // Get pointers to the surrounding lines.
                // If a line we need is outside the active area, use blackLine instead.
                const quint16 *b0, *b1, *b2, *b3, *b4, *b5, *b6;
                b0 =                                                  fieldData +  (fieldLine      * videoParameters.fieldWidth);
                b1 = (fieldLine - 1) <  firstFieldLine ? blackLine : (fieldData + ((fieldLine - 1) * videoParameters.fieldWidth));
                b2 = (fieldLine + 1) >= lastFieldLine  ? blackLine : (fieldData + ((fieldLine + 1) * videoParameters.fieldWidth));
                b3 = (fieldLine - 2) <  firstFieldLine ? blackLine : (fieldData + ((fieldLine - 2) * videoParameters.fieldWidth));
                b4 = (fieldLine + 2) >= lastFieldLine  ? blackLine : (fieldData + ((fieldLine + 2) * videoParameters.fieldWidth));
                b5 = (fieldLine - 2) <  firstFieldLine ? blackLine : (fieldData + ((fieldLine - 3) * videoParameters.fieldWidth));
                b6 = (fieldLine + 3) >= lastFieldLine  ? blackLine : (fieldData + ((fieldLine + 3) * videoParameters.fieldWidth));

                for (qint32 i = videoParameters.colourBurstStart; i < videoParameters.fieldWidth; i++) {
                    // The 2D filter is vertically symmetrical, so we can
                    // pre-compute the sums of pairs of lines above and below
                    // fieldLine to save some work in the inner loop below.
                    //
                    // Vertical taps 1 and 2 are swapped in the array to save
                    // one addition in the filter loop, as U and V are the same
                    // sign for taps 0 and 2.

                    m[0][i]=+b0[i]*sine[i];
                    m[2][i]=+b1[i]*sine[i]-b2[i]*sine[i];
                    m[1][i]=-b3[i]*sine[i]-b4[i]*sine[i];
                    m[3][i]=-b5[i]*sine[i]+b6[i]*sine[i];

                    n[0][i]=+b0[i]*cosine[i];
                    n[2][i]=+b1[i]*cosine[i]-b2[i]*cosine[i];
                    n[1][i]=-b3[i]*cosine[i]-b4[i]*cosine[i];
                    n[3][i]=-b5[i]*cosine[i]+b6[i]*cosine[i];
                }

                // Find absolute burst phase

                //  To avoid hue-shifts on alternate lines, the phase is determined by averaging the phase on the current-line with the average of
                //  two other lines, one above and one below the current line.
                //   For NTSC we use the scan-lines immediately above and below (in the field), which we know have exactly 180 degrees burst phase shift to the present line
                //   For PAL we use the next-but-one line above and below (in the field), which will have the same V-switch phase as the current-line (and 180 degree change of phase)
                //    but for PAL we also analyse the average (bpo,bqo 'old') of the line immediately above and below, which have the opposite V-switch phase (and a 90 degree subcarrier phase shift)

                // this is a classic "product-" or "synchronous demodulation" operation. We "detect" the burst relative to the arbitrary sine[] and cosine[] reference phases
                double bp=0, bq=0, bpo=0, bqo=0;
                for (qint32 i=videoParameters.colourBurstStart; i<videoParameters.colourBurstEnd; i++) {
                    bp+=(m[0][i]+(m[1][i]/2))/2;
                    bq+=(n[0][i]+(n[1][i]/2))/2;
                    bpo-=m[2][i]/2;
                    bqo-=n[2][i]/2;
                }

                bp/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart);  bq/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart);  // normalises those sums
                bpo/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart); bqo/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart); // normalises those sums

                // Generate V-switch phase - I forget exactly why this works, but it's essentially comparing the vector magnitude /difference/ between the
                // phases of the burst on the present line and previous line to the magnitude of the burst. This may effectively be a dot-product operation...
                double Vsw;
                if (((bp-bpo)*(bp-bpo)+(bq-bqo)*(bq-bqo))<(bp*bp+bq*bq)*2) Vsw=1; else Vsw=-1;

                // NB bp and bq will be of the order of 1000. CHECK!!
                bp=(bp-bqo)/2;
                bq=(bq+bpo)/2;

                // ave the phase of burst from two lines to get -U (reference) phase out (burst phase is (-U +/-V)
                // if NTSC then leave bp as-is, we take bp,bq as the underlying -U (reference) phase.

                // burstNorm normalises bp and bq to 1
                double burstNorm = sqrt(bp*bp+bq*bq);

                // kill colour if burst too weak!  magic number 130000 !!! check!
                if (burstNorm < (130000.0 / 128)) {
                    burstNorm = 130000.0 / 128;
                }

                // p & q should be sine/cosine components' amplitudes
                // NB: Multiline averaging/filtering assumes perfect
                //     inter-line phase registration...

                double PU,QU, PV,QV, PY,QY;
                for (qint32 i = videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++) {
                    PU=QU=0; PV=QV=0; PY=QY=0;

                    // Carry out 2D filtering. P and Q are the two arbitrary SINE & COS
                    // phases components. U filters for U, V for V, and Y for Y
                    // U and V are the same for lines n ([0]), n+/-2 ([1]), but
                    // differ in sign for n+/-1 ([2]), n+/-3 ([3]) owing to the
                    // forward/backward axis slant

                    qint32 l,r;

                    for (qint32 b = 0; b <= FILTER_SIZE; b++) {
                        l=i-b; r=i+b;

                        PY+=(m[0][r]+m[0][l])*yfilt[b][0]+(m[1][r]+m[1][l])*yfilt[b][1];
                        QY+=(n[0][r]+n[0][l])*yfilt[b][0]+(n[1][r]+n[1][l])*yfilt[b][1];

                        PU+=(m[0][r]+m[0][l])*cfilt[b][0]+(m[1][r]+m[1][l])*cfilt[b][1]+(n[2][r]+n[2][l])*cfilt[b][2]+(n[3][r]+n[3][l])*cfilt[b][3];
                        QU+=(n[0][r]+n[0][l])*cfilt[b][0]+(n[1][r]+n[1][l])*cfilt[b][1]-(m[2][r]+m[2][l])*cfilt[b][2]-(m[3][r]+m[3][l])*cfilt[b][3];
                        PV+=(m[0][r]+m[0][l])*cfilt[b][0]+(m[1][r]+m[1][l])*cfilt[b][1]-(n[2][r]+n[2][l])*cfilt[b][2]-(n[3][r]+n[3][l])*cfilt[b][3];
                        QV+=(n[0][r]+n[0][l])*cfilt[b][0]+(n[1][r]+n[1][l])*cfilt[b][1]+(m[2][r]+m[2][l])*cfilt[b][2]+(m[3][r]+m[3][l])*cfilt[b][3];
                    }
                    pu[i]=PU; qu[i]=QU;
                    pv[i]=PV; qv[i]=QV;
                    py[i]=PY; qy[i]=QY;
                }

                // Define scan line pointer to output buffer using 16 bit unsigned words
                quint16 *ptr = reinterpret_cast<quint16*>(outputFrame.data() + (((fieldLine * 2) + field) * videoParameters.fieldWidth * 6));

                // 'saturation' is a user saturation control, nom. 100%
                double scaledSaturation = (saturation / 50.0) / burstNorm;
                double R, G, B;
                double rY, rU, rV;

                for (qint32 i = videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++)
                {
                    // Generate the luminance (Y), by filtering out Fsc (by re-synthesising the detected py qy and subtracting), and subtracting the black-level
                    rY = b0[i] - ((py[i]*sine[i]+qy[i]*cosine[i]) / refNorm) - videoParameters.black16bIre;
                    rY *= scaledContrast;
                    if (rY < 0) rY = 0;
                    if (rY > 65535) rY = 65535;

                    // the next two lines "rotate" the p&q components (at the arbitrary sine/cosine reference phase) backwards by the
                    // burst phase (relative to the arb phase), in order to recover U and V. The Vswitch is applied to flip the V-phase on alternate lines for PAL
                    rU = (-((pu[i]*bp+qu[i]*bq)) * scaledSaturation);
                    rV = (-(Vsw*(qv[i]*bp-pv[i]*bq)) * scaledSaturation);

                    // This conversion is taken from Video Demystified (5th edition) page 18
                    R = ( rY + (1.140 * rV) );
                    G = ( rY - (0.395 * rU) - (0.581 * rV) );
                    B = ( rY + (2.032 * rU) );

                    // Saturate the levels at 0 and 100% in order to prevent range overflow
                    if (R < 0) R = 0;
                    if (R > 65535) R = 65535;
                    if (G < 0) G = 0;
                    if (G > 65535) G = 65535;
                    if (B < 0) B = 0;
                    if (B > 65535) B = 65535;

                    // Pack the data back into the RGB 16/16/16 buffer
                    qint32 pp = i * 3; // 3 words per pixel
                    ptr[pp+0] = static_cast<quint16>(R);
                    ptr[pp+1] = static_cast<quint16>(G);
                    ptr[pp+2] = static_cast<quint16>(B);
                }
            }
        }
    }

    return outputFrame;
}
