#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <unistd.h>
#include <sys/fcntl.h>
#include <fftw3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

//#define CHZ 35795453.0 
//#define CHZ (28636363.0*5.0/4.0)

const double FSC=(1000000.0*(315.0/88.0))*1.00;
const double CHZ=(1000000.0*(315.0/88.0))*4.0;

using namespace std;

double _ctor(fftw_complex c)
{
	return sqrt((c[0] * c[0]) + (c[1] * c[1]));
}

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
}

double clamp(double v, double low, double high)
{
	if (v < low) return low;
	else if (v > high) return high;	
	else return v;
}

class LowPass {
	protected:
		bool first;
	public:
		double alpha;
		double val;
		
		LowPass(double _alpha = 0.15) {
			alpha = _alpha;	
			first = true;
		}	

		double feed(double _val) {
			if (first) {
				first = false;
				val = _val;
			} else {
				val = (alpha * val) + ((1 - alpha) * _val);	
			}
			return val;
		}
};

/* Linear difference equation - used for running filters (compute with Octave, etc) */

class LDE {
	protected:
		int order;
		const double *a, *b;
		double *y, *x;
	public:
		LDE(int _order, const double *_a, const double *_b) {
			order = _order + 1;
			a = _a;
			b = _b;
			x = new double[order];
			y = new double[order];
	
			clear();
		}

		~LDE() {
			delete [] x;
			delete [] y;
		}

		void clear(double val = 0) {
			for (int i = 0; i < order; i++) {
				x[i] = y[i] = val;
			}
		}

		double feed(double val) {
			for (int i = order - 1; i >= 1; i--) {
				x[i] = x[i - 1];
				y[i] = y[i - 1];
			}
		
			x[0] = val;
			y[0] = ((b[0] / a[0]) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			for (int o = 1; o < order; o++) {
				y[0] += ((b[o] / a[0]) * x[o]);
				y[0] -= ((a[o] / a[0]) * y[o]);
				//cerr << o << ' ' << x[o] << ' ' << y[o] << ' ' << a[o] << ' ' << b[o] << ' ' << (b[o] * x[o]) << ' ' << -(a[o] * y[o]) << ' ' << y[0] << endl;
			}

			return y[0];
		}
		double val() {return y[0];}
};

const double f_1_3mhz_b[] {-3.2298296184665740e-03, -3.9763697027928036e-03, -3.0488187471881391e-03, 7.1571555933253586e-03, 3.3887137420533418e-02, 7.7579717689882186e-02, 1.2857649823595613e-01, 1.7003884825042573e-01, 1.8603132175664944e-01, 1.7003884825042576e-01, 1.2857649823595613e-01, 7.7579717689882199e-02, 3.3887137420533425e-02, 7.1571555933253577e-03, -3.0488187471881404e-03, -3.9763697027928062e-03, -3.2298296184665740e-03  };
const double f_1_3mhz_a[16] {1, 0}; 

const double f_2_0mhz_b[] { 2.0725950133615822e-03, -8.3463967955793583e-04, -9.7490566449315967e-03, -2.1735983355962385e-02, -1.4929346936560809e-02, 3.7413352363703849e-02, 1.3482681278026168e-01, 2.3446159984589487e-01, 2.7694933322758158e-01, 2.3446159984589490e-01, 1.3482681278026165e-01, 3.7413352363703870e-02, -1.4929346936560811e-02, -2.1735983355962385e-02, -9.7490566449315984e-03, -8.3463967955793670e-04, 2.0725950133615822e-03 }; 
const double f_2_0mhz_a[16] {1, 0}; 

unsigned short rdata[1024*1024*32];
double data[1024*1024*32];
int dlen;

#define STATE_LINE 0
#define STATE_SYNC 1
#define STATE_PORCH 2
#define STATE_CB   3
#define STATE_PORCH2 4
#define STATE_PORCH3 5

int state = STATE_LINE;

int find_sync(int start, int &begin, int &len)
{
	int i, sc = 0;
	begin = len = 0;

	for (i = start; i < dlen; i++) {
		if (!begin) {
			if (data[i] < -20.0) {
				sc++;
				if (sc > 32) {
					begin = i - 32;
				}
			}
		} else if (data[i] > -15.0) {
			len = sc;

			return 0;
		} else sc++;
	}

	return -1;
}

double phase = 0.0;

int cb_analysis(int begin, int end, double &peaklevel, double &peakphase)
{
//	double fc = 0.0, fci = 0.0;
	double freq = 4.0;

	// peaklevel = 0.0;

	for (int i = begin + 16; i < end; i++) {	
		double fc = 0.0, fci = 0.0;
		for (int j = -16; j < 16; j++) {
			double o = (double)(data[i + j]); 

			fc += (o * cos(phase + (2.0 * M_PIl * ((double)(i + j) / freq)))); 
			fci -= (o * sin(phase + (2.0 * M_PIl * ((double)(i + j) / freq)))); 
		}
		double level = ctor(fc, fci) / 33.0;
		if (level > 0.6) phase -= (atan2(fci, ctor(fc, fci)));
		if (level > peaklevel) peaklevel = level;
		cerr << i << ' ' << ctor(fc, fci) / 33 << ' ' << phase << ' ' << peaklevel << endl;
	}
//	cerr << i << ' ' << state << ' ' << (int)data[i] << ':' << ire << ' ' << ' ' << fc << ',' << fci << " : " << ctor(fc, fci) / N << ',' << atan2(fci, ctor(fci, fc)) << ',' << phase << endl; 
//		if (fc < 0) phase += (M_PIl / 2.0); 
//		if (ctor(fc, fci)) phase += (atan2(fci, ctor(fc, fci)));


	//peakfreq = freq;
	peakphase = phase;

	return 0;
}

int main(int argc, char *argv[])
{
	int i, rv, fd;
	unsigned short avg, rhigh = 0, rlow = 65535;
	unsigned short high = 0, low = 65535;
	long long total = 0;
	int rp;
	double igrad = 0.0;

	fd = open(argv[1], O_RDONLY);
	if (argc >= 3) lseek64(fd, atoll(argv[2]) /* *1024*1024 */, SEEK_SET);

	dlen = sizeof(rdata);
	if (argc >= 4) dlen = atol(argv[3]);
	dlen = read(fd, rdata, dlen);
	dlen /= 2.0;

//	cout << std::setprecision(8);

	rlow = 0;  rhigh = 65535;

//	rlow = 4;  rhigh = 0x3fb;
	
	igrad = (double)(rhigh - rlow) / 140.0;
	double irestep = 140.0 / (double)(rhigh - rlow); 

	for (i = 0; i < dlen; i++) {
//		data[i] = (sin(2 * M_PIl * ((double)i / (CHZ / FSC))) * 10) + 128; 
//		cout << (sin(2 * M_PIl * ((double)i / 4.0)) * 127) + 128 << endl;

//		data[i] = ((rdata[i] - 25) * 956.0 / 223.0) + 16; 

		data[i] = (((double)rdata[i] - rlow) * irestep)  - 40;
//		cerr << (int)rdata[i] << ' ' << data[i] << endl;

		if (data[i] > high) high = data[i];
		if (data[i] < low)  low = data[i];
		total += data[i];
	}

	rhigh = high;
	int begin = 0, len = 0;
	i = 0;
	double burst = 0.0;

	LowPass lpburst(0.5);
//	LowPass lpU(0.9), lpV(0.9);

	LDE lpU(16, f_1_3mhz_a, f_1_3mhz_b);
	LDE lpV(16, f_1_3mhz_a, f_1_3mhz_b);

	while (i < dlen) {
		if (!find_sync(i, begin, len)) {
			int lc = -21;
			unsigned char line[1536 * 3];

			cerr << begin << ' ' << len << endl;
			i = begin + len;

			double freq, phase;

			burst = 0.0;
			// color burst is approx i + 30 to i + 90
			cb_analysis(i + 15, i + 35, burst, phase);
			lpburst.feed(burst);

			cerr << burst << ',' << phase << endl;
			freq = 4.0;

			for (int j = i + 60; j < i + 60 + 768 + 7; j++) {
				double fc = 0, fci = 0;
				double y = data[j];
				double u, v;	
	
				u = lpU.feed(data[j] * cos(phase + (2.0 * M_PIl * ((double)(j) / freq)))); 
				v = lpV.feed(-data[j] * sin(phase + (2.0 * M_PIl * ((double)(j) / freq)))); 
				y = data[j - 6];
				//cerr << lpU.val << ' ' << lpV.val << endl;
#if 0
				if (burst > 0.2) {
//					cerr << j << ' ' << u << ' ' << v << ' ' << y << ' ';
//					cerr << u * cos(phase + (2.0 * M_PIl * (((double)j / freq)))) << ' ' ;
//					cerr << v * cos(phase + (2.0 * M_PIl * (((double)j / freq)))) << ' ' ;
					y += u * (2 * cos(phase + (2.0 * M_PIl * (((double)j / freq)))));
					y -= v * (2 * sin(phase + (2.0 * M_PIl * (((double)j / freq)))));
//					cerr << y << ' ' << endl;
				}
//				y -= (255 * .2);
#endif
				u *= (10 / burst);
				v *= (10 / burst);

				y *= 2.55;
				u *= 2.55;
				v *= 2.55;
				clamp(y, 0, 130);
				clamp(u, -78, 78);
				clamp(v, -78, 78);

/*
B = 1.164(Y - 16)                   + 2.018(U - 128)
G = 1.164(Y - 16) - 0.813(V - 128) - 0.391(U - 128)
R = 1.164(Y - 16) + 1.596(V - 128)
*/

				double r = (y * 1.164) + (1.596 * v); 
				double g = (y * 1.164) - (0.813 * v) - (u * 0.391); 
				double b = (y * 1.164) + (u * 2.018); 

				//cerr << fc << ':' << fci << ' ' << r << endl;				

//				line[lc++] = clamp(y, 0, 255);

				if (lc > 0) {	
					line[lc++] = clamp(r, 0, 255);
					line[lc++] = clamp(g, 0, 255);
					line[lc++] = clamp(b, 0, 255);
				} else lc += 3;
				//cerr << fc << ':' << fci << ' ' << lc << ' ' << (int)line[lc - 2] << endl;				
			
			}
			write(1, line, 768 * 3);
		} else {
			i = dlen;
		}
	};

/*
	NTSC timing, 4fsc:

	0-767:  data
	795-849: hsync
	795-815: equalizing pulse
	
	340-360, 795-260, 340-715: vsync

	8fsc - 

	0-1535: data
	1590-1699: hsync
	1700-1820: ?

	chroma after conversion:
	sync tip = 16
	chroma peak = 104
	chroma burst = 128
	blank (non sync) 0ire = 240
	black 7.5ire = 280
	peak burst = 352
	white = 800
	peak chroma = 972 

*/

	return 0;
}
 
