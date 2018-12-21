/************************************************************************

    palcolour.cpp

    Performs 2D subcarrier filtering to process stand-alone fields of
    a video signal

    Copyright (C) 2018  William Andrew Steer
    Copyright (C) 2018 Simon Inns

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

PalColour::PalColour(LdDecodeMetaData::VideoParameters videoParametersParam, QObject *parent) : QObject(parent)
{
    // Copy the configuration parameters
    videoParameters = videoParametersParam;

    // Build the look-up tables
    buildLookUpTables();
}

// Private method to build the look up tables
// must be called by the constructor when the object is created
void PalColour::buildLookUpTables(void)
{
    // Step 1: create sine/cosine lookups
    refAmpl = 128;    // original scaling for integer math

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

        cfilt[0][f]=256*(1+cos(M_PI*fc/ca))/d;
        cfilt[1][f]=256*(1+cos(M_PI*ff/ca))/d;
        cfilt[2][f]=256*(1+cos(M_PI*fff/ca))/d;
        cfilt[3][f]=256*(1+cos(M_PI*ffff/ca))/d;

        cdiv+=cfilt[0][f]+2*cfilt[1][f]+2*cfilt[2][f]+2*cfilt[3][f];

        double  fy=f; if (fy>ya) fy=ya;
        double ffy=sqrt(f*f+2*2); if (ffy>ya) ffy=ya;
        double fffy=sqrt(f*f+4*4); if (fffy>ya) fffy=ya;

        yfilt[0][f]=256*(1+cos(M_PI*fy/ya))/d;
        yfilt[1][f]=0.3*256*(1+cos(M_PI*ffy/ya))/d; // only used for NTSC, NB making the 0.3 closer to a half would increase sharpness, but at the cost of more residual luma patterning
        yfilt[2][f]=0.2*256*(1+cos(M_PI*fffy/ya))/d;  // only used for PAL NB 0.2 makes much less sensitive to adjacent lines and reduces castellations and residual dot patterning
        yfilt[3][f]=0;
        if (videoParameters.isSourcePal) yfilt[1][f]=0; else yfilt[2][f]=0;
        ydiv+=yfilt[0][f]+2*yfilt[1][f]+2*yfilt[2][f]+2*yfilt[3][f];
    }
    cdiv*=2; ydiv*=2;
}

// Performs a decode of the 16-bit greyscale input frame and produces a RGB 16-16-16-bit output frame
//
// Note: This method does not clear the output array before writing to it; if there is garbage
// in the allocated memory, it will be in the output with the decoded image on top.
QByteArray PalColour::performDecode(QByteArray firstFieldData, QByteArray secondFieldData, qint32 brightness, qint32 saturation)
{
    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    QByteArray outputFrame;
    outputFrame.resize(videoParameters.fieldWidth * frameHeight * 6);

    double scaledBrightness = 1.75 * brightness / 100.0;
    // NB 1.75 is nominal scaling factor for full-range digitised composite (with sync at code 0 or 1,
    // blanking at code 64 (40h), and peak white at code 211 (d3h) to give 0-255 RGB.

    if (!firstFieldData.isNull() && !secondFieldData.isNull()) {
        // Step 2:
        uint8_t *buffer, *b1, *b2, *b3, *b4, *b5, *b6, Y[MAX_WIDTH];

        // were all short ints
        double pu[MAX_WIDTH], qu[MAX_WIDTH], pv[MAX_WIDTH], qv[MAX_WIDTH], py[MAX_WIDTH], qy[MAX_WIDTH];
        double m[MAX_WIDTH], n[MAX_WIDTH];
        double m1[MAX_WIDTH], n1[MAX_WIDTH], m2[MAX_WIDTH], n2[MAX_WIDTH];
        double m3[MAX_WIDTH], n3[MAX_WIDTH], m4[MAX_WIDTH], n4[MAX_WIDTH];
        double m5[MAX_WIDTH], n5[MAX_WIDTH], m6[MAX_WIDTH], n6[MAX_WIDTH];

        qint32 Vsw; // this will represent the PAL Vswitch state later on...

        // Since we're not using Image objects, we need a pointer to the image data
        uint8_t *topFieldDataPointer = reinterpret_cast<uint8_t*>(secondFieldData.data());
        uint8_t *bottomFieldDataPointer = reinterpret_cast<uint8_t*>(firstFieldData.data());

        for (qint32 field = 0; field < 2; field++) {
            for (qint32 fieldLine = 3; fieldLine < (videoParameters.fieldHeight - 3); fieldLine++) {
                if (field == 0) {
                    buffer = topFieldDataPointer + (fieldLine * (videoParameters.fieldWidth * 2)); // Current scan-line
                    b1 = topFieldDataPointer + ((fieldLine - 1) * (videoParameters.fieldWidth * 2)); // Current scan-line minus 1
                    b2 = topFieldDataPointer + ((fieldLine + 1) * (videoParameters.fieldWidth * 2)); // Current scan-line plus 1
                    b3 = topFieldDataPointer + ((fieldLine - 2) * (videoParameters.fieldWidth * 2)); // Current scan-line minus 2
                    b4 = topFieldDataPointer + ((fieldLine + 2) * (videoParameters.fieldWidth * 2)); // Current scan-line plus 2
                    b5 = topFieldDataPointer + ((fieldLine - 3) * (videoParameters.fieldWidth * 2)); // Current scan-line minus 3
                    b6 = topFieldDataPointer + ((fieldLine + 3) * (videoParameters.fieldWidth * 2)); // Current scan-line plus 3
                } else {
                    buffer = bottomFieldDataPointer + (fieldLine * (videoParameters.fieldWidth * 2)); // Current scan-line
                    b1 = bottomFieldDataPointer + ((fieldLine - 1) * (videoParameters.fieldWidth * 2)); // Current scan-line minus 1
                    b2 = bottomFieldDataPointer + ((fieldLine + 1) * (videoParameters.fieldWidth * 2)); // Current scan-line plus 1
                    b3 = bottomFieldDataPointer + ((fieldLine - 2) * (videoParameters.fieldWidth * 2)); // Current scan-line minus 2
                    b4 = bottomFieldDataPointer + ((fieldLine + 2) * (videoParameters.fieldWidth * 2)); // Current scan-line plus 2
                    b5 = bottomFieldDataPointer + ((fieldLine - 3) * (videoParameters.fieldWidth * 2)); // Current scan-line minus 3
                    b6 = bottomFieldDataPointer + ((fieldLine + 3) * (videoParameters.fieldWidth * 2)); // Current scan-line plus 3
                }

                for (qint32 i = 0; i < videoParameters.fieldWidth; i++) {
                    qint32 sf = (i * 2) + 1; // Simon: Take MSB from source image 16-bit value as 8-bit input (not portable at all)

                    m[i]=buffer[sf]*sine[i]; n[i]=buffer[sf]*cosine[i];

                    m1[i]=b1[sf]*sine[i];  n1[i]=b1[sf]*cosine[i];
                    m2[i]=b2[sf]*sine[i];  n2[i]=b2[sf]*cosine[i];
                    m3[i]=b3[sf]*sine[i];  n3[i]=b3[sf]*cosine[i];
                    m4[i]=b4[sf]*sine[i];  n4[i]=b4[sf]*cosine[i];
                    m5[i]=b5[sf]*sine[i];  n5[i]=b5[sf]*cosine[i];
                    m6[i]=b6[sf]*sine[i];  n6[i]=b6[sf]*cosine[i];
                }

                // Find absolute burst phase

                //  To avoid hue-shifts on alternate lines, the phase is determined by averaging the phase on the current-line with the average of
                //  two other lines, one above and one below the current line.
                //   For NTSC we use the scan-lines immediately above and below (in the field), which we know have exactly 180 degrees burst phase shift to the present line
                //   For PAL we use the next-but-one line above and below (in the field), which will have the same V-switch phase as the current-line (and 180 degree change of phase)
                //    but for PAL we also analyse the average (bpo,bqo 'old') of the line immediately above and below, which have the opposite V-switch phase (and a 90 degree subcarrier phase shift)

                // this is a classic "product-" or "synchronous demodulation" operation. We "detect" the burst relative to the arbitrary sine[] and cosine[] reference phases
                qint32 bp=0, bq=0, bpo=0, bqo=0;
                if (videoParameters.isSourcePal)
                    for (qint32 i=videoParameters.colourBurstStart; i<videoParameters.colourBurstEnd; i++) { bp+=(m[i]-(m3[i]+m4[i])/2)/2; bq+=(n[i]-(n3[i]+n4[i])/2)/2; bpo+=(m2[i]-m1[i])/2; bqo+=(n2[i]-n1[i])/2; }
                else // if NTSC
                    for (qint32 i=videoParameters.colourBurstStart; i<videoParameters.colourBurstEnd; i++) { bp+=(m[i]-(m1[i]+m2[i])/2)/2; bq+=(n[i]-(n1[i]+n2[i])/2)/2; }

                bp/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart);  bq/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart);  // normalises those sums
                bpo/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart); bqo/=(videoParameters.colourBurstEnd-videoParameters.colourBurstStart); // normalises those sums

                // Generate V-switch phase - I forget exactly why this works, but it's essentially comparing the vector magnitude /difference/ between the
                // phases of the burst on the present line and previous line to the magnitude of the burst. This may effectively be a dot-product operation...
                if (((bp-bpo)*(bp-bpo)+(bq-bqo)*(bq-bqo))<(bp*bp+bq*bq)*2) Vsw=1; else Vsw=-1;
                if (!videoParameters.isSourcePal) Vsw=1; // for NTSC there is no V-switch

                // NB bp and bq will be of the order of 1000. CHECK!!
                if (videoParameters.isSourcePal) {
                    bp=(bp-bqo)/2;
                    bq=(bq+bpo)/2;
                }
                // ave the phase of burst from two lines to get -U (reference) phase out (burst phase is (-U +/-V)
                // if NTSC then leave bp as-is, we take bp,bq as the underlying -U (reference) phase.

                //qint32 norm=sqrt(bp*bp+bq*bq)*refAmpl*16; // 16 empirical scaling factor
                double norm=sqrt(bp*bp+bq*bq); // TRIAL - 7 Oct 2005

                if (norm<130000) norm=130000;   // kill colour if burst too weak!  magic number 130000 !!! check!

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
                    if (videoParameters.isSourcePal)
                    {
                        for (qint32 b = 0; b <= arraySize; b++)
                        {
                            l=i-b; r=i+b;

                            PU+=(m[r]+m[l])*cfilt[0][b]+(+n1[r]+n1[l]-n2[l]-n2[r])*cfilt[1][b]-(m3[l]+m3[r]+m4[l]+m4[r])*cfilt[2][b]+(-n5[r]-n5[l]+n6[l]+n6[r])*cfilt[3][b];
                            QU+=(n[r]+n[l])*cfilt[0][b]+(-m1[r]-m1[l]+m2[l]+m2[r])*cfilt[1][b]-(n3[l]+n3[r]+n4[l]+n4[r])*cfilt[2][b]+(+m5[r]+m5[l]-m6[l]-m6[r])*cfilt[3][b];
                            PV+=(m[r]+m[l])*cfilt[0][b]+(-n1[r]-n1[l]+n2[l]+n2[r])*cfilt[1][b]-(m3[l]+m3[r]+m4[l]+m4[r])*cfilt[2][b]+(+n5[r]+n5[l]-n6[l]-n6[r])*cfilt[3][b];
                            QV+=(n[r]+n[l])*cfilt[0][b]+(+m1[r]+m1[l]-m2[l]-m2[r])*cfilt[1][b]-(n3[l]+n3[r]+n4[l]+n4[r])*cfilt[2][b]+(-m5[r]-m5[l]+m6[l]+m6[r])*cfilt[3][b];

                            PY+=(m[r]+m[l])*yfilt[0][b]-(m3[l]+m3[r]+m4[l]+m4[r])*yfilt[2][b];  // note omission of yfilt[1] and [3] for PAL
                            QY+=(n[r]+n[l])*yfilt[0][b]-(n3[l]+n3[r]+n4[l]+n4[r])*yfilt[2][b];  // note omission of yfilt[1] and [3] for PAL
                        }
                        pu[i]=PU/cdiv; qu[i]=QU/cdiv;
                        pv[i]=PV/cdiv; qv[i]=QV/cdiv;
                        py[i]=PY/ydiv; qy[i]=QY/ydiv;
                    } else // if NTSC
                    {
                        for (qint32 b = 0; b <= arraySize; b++)
                        {
                            l=i-b; r=i+b;

                            PU+=(m[r]+m[l])*cfilt[0][b]-(+m1[r]+m1[l]+m2[l]+m2[r])*cfilt[1][b]+(m3[l]+m3[r]+m4[l]+m4[r])*cfilt[2][b]-(m5[r]+m5[l]+m6[l]+m6[r])*cfilt[3][b];
                            QU+=(n[r]+n[l])*cfilt[0][b]-(+n1[r]+n1[l]+n2[l]+n2[r])*cfilt[1][b]+(n3[l]+n3[r]+n4[l]+n4[r])*cfilt[2][b]-(n5[r]+n5[l]+n6[l]+n6[r])*cfilt[3][b];
                            PV+=(m[r]+m[l])*cfilt[0][b]-(+m1[r]+m1[l]+m2[l]+m2[r])*cfilt[1][b]+(m3[l]+m3[r]+m4[l]+m4[r])*cfilt[2][b]-(m5[r]+m5[l]+m6[l]+m6[r])*cfilt[3][b];
                            QV+=(n[r]+n[l])*cfilt[0][b]-(+n1[r]+n1[l]+n2[l]+n2[r])*cfilt[1][b]+(n3[l]+n3[r]+n4[l]+n4[r])*cfilt[2][b]-(n5[r]+n5[l]+n6[l]+n6[r])*cfilt[3][b];

                            // PY+=(m[r]+m[l])*yfilt[0][b]+(m3[l]+m3[r]+m4[l]+m4[r])*yfilt[2][b];  // blurrier for NTSC as luma is in same "phase" as chroma for next-but-one lines
                            // QY+=(n[r]+n[l])*yfilt[0][b]+(n3[l]+n3[r]+n4[l]+n4[r])*yfilt[2][b];  // blurrier for NTSC as luma is in same "phase" as chroma for next-but-one lines
                            PY+=(m[r]+m[l])*yfilt[0][b]-(m1[l]+m1[r]+m2[l]+m2[r])*yfilt[1][b];  // for NTSC sharper as luma/chroma out of phase for adjacent lines
                            QY+=(n[r]+n[l])*yfilt[0][b]-(n1[l]+n1[r]+n2[l]+n2[r])*yfilt[1][b];  // for NTSC sharper as luma/chroma out of phase for adjacent lines

                        }
                        pu[i]=PU/cdiv; qu[i]=QU/cdiv;
                        pv[i]=PV/cdiv; qv[i]=QV/cdiv;
                        py[i]=PY/ydiv; qy[i]=QY/ydiv;
                    }
                }

                // Obtain the black level from the "back porch"
                // we average over the present line, and two lines above and below to get a good average and avoid "banding"
                // Bkstart and Bkend define the zone of the back-porch, used for blacklevel reference
                qint32 blacklevel=0;
                for (qint32 i = videoParameters.blackLevelStart; i < videoParameters.blackLevelEnd; i++) {
                    qint32 sf = (i * 2) + 1; // Simon: Take MSB from source image 16-bit value as 8-bit input (not portable at all)
                    blacklevel+=buffer[sf]+b1[sf]+b2[sf]+b3[sf]+b4[sf];
                }
                if (!videoParameters.isSourcePal) blacklevel*=(47.5/40); // NTSC fix for pedestal / set-up!
                blacklevel/=(videoParameters.blackLevelEnd-videoParameters.blackLevelStart)*5;

                qint32 normalise=refAmpl*refAmpl/2;     // refAmpl is the integer sinewave amplitude

                // Generate the luminance (Y), by filtering out Fsc (by re-synthesising the detected py qy and subtracting), and subtracting the black-level
                for (qint32 i=videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++) {
                    qint32 sf = (i * 2) + 1; // Simon: Take MSB from source image 16-bit value as 8-bit input (not portable at all)

                    qint32 tmp = static_cast<qint32>(buffer[sf]-(py[i]*sine[i]+qy[i]*cosine[i])/normalise -blacklevel);
                    if (tmp<0) tmp=0;
                    if (tmp>255) tmp=255;
                    Y[i]=static_cast<uint8_t>(tmp);
                }

                // Define scan line pointer to output buffer
                uint8_t *ptr = reinterpret_cast<uint8_t*>(outputFrame.data() + (((fieldLine * 2) + field) * videoParameters.fieldWidth * 6));

                // 'saturation' is a user saturation control, nom. 100%
                double scaledSaturation = (saturation / 100.0) / (norm / 2.0);  // 'norm' normalises bp and bq to 1
                // the '2' is arbitrary until I can work out a physical reason for it!
                for (qint32 i = videoParameters.activeVideoStart; i < videoParameters.activeVideoEnd; i++)
                {
                    qint32 R, G, B;
                    double U, V;

                    // the next two lines "rotate" the p&q components (at the arbitrary sine/cosine reference phase) backwards by the
                    // burst phase (relative to the arb phase), in order to recover U and V. The Vswitch is applied to flip the V-phase on alternate lines for PAL
                    U=-((pu[i]*bp+qu[i]*bq)) *scaledSaturation;
                    V=-(Vsw*(qv[i]*bp-pv[i]*bq)) *scaledSaturation;

                    // These magic numbers below come from the PAL matrices (I ought to have a reference for these. Tancock and/or Rec.470, I expect)
                    // Simon: Scaled output RGB to 16-bit values
                    R=static_cast<qint32>(scaledBrightness*(Y[i]+1.14*V) * 256);          if (R<0) R=0; if (R>65535) R=65535;
                    G=static_cast<qint32>(scaledBrightness*(Y[i]-0.581*V-0.394*U) * 256); if (G<0) G=0; if (G>65535) G=65535;  // coefficients corrected 10 Sept 2004
                    B=static_cast<qint32>(scaledBrightness*(Y[i]+2.03*U) * 256);          if (B<0) B=0; if (B>65535) B=65535;
                    // note however that since U and V have been scaled (relative to the burst), they *should* be "absolute"... (indep of HF gain or overall capture levels)
                    //  ... if "bright" is used to compensate for capture-levels, then the saturation seems to go amiss.
                    //  ... possibly "bright" should only multiply Y[i] and not also U and V - or maybe "norm" isn't working as it's supposed to?
                    //  Needs some detailed analysis!

                    // Pack the data back into the RGB 16/16/16 buffer
                    qint32 pp = i * 6;
                    ptr[pp+0] = static_cast<uint8_t>((R & 0x00FF));        // Red LSB
                    ptr[pp+1] = static_cast<uint8_t>((R & 0xFF00) >> 8);   // Red MSB
                    ptr[pp+2] = static_cast<uint8_t>((G & 0x00FF));        // Green LSB
                    ptr[pp+3] = static_cast<uint8_t>((G & 0xFF00) >> 8);   // Green MSB
                    ptr[pp+4] = static_cast<uint8_t>((B & 0x00FF));        // Blue LSB
                    ptr[pp+5] = static_cast<uint8_t>((B & 0xFF00) >> 8);   // Blue MSB
                }
            }
        }
    }

    return outputFrame;
}
