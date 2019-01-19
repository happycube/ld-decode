/************************************************************************

    palcolour.cpp

    Performs 2D subcarrier filtering to process stand-alone fields of
    a video signal

    Copyright (C) 2018  William Andrew Steer
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-pal is free software: you can redistribute it and/or
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

void PalColour::updateConfiguration(LdDecodeMetaData::VideoParameters videoParametersParam)
{
    // Copy the configuration parameters
    videoParameters = videoParametersParam;

    // Build the look-up tables
    buildLookUpTables();

    configurationSet = true;
}

// Private method to build the look up tables
// must be called by the constructor when the object is created
void PalColour::buildLookUpTables(void)
{
    // Step 1: create sine/cosine lookups
    refAmpl = 1.28;
    normalise = (refAmpl * refAmpl / 2);     // refAmpl is the integer sinewave amplitude

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
    // dot pattern at given sample rates due to the discrete nature of the filters. It'd be good to find ways to optimise this more rigourously
    double chromaBandwidthHz=1100000.0 /0.93; // the 0.93 is a bit empirical for the 4Fsc sampled LaserDisc scans
    double ca=0.5*videoParameters.sampleRate/chromaBandwidthHz, ya=0.5*videoParameters.sampleRate/chromaBandwidthHz; // where does the 0.5* come from?
    // note in principle you could have different bandwidths for extracting the luma and chroma, according to aesthetic tradeoffs. Not really very justifyable though.

    // Simon: The array declarations (used here and in the processing method) have been moved
    // to the class' private space (in the .h)
    cdiv=0; ydiv=0;

    // Note that we choose to make the y-filter *much* less selective in the vertical direction:
    // - this is to prevent castellation on horizontal colour boundaries.

    // may wish to broaden vertical bandwidth *slightly* so as to better pass
    // one- or two-line colour bars - underlines/graphics etc.

    // Note also that if Y-bandwidth was made the same as C,
    // and that 'lines' of the masks were equivalent, then
    // significant time-savings could be made.

    for (int16_t f=0; f<=arraySize; f++)
    {
        double  fc=f; if (fc>ca) fc=ca;
        double  ff=sqrt(f*f+2*2); if ( ff>ca)  ff=ca;  // 2 -- 4 -- 6 sequence
        double fff=sqrt(f*f+4*4); if (fff>ca) fff=ca;  // because only one FIELD!
        double ffff=sqrt(f*f+6*6); if (ffff>ca) ffff=ca;

        qint32 d;
        if (f==0) d=2; else d=1; // divider because we're only making half a filter-kernel and the zero-th poqint32 is counted twice later.

        cfilt0[f]=256*(1+cos(M_PI*fc/ca))/d;
        cfilt1[f]=256*(1+cos(M_PI*ff/ca))/d;
        cfilt2[f]=256*(1+cos(M_PI*fff/ca))/d;
        cfilt3[f]=256*(1+cos(M_PI*ffff/ca))/d;

        cdiv+=cfilt0[f]+2*cfilt1[f]+2*cfilt2[f]+2*cfilt3[f];

        double  fy=f; if (fy>ya) fy=ya;
        double ffy=sqrt(f*f+2*2); if (ffy>ya) ffy=ya;
        double fffy=sqrt(f*f+4*4); if (fffy>ya) fffy=ya;

        yfilt0[f]=256*(1+cos(M_PI*fy/ya))/d;
        yfilt2[f]=0.2*256*(1+cos(M_PI*fffy/ya))/d;  // only used for PAL NB 0.2 makes much less sensitive to adjacent lines and reduces castellations and residual dot patterning

        ydiv+=yfilt0[f]+2*0+2*yfilt2[f]+2*0;
    }
    cdiv*=2; ydiv*=2;

    // Calculate the frame height and resize the output buffer
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;
    outputFrame.resize(videoParameters.fieldWidth * frameHeight * 6);
}

// Performs a decode of the 16-bit greyscale input frame and produces a RGB 16-16-16-bit output frame
// with 16 bit processing
//
// Note: This method does not clear the output array before writing to it; if there is garbage
// in the allocated memory, it will be in the output with the decoded image on top.
QByteArray PalColour::performDecode(QByteArray firstFieldData, QByteArray secondFieldData, qint32 brightness, qint32 saturation, bool blackAndWhite)
{
    // Ensure the object has been configured
    if (!configurationSet) {
        qDebug() << "PalColour::performDecode(): Called, but the object has not been configured";
        return nullptr;
    }

    // Note: 1.75 is the nominal scaling factor of 75% amplitude for full-range digitised
    // composite (with sync at code 0 or 1, blanking at code 64 (40h), and peak white at
    // code 211 (d3h) to give 0-255 RGB).
    double scaledBrightness = 1.75 * brightness / 100.0;

    if (!firstFieldData.isNull() && !secondFieldData.isNull()) {
        // Step 2:
        quint16 Y[MAX_WIDTH];

        // were all short ints
        double pu[MAX_WIDTH], qu[MAX_WIDTH], pv[MAX_WIDTH], qv[MAX_WIDTH], py[MAX_WIDTH], qy[MAX_WIDTH];
        double m[MAX_WIDTH], n[MAX_WIDTH];
        double m1[MAX_WIDTH], n1[MAX_WIDTH], m2[MAX_WIDTH], n2[MAX_WIDTH];
        double m3[MAX_WIDTH], n3[MAX_WIDTH], m4[MAX_WIDTH], n4[MAX_WIDTH];
        double m5[MAX_WIDTH], n5[MAX_WIDTH], m6[MAX_WIDTH], n6[MAX_WIDTH];

        qint32 Vsw; // this will represent the PAL Vswitch state later on...

        // Since we're not using Image objects, we need a pointer to the 16-bit image data
        quint16 *topFieldDataPointer = reinterpret_cast<quint16*>(firstFieldData.data());
        quint16 *bottomFieldDataPointer = reinterpret_cast<quint16*>(secondFieldData.data());

        // Define the 16-bit line buffers
        quint16 *b0 = nullptr;
        quint16 *b1 = nullptr;
        quint16 *b2 = nullptr;
        quint16 *b3 = nullptr;
        quint16 *b4 = nullptr;
        quint16 *b5 = nullptr;
        quint16 *b6 = nullptr;

        for (qint32 field = 0; field < 2; field++) {
            for (qint32 fieldLine = 3; fieldLine < (videoParameters.fieldHeight - 4); fieldLine++) {
                if (field == 0) {
                    for (qint32 x = videoParameters.colourBurstStart; x < videoParameters.fieldWidth; x++) {
                        b0 = topFieldDataPointer+ (fieldLine      * (videoParameters.fieldWidth)) + x;
                        b1 = topFieldDataPointer+((fieldLine - 1) * (videoParameters.fieldWidth)) + x;
                        b2 = topFieldDataPointer+((fieldLine + 1) * (videoParameters.fieldWidth)) + x;
                        b3 = topFieldDataPointer+((fieldLine - 2) * (videoParameters.fieldWidth)) + x;
                        b4 = topFieldDataPointer+((fieldLine + 2) * (videoParameters.fieldWidth)) + x;
                        b5 = topFieldDataPointer+((fieldLine - 3) * (videoParameters.fieldWidth)) + x;
                        b6 = topFieldDataPointer+((fieldLine + 3) * (videoParameters.fieldWidth)) + x;
                    }
                } else {
                    for (qint32 x = videoParameters.colourBurstStart; x < videoParameters.fieldWidth; x++) {
                        b0 = bottomFieldDataPointer+ (fieldLine      * (videoParameters.fieldWidth)) + x;
                        b1 = bottomFieldDataPointer+((fieldLine - 1) * (videoParameters.fieldWidth)) + x;
                        b2 = bottomFieldDataPointer+((fieldLine + 1) * (videoParameters.fieldWidth)) + x;
                        b3 = bottomFieldDataPointer+((fieldLine - 2) * (videoParameters.fieldWidth)) + x;
                        b4 = bottomFieldDataPointer+((fieldLine + 2) * (videoParameters.fieldWidth)) + x;
                        b5 = bottomFieldDataPointer+((fieldLine - 3) * (videoParameters.fieldWidth)) + x;
                        b6 = bottomFieldDataPointer+((fieldLine + 3) * (videoParameters.fieldWidth)) + x;
                    }
                }

                for (qint32 i = videoParameters.colourBurstStart; i < videoParameters.fieldWidth; i++) {
                    m[i]=b0[i]*sine[i]; n[i]=b0[i]*cosine[i];

                    m1[i]=b1[i]*sine[i];  n1[i]=b1[i]*cosine[i];
                    m2[i]=b2[i]*sine[i];  n2[i]=b2[i]*cosine[i];
                    m3[i]=b3[i]*sine[i];  n3[i]=b3[i]*cosine[i];
                    m4[i]=b4[i]*sine[i];  n4[i]=b4[i]*cosine[i];
                    m5[i]=b5[i]*sine[i];  n5[i]=b5[i]*cosine[i];
                    m6[i]=b6[i]*sine[i];  n6[i]=b6[i]*cosine[i];
                }

                // Find absolute burst phase

                //  To avoid hue-shifts on alternate lines, the phase is determined by averaging the phase on the current-line with the average of
                //  two other lines, one above and one below the current line.
                //   For NTSC we use the scan-lines immediately above and below (in the field), which we know have exactly 180 degrees burst phase shift to the present line
                //   For PAL we use the next-but-one line above and below (in the field), which will have the same V-switch phase as the current-line (and 180 degree change of phase)
                //    but for PAL we also analyse the average (bpo,bqo 'old') of the line immediately above and below, which have the opposite V-switch phase (and a 90 degree subcarrier phase shift)

                // this is a classic "product-" or "synchronous demodulation" operation. We "detect" the burst relative to the arbitrary sine[] and cosine[] reference phases
                qint32 bp=0, bq=0, bpo=0, bqo=0;
                for (qint32 i=videoParameters.colourBurstStart; i<videoParameters.colourBurstEnd; i++) {
                    bp+=(m[i]-(m3[i]+m4[i])/2)/2;
                    bq+=(n[i]-(n3[i]+n4[i])/2)/2;
                    bpo+=(m2[i]-m1[i])/2;
                    bqo+=(n2[i]-n1[i])/2;
                }

                bp/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart);  bq/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart);  // normalises those sums
                bpo/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart); bqo/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart); // normalises those sums

                // Generate V-switch phase - I forget exactly why this works, but it's essentially comparing the vector magnitude /difference/ between the
                // phases of the burst on the present line and previous line to the magnitude of the burst. This may effectively be a dot-product operation...
                if (((bp-bpo)*(bp-bpo)+(bq-bqo)*(bq-bqo))<(bp*bp+bq*bq)*2) Vsw=1; else Vsw=-1;

                // NB bp and bq will be of the order of 1000. CHECK!!
                bp=(bp-bqo)/2;
                bq=(bq+bpo)/2;

                // ave the phase of burst from two lines to get -U (reference) phase out (burst phase is (-U +/-V)
                // if NTSC then leave bp as-is, we take bp,bq as the underlying -U (reference) phase.

                //qint32 norm=sqrt(bp*bp+bq*bq)*refAmpl*16; // 16 empirical scaling factor
                double norm=sqrt(bp*bp+bq*bq); // TRIAL - 7 Oct 2005

                // kill colour if burst too weak!  magic number 130000 !!! check!
                if (norm<(130000 / 128)) {
                    norm=130000 / 128;
                }

                // p & q should be sine/cosine components' amplitudes
                // NB: Multiline averaging/filtering assumes perfect
                //     inter-line phase registration...

                qint32 PU,QU, PV,QV, PY,QY;
                for (qint32 i = videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++) {
                    PU=QU=0; PV=QV=0; PY=QY=0;

                    // Carry out 2D filtering. P and Q are the two arbitrary SINE & COS
                    // phases components. U filters for U, V for V, and Y for Y
                    // U and V are the same for lines n, n+/-2, but differ in sign for
                    // n+/-1, n+/-3 owing to the forward/backward axis slant
                    // For Y, only use lines n, n+/-2: the others cancel!!!
                    //  *have tried* using lines +/-1 & 3 --- can be made to work, but
                    //  introduces *phase-sensitivity* to the filter -> leaks too much
                    //  subcarrier if *any* phase-shifts!

                    qint32 l,r;

                    for (qint32 b = 0; b <= arraySize; b++)
                    {
                        l=i-b; r=i+b;

                        PU+=(m[r]+m[l])*cfilt0[b]+(+n1[r]+n1[l]-n2[l]-n2[r])*cfilt1[b]-(m3[l]+m3[r]+m4[l]+m4[r])*cfilt2[b]+(-n5[r]-n5[l]+n6[l]+n6[r])*cfilt3[b];
                        QU+=(n[r]+n[l])*cfilt0[b]+(-m1[r]-m1[l]+m2[l]+m2[r])*cfilt1[b]-(n3[l]+n3[r]+n4[l]+n4[r])*cfilt2[b]+(+m5[r]+m5[l]-m6[l]-m6[r])*cfilt3[b];
                        PV+=(m[r]+m[l])*cfilt0[b]+(-n1[r]-n1[l]+n2[l]+n2[r])*cfilt1[b]-(m3[l]+m3[r]+m4[l]+m4[r])*cfilt2[b]+(+n5[r]+n5[l]-n6[l]-n6[r])*cfilt3[b];
                        QV+=(n[r]+n[l])*cfilt0[b]+(+m1[r]+m1[l]-m2[l]-m2[r])*cfilt1[b]-(n3[l]+n3[r]+n4[l]+n4[r])*cfilt2[b]+(-m5[r]-m5[l]+m6[l]+m6[r])*cfilt3[b];

                        PY+=(m[r]+m[l])*yfilt0[b]-(m3[l]+m3[r]+m4[l]+m4[r])*yfilt2[b];  // note omission of yfilt[1] and [3] for PAL
                        QY+=(n[r]+n[l])*yfilt0[b]-(n3[l]+n3[r]+n4[l]+n4[r])*yfilt2[b];  // note omission of yfilt[1] and [3] for PAL
                    }
                    pu[i]=PU/cdiv; qu[i]=QU/cdiv;
                    pv[i]=PV/cdiv; qv[i]=QV/cdiv;
                    py[i]=PY/ydiv; qy[i]=QY/ydiv;
                }

                // Generate the luminance (Y), by filtering out Fsc (by re-synthesising the detected py qy and subtracting), and subtracting the black-level
                for (qint32 i=videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++) {
                    qint32 tmp = static_cast<qint32>(b0[i]-(py[i]*sine[i]+qy[i]*cosine[i]) / normalise - videoParameters.black16bIre);
                    if (tmp < 0) tmp = 0;
                    if (tmp > 65535) tmp = 65535;
                    Y[i] = static_cast<quint16>(tmp);
                }

                // Define scan line pointer to output buffer using 16 bit unsigned words
                quint16 *ptr = reinterpret_cast<quint16*>(outputFrame.data() + (((fieldLine * 2) + field + 2) * videoParameters.fieldWidth * 6));

                // 'saturation' is a user saturation control, nom. 100%
                double scaledSaturation = (saturation / 50.0) / norm;  // 'norm' normalises bp and bq to 1
                double R, G, B;
                double rY, rU, rV;

                for (qint32 i = videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++)
                {
                    // the next two lines "rotate" the p&q components (at the arbitrary sine/cosine reference phase) backwards by the
                    // burst phase (relative to the arb phase), in order to recover U and V. The Vswitch is applied to flip the V-phase on alternate lines for PAL
                    // The scaledBrightness provides 75% amplitude (x1.75)
                    rY = Y[i] * scaledBrightness;
                    rU = (-((pu[i]*bp+qu[i]*bq)) * scaledSaturation);
                    rV = (-(Vsw*(qv[i]*bp-pv[i]*bq)) * scaledSaturation);

                    // Remove UV colour components if black and white (Y only) output is required
                    if (blackAndWhite) {
                        rU = 0;
                        rV = 0;
                    }

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
