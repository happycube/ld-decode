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

class Filter {
	protected:
		int order;
		bool isIIR;
		vector<double> a, b;
		vector<double> y, x;
	public:
		Filter(int _order, const double *_a, const double *_b) {
			order = _order + 1;
			if (_a) {
				a.insert(b.begin(), _a, _a + order);
				isIIR = true;
			} else {
				a.push_back(1.0);
				isIIR = false;
			}
			b.insert(b.begin(), _b, _b + order);
			x.resize(order);
			y.resize(order);
	
			clear();
		}
		
		Filter(vector<double> _b, vector<double> _a) {
			b = _b;
			a = _a;

			order = b.size();
			
			x.resize(b.size() + 1);
			y.resize(a.size() + 1);

//			for (int i = 0; i < b.size(); i++) cerr << b[i] << endl;;
//			for (int i = 0; i < b.size(); i++) cerr << a[i] << endl;;
	
			clear();

			isIIR = true;
		}

		Filter(Filter *orig) {
			order = orig->order;
			isIIR = orig->isIIR;
			a = orig->a;
			b = orig->b;
			x.resize(b.size());
			y.resize(a.size());
				
			clear();
		}

		void clear(double val = 0) {
			for (int i = 0; i < a.size(); i++) {
				y[i] = val;
			}
			for (int i = 0; i < b.size(); i++) {
				x[i] = val;
			}
		}

		void dump() {
//			for (int i = 0 ; i < order; i++) cerr << x[i] << ' ' << b[i] << endl;
			cerr << (const void *)a.data() << ' ' << a[0] << endl;
		}

		inline double feed(double val) {
			double a0 = a[0];
			double y0;

			double *x_data = x.data();
			double *y_data = y.data();

			memmove(&x_data[1], x_data, sizeof(double) * (b.size() - 1)); 
			if (isIIR) memmove(&y_data[1], y_data, sizeof(double) * (a.size() - 1)); 

			x[0] = val;
			y0 = 0; // ((b[0] / a0) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			if (isIIR) {
				for (int o = 0; o < b.size(); o++) {
					y0 += ((b[o] / a0) * x[o]);
				}
				for (int o = 1; o < a.size(); o++) {
					y0 -= ((a[o] / a0) * y[o]);
				}
//				for (int i = 0 ; i < b.size(); i++) cerr << 'b' << i << ' ' << b[i] << ' ' << x[i] << endl;
//				for (int i = 0 ; i < a.size(); i++) cerr << 'a' << i << ' ' << a[i] << ' ' << y[i] << endl;
			} else {
				if (order == 13) {
					double t[4];
		
					// Cycling through destinations reduces pipeline stalls.	
					t[0] = b[0] * x[0];
					t[1] = b[1] * x[1];
					t[2] = b[2] * x[2];
					t[3] = b[3] * x[3];
					t[0] += b[4] * x[4];
					t[1] += b[5] * x[5];
					t[2] += b[6] * x[6];
					t[3] += b[7] * x[7];
					t[0] += b[8] * x[8];
					t[1] += b[9] * x[9];
					t[2] += b[10] * x[10];
					t[3] += b[11] * x[11];
					y0 = t[0] + t[1] + t[2] + t[3] + (b[12] * x[12]);
				} else for (int o = 0; o < order; o++) {
					y0 += b[o] * x[o];
				}
			}

			y[0] = y0;
			return y[0];
		}
		double val() {return y[0];}
};
		
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
#define FRAME_INFO_CAV_ODD	0x2
#define FRAME_INFO_CX		0x4

#define FRAME_INFO_WHITE_ODD	0x100
#define FRAME_INFO_WHITE_EVEN	0x200

#endif
