#ifndef LD_DECODER_H
#define LD_DECODER_H

#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <vector>
#include <list>
#include <queue>
#include <complex>
#include <unistd.h>
#include <sys/fcntl.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// capture frequency and fundamental NTSC color frequency
//const double CHZ = (1000000.0*(315.0/88.0)*8.0);

using namespace std;

//for macOS
#ifndef M_PIl
#define M_PIl M_PI
#endif
// From http://lists.apple.com/archives/perfoptimization-dev/2005/Jan/msg00051.html. 
const double PI_FLOAT = M_PIl;
const double PIBY2_FLOAT = (M_PIl/2.0); 
// |error| < 0.005
inline double fast_atan2( double y, double x )
{
	if ( x == 0.0f )
	{
		if ( y > 0.0f ) return PIBY2_FLOAT;
		if ( y == 0.0f ) return 0.0f;
		return -PIBY2_FLOAT;
	}
	double atan;
	double z = y/x;
	if (  fabs( z ) < 1.0f  )
	{
		atan = z/(1.0f + 0.28f*z*z);
		if ( x < 0.0f )
		{
			if ( y < 0.0f ) return atan - PI_FLOAT;
			return atan + PI_FLOAT;
		}
	}
	else
	{
		atan = PIBY2_FLOAT - z/(z*z + 0.28f);
		if ( y < 0.0f ) return atan - PI_FLOAT;
	}
	return atan;
}

inline double WrapAngle(double v) {
        if (v > M_PIl) v -= (2 * M_PIl);
        else if (v <= -M_PIl) v += (2 * M_PIl);

        return v;
}

inline double absWrapAngle(double v) {
	return fabs(WrapAngle(v));
}

inline double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
}

inline double atan2deg(double y, double x)
{
	double rv = (atan2(y, x) * (180 / M_PIl));
	if (rv < 0) rv += 360;
	return rv;
}

inline double dftc(double *buf, int offset, int len, double bin, double &fc, double &fci) 
{
	fc = 0.0; fci = 0.0;

	for (int k = (-len + 1); k < len; k++) {
//		cout << offset + k << ' ' << len << endl;
		double o = buf[offset + k]; 
		
		fc += (o * cos((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
		fci -= (o * sin((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
	}

	return ctor(fc, fci);
}

inline double dft(double *buf, int offset, int len, double bin) 
{
	double fc, fci;

	return dftc(buf, offset, len, bin, fc, fci);
}

// taken from http://www.paulinternet.nl/?page=bicubic
double CubicInterpolate(double *y, double x)
{
	double p[4];
	p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

	return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
}

/*
	TBC line 0 format (presumably shared for PAL/NTSC):

	All data in uint32_t, using pairs of 16-bit words in the line.

	words 0-5: decoded VBI data

	word 6:
		bit 0: CAV/CLV
		bit 1: Frame begins on odd field (CAV only)
		bit 2: CX enable/disable
		bit 8: white flag on odd frame
		bit 9: white flag on even frame
		bits 16-31: chapter #

	word 7:  Frame # (CAV *and* CLV)
		CLV:  ((Hour * 3600) + (Minute * 60) + Second) * FPS) + frame #	
*/

#define FRAME_INFO_CLV		0x1
#define FRAME_INFO_CAV_EVEN	0x4
#define FRAME_INFO_CAV_ODD	0x8
#define FRAME_INFO_CX		0x10

#define FRAME_INFO_WHITE_ODD	0x100
#define FRAME_INFO_WHITE_EVEN	0x200

#endif
