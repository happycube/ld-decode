#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <unistd.h>
#include <sys/fcntl.h>
#include <fftw3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <vector>

//#define CHZ 35795453.0 
//#define CHZ (28636363.0*5.0/4.0)

const double FSC=(1000000.0*(315.0/88.0))*1.00;
const double CHZ=(1000000.0*(315.0/88.0))*8.0;

using namespace std;

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

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
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

	dftc(buf, offset, len, bin, fc, fci);

	return ctor(fc, fci);
}

double phase = 0.0;

int cb_analysis(double *data, int begin, int end, double &peaklevel, double &peakphase)
{
//	double fc = 0.0, fci = 0.0;
	double freq = 4.0;

	// peaklevel = 0.0;

	for (int i = begin + 16; i < end - 16; i++) {	
		double fc = 0.0, fci = 0.0;
		for (int j = -16; j < 16; j++) {
			double o = (double)(data[i + j]); 

			fc += (o * cos((1.0 * M_PIl * ((double)(i + j) / freq)))); 
			fci -= (o * sin((1.0 * M_PIl * ((double)(i + j) / freq)))); 
		}
		double level = ctor(fc, fci) / 33.0;
		phase = atan2(fc, -fci);
		if (level > peaklevel) {
			peaklevel = level;
			peakphase = phase;
			//cerr << 'x' << i << ' ' << fc <<' ' << fci << ' ' << peakphase << endl;
		}
		//cerr << i << ' ' << ctor(fc, fci) / 33 << ',' << fc << ' ' << fci << ' ' << phase << ' ' << peaklevel << endl;
	}
//	cerr << i << ' ' << state << ' ' << (int)data[i] << ':' << ire << ' ' << ' ' << fc << ',' << fci << " : " << ctor(fc, fci) / N << ',' << atan2(fci, ctor(fci, fc)) << ',' << phase << endl; 
//		if (fc < 0) phase += (M_PIl / 2.0); 
//		if (ctor(fc, fci)) phase += (atan2(fci, ctor(fc, fci)));

	//cerr << 'P' << phase;
	if (fabs(phase) < (M_PIl * .6)) {
		phase = fabs(phase);
	} else {
		phase = M_PIl - fabs(phase);
	}
	phase *= (M_PIl / 4.0);
	//cerr << ' ' << phase << endl;
	//peakfreq = freq;
	peakphase = phase;

	return 0;
}

double *curframe;

int curline = -1;

double *curdata;
int clen = 0;

const int BUFSIZE = (8 * 1024 * 1024);

// XXX:  side effect	
int sl;
bool halfsync;	

int findsync(double *curdata, int len)
{
	int begsync = -1, endsync = -1;
	int possync = -1, nscount = -1;
	bool havesync = false;

	for (int i = 0; i < len && begsync == -1; i++) {
//		if (curdata[i] < 0.2) cerr << i << ' ' << curdata[i] << endl;

		if (curdata[i] < 0.05) {
			//cerr << i << ' ' << curdata[i] << endl;
			if (possync < 0) {
				possync = i;
			} 
		} else if ((curdata[i] > 0.10) && (possync >= 0)) {
			if ((nscount++) > 8) {
				if ((i - 8) > (possync + 50)) {
					begsync = possync; 
					endsync = i - 8;
					
					sl = endsync - begsync;

					cerr << 'S' <<  begsync << ' ' << endsync - begsync << endl;		
				} 
				possync = -1;
			}
		}
	} 

	if (begsync == -1) {
		cerr << "nosync\n";
		return -1;
	}

	// scan for half-line sync
	halfsync = false; possync = -1; nscount = 0;
	for (int i = begsync + 900; i < (begsync + 1000) && !halfsync; i++) {
		if (curdata[i] < 0.05) {
			//cerr << i << ' ' << curdata[i] << endl;
			if (possync < 0) {
				possync = i;
			} 
		} else if ((curdata[i] > 0.10) && (possync >= 0)) {
			if ((nscount++) > 8) {
				if ((i - 8) >= (possync + 40)) {
					endsync = i - 8;
					halfsync = true;
					cerr << 'H' <<  begsync + 900 << ' ' << endsync - (begsync + 900) << endl;		
				} 
			}
		} 
	} 

	return begsync;
}

int main(int argc, char *argv[])
{
	int i, rv;
	double buf[8192];

	curdata = new double[BUFSIZE];
	curframe = new double[1820 * 530];

	int begline = -1, endline = -1;
	int begsync = -1, endsync = -1;

	bool havesync = false;

	double phase;
	double level = 0.0;

	double tshift = 0.0;

	int rlen = 8192;

	int prevsync = -1;

	int vsync = 0, line = 0, field = -1, nextfield = -1;
	int tfields = 0;
		
	unsigned short frame[910 * 525];
	memset(frame, 0, sizeof(frame));

	// XXX:  will fail horribly if read length isn't an even # of doubles
	while ((rv = read(0, &buf, rlen * sizeof(double))) > 0) {
		double preout;	
		int nr = rv / sizeof(double);

		memcpy(&curdata[clen], buf, rv); 
		clen += rv / sizeof(double);

		//cerr << clen << endl;

		int slen = (clen > 400) ? 400 : clen;
		int begsync = findsync(curdata, slen);
		cerr << 's' << begsync <<  ' ' << prevsync << ' ' << sl << endl;

		if (begsync < -1) begsync = prevsync;
		prevsync = begsync;

//		for (int x = 0; x < 256; x++) {
//			cerr << x << ' ' << (140.0 * curdata[x + begsync]) - 40.0 << endl;
//		}
	
		if ((clen - begsync) > 200) {
			level = 0.0;
			cb_analysis(&curdata[begsync], 150, 220, level, phase);
			cerr << "level " << level << " phase " << phase << endl; 
		}

		unsigned short frame[910 * 525];

		int newbeg = 0;
//		begsync = 0;	
		if (clen > 3880) {
			newbeg = begsync + 1700;

			double outbuf[2048];
			memset(outbuf, 0, sizeof(outbuf));

			//double cur = phase, scale = 0.50;	
			double cur = phase, scale = 0.50;	

			if ((sl > 120) && (sl < 140)) {
				line+=2;

				if (vsync > 1) {
					cerr << "V" << vsync << endl;
					vsync = 0;

					field = nextfield; nextfield = !field;
					line = field;

					if (!field && (tfields > 2)) {
						write(1, frame, (910 * 480) * 2);
					}
					tfields++;
				}

				if (halfsync == true) {
					cerr << "SYNC" << line << endl;
					if (line > 200) {
						nextfield = 1;
					}
				}
	
				for (int i = begsync; (field >= 0) && cur < 910/* && i < begsync + 1820 */; i++) {
					if (floor(cur + scale) > floor(cur)) {
						double a = (cur + scale) - floor(cur + scale);
	
						if (cur > 0) outbuf[(int)floor(cur)] += (scale - a) * curdata[i];  
						outbuf[(int)floor(cur)] = curdata[i];
//						cerr << i << ' ' << cur << ' ' << a << ' ' << outbuf[(int)floor(cur)] << ' ' << curdata[i] << endl;
						cur += scale;
						if (cur > 0) outbuf[(int)floor(cur)] = a * curdata[i];  
					} else {
						if (cur > 0) outbuf[(int)floor(cur)] += scale * curdata[i];  
						cur += scale;
					}
				}	
		
				//for (int i = 0; i < (int)floor(cur); i++) {
				for (int i = 0; line > 24 && i < 910; i++) {
					//double preout = (curdata[(i * 2) + begsync] + curdata[(i * 2) + begsync + 1]) / 2;
					double preout = outbuf[i];
#if 0
					preout = (preout * 800) + 4;
					if (preout < 16) preout = 16;
					if (preout > 1019) preout = 1019;
#else
					preout = (preout * 65536);
					if (preout < 0) preout = 0;
					if (preout > 65535) preout = 65535;
#endif
					frame[i + ((line - 24) * 910)] = preout;
				} 
			} else {
				vsync++; 
			}
	
			//cerr << 'C' << cur <<' ' << newbeg << endl;
	
			memmove(curdata, &curdata[newbeg], (clen - newbeg) * sizeof(double));
			clen -= newbeg;

			rlen = 8192 - clen;
			cerr << 'r' << rlen << ' ' << clen << ' ' << newbeg << endl;
		}
	}	
	
	return 0;
}
 
