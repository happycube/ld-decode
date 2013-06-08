/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <unistd.h>
#include <sys/fcntl.h>
#include <fftw3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// capture frequency and fundamental NTSC color frequency
const double CHZ = (1000000.0*(315.0/88.0)*8.0);
const double FSC = (1000000.0*(315.0/88.0));

using namespace std;

// (too) simple lowpass filter
class LowPass {
	protected:
		bool first;
	public:
		double alpha;
		double val;
		
		LowPass(double _alpha = 0.15) {
			alpha = _alpha;	
			first = true;
			val = 0;
		}	
		
		double reset(double _val) {
			val = _val;
			return val;
		}

		double feed(double _val) {
			if (first) {
				first = false;
				val = val;
			} else {
				val = (alpha * val) + ((1 - alpha) * _val);	
			}
			return val;
		}
};

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
}

inline double dft(double *buf, int offset, int len, double bin) 
{
	double fc = 0.0, fci = 0.0;

	for (int k = (-len + 1); k < len; k++) {
//		cout << offset + k << ' ' << len << endl;
		double o = buf[offset + k]; 
		
		fc += (o * cos((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
		fci -= (o * sin((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
	}

	return ctor(fc, fci);
}

void dc_filter(double *out, double *in, int len)
{
	double avg = 0;

	for (int i = 0; i < len; i++) {
		avg += (in[i] / len);
	}
	
	for (int i = 0; i < len; i++) {
		out[i] = in[i] - avg;
	}
}

double peakfreq(double *buf, int offset, int len, double lf, double hf, double step, double basefreq) 
{
	double *buf_mdc = new double[(len * 2) + 1];
	double bin[2048];
	double peak = 0;	
	int fbin = 0, peakbin = 0;
	int f;

	dc_filter(buf_mdc, &buf[offset - len], (len * 2) + 1);
	
	// we include an extra bin on each side so we can do quadratric interp across the whole range 
	lf -= step;
	for (f = lf; f < hf + step + 1; f += step) { 
		//bin[fbin] = dft(&buf[offset - len], len, len, (basefreq / f));
		bin[fbin] = dft(buf_mdc, len, len, (basefreq / f));
//		cerr << f << ' ' << bin[fbin] << endl;
		if (bin[fbin] > peak) {
			peak = bin[fbin];
			peakbin = fbin;
		}
		fbin++;
	}

	double dpi;
	double pf;	
	if ((peakbin >= 1) && (peakbin < (fbin - 1))) {
		double p0 = bin[peakbin - 1];
		double p2 = bin[peakbin + 1];
		
		dpi = (double)peakbin + ((p2 - p0) / (2.0 * ((2.0 * peak) - p0 - p2))); 
		pf = (dpi * step) + lf;	

		if (pf < 0) {
			cerr << "invalid freq " << pf << " peak bin " << (peakbin * step) + lf << endl;
			pf = 0;
		}
	} else {
		// this generally only happens during a long dropout
		cerr << "out of range on sample " <<  offset << " with step " << step << ' ' << peakbin << endl;
		pf = 0;	
	}

	delete [] buf_mdc;

	return pf;
};

void window(double *out, double *in, double *window, int len)
{
	for (int i = 0; i < len; i++) {
		out[i] = in[i] * window[i];
	}
} 

// use only with odd #'s
void make_hamming_window(double *out, int len)
{
	int N = (len - 1) / 2;
	int K = (len / 2);

	double a = 0.54;

	for (int i = 0; i < len; i++) {
		int d = i - K;
		
		if (abs(d) < N) {
			out[i] = a + (1 - a) * cos((d * M_PIl) / N); 
		}
	}
}

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

		void clear() {
			for (int i = 0; i < order; i++) {
				x[i] = y[i] = 0;
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
};

/* 
	[n, Wn] = buttord((3.0/28.636),(4.0/28.636),10,50), [a, b] = butter(16, 0.097924) 

double butter_lp_b[] = {2.3021e-14,  3.6834e-13,  2.7625e-12,  1.2892e-11,  4.1899e-11,  1.0056e-10,  1.8435e-10,  2.6336e-10,  2.9628e-10   2.6336e-10, 1.8435e-10,  1.0056e-10,  4.1899e-11,  1.2892e-11,  2.7625e-12,  3.6834e-13,  2.3021e-14};
double butter_lp_a[] = {1.0000e+00  -1.2862e+01   7.7800e+01  -2.9376e+02   7.7484e+02  -1.5137e+03   2.2653e+03  -2.6490e+03   2.4458e+03  -1.7889e+03 1.0329e+03  -4.6585e+02   1.6087e+02  -4.1117e+01   7.3351e+00  -8.1593e-01   4.2634e-02};
*/

/*
	[n, Wn] = buttord((3.0/28.636),(4.0/28.636),10,50), [a, b] = butter(16, 0.097924) 
	[b, a] = butter(16, 0.097924, 'high')
	printf("%.20f, ", a)
XXX 6/8 now
*/

const double butter_hp_b[] = {0.040642012368838, -0.650272197901411, 4.877041484260581, -22.759526926549377, 73.968462511285480, -177.524310027085136, 325.461235049656068, -464.944621499508685, 523.062699186947270, -464.944621499508685, 325.461235049656068, -177.524310027085136, 73.968462511285480, -22.759526926549377, 4.877041484260581, -0.650272197901411, 0.040642012368838}; 
const double butter_hp_a[] = {1.000000000000000, -9.730859519461649, 45.222424461913782, -132.965285187545618, 276.401755992073277, -430.173100182725307, 517.929531079109211, -491.639184505153366, 371.542897231422899, -224.127369006135268, 107.495012453638978, -40.537544323153909, 11.777555887860700, -2.547320867570707, 0.386646564494498, -0.036783568751103, 0.001651773169389};

/*
[n, Wn] = buttord((9/28.636),(10.0/28.636),15,30)
... as above
*/

const double butter_vlp_a[] = {1.000000000000000, -6.937616955034972, 23.970838770088655, -54.000427012043730, 88.061456238381183, -109.615737692123218, 107.291092756922552, -83.963755281752029, 52.957405639935935, -26.951950514411902, 11.011945319216913, -3.568605316842922, 0.898035788062039, -0.169453212774060, 0.022587985197723, -0.001898700131677, 0.000075758962287};
const double butter_vlp_b[] = {0.000000060937067, 0.000000974993079, 0.000007312448095, 0.000034124757775, 0.000110905462769, 0.000266173110647, 0.000487984036185, 0.000697120051694, 0.000784260058155, 0.000697120051694, 0.000487984036185, 0.000266173110647, 0.000110905462769, 0.000034124757775, 0.000007312448095, 0.000000974993079, 0.000000060937067}; 

const double zero = 7600000.0;
const double one = 9300000.0;
const double mfactor = 254.0 / (one - zero);

int main(int argc, char *argv[])
{
	int rv = 0, fd, dlen = 1024 * 1024 * 2;
	long long total = 0;
	double avg = 0.0;

	unsigned char *data;
	double *ddata;

	cerr << std::setprecision(16);

	fd = open(argv[1], O_RDONLY);
	if (argc >= 3) lseek64(fd, atoll(argv[2]), SEEK_SET);
	
	if (argc >= 4) {
		if ((size_t)atoi(argv[3]) < dlen) {
			dlen = atoi(argv[3]); 
		}
	}

	cerr << dlen << endl;

	data = new unsigned char[dlen + 1];

	dlen = read(fd, data, dlen);
	cout << std::setprecision(8);
	
	ddata = new double[dlen + 1];

	LDE butterin(16, butter_hp_a, butter_hp_b);
	LDE butterout(16, butter_vlp_a, butter_vlp_b);

	for (int i = 0; i < dlen; i++) {
		total += data[i];
	}

	avg = (double)total / (double)dlen;
	cerr << avg << endl;
	
	for (int i = 0; i < dlen; i++) {
		//cerr << i << endl;
		ddata[i] = butterin.feed((double)data[i] - avg);
//		ddata[i] = ((double)data[i] - avg);
		//if (i < 100) cerr << (double)(data[i] - avg) << ", ";
		if (i < 100) cerr << (double)(ddata[i]) << ", ";
		total += ddata[i];
	}

	bool insync = false;
	char outbuf[4096];
	int bufloc = 0;
	
	#define N 8 

	for (int i = N; i < dlen - N; i++) {		
		// One rough pass to get the approximate frequency for a pixel, and then a final pass to resolve it
		double pf = peakfreq(ddata, i, N, 7000000, 10000000, 500000, CHZ);

		if (pf != 0) {
			double pf2 = peakfreq(ddata, i, N, pf - 100000, pf + 100000, 20000, CHZ);
		
			if (pf2 != 0.0) pf = pf2;
		}

		if (insync) {
			if (pf > 7900000) {
				insync = false;
//				butterout.clear();
				pf = butterout.feed(pf);
				//cerr << i << ' ' << pf << ' ' << pf / 7600000.0 << endl;
			}
		} else {
			if (pf < 7650000) {
				insync = true;
			} else {
			//	cerr << pf << ' ';
				pf = butterout.feed(pf);
			//	cerr << pf << endl;
		//		cerr << i << ' ' << pf << ' ' << butterout.val << endl;
			}
		}
//		cerr << i << ' ' << pf << ' ' << lpf.val << endl;

		unsigned char out;
		double tmpout = ((double)(pf - zero) * mfactor);
			
		if (tmpout < 0) out = 0;
		else if (tmpout > 255) out = 255;
		else out = tmpout; 
				
//		cerr << i << ' ' << pf << ' ' << pf << ' ' << (int)out << endl;

		outbuf[bufloc++] = out;
		if (bufloc == 4096) {	
			if (write(1, outbuf, 4096) != 4096) {
				cerr << "write error\n";
				exit(0);
			}
			bufloc = 0;
		}
	};

#if 0
	LowPass lpf(0.8);

	double lf = 8000000.0;
	int pfc = 0, prev_i = 0;	
	for (int i = 512; i < dlen - 512; i++) {
		double pf = peakfreq(ddata, i, 128, 7600000, 9400000, 500000, CHZ);

//		cout << pf << endl;
		if (pf < 7800000) {
			pf = peakfreq(ddata, i, 128, 7500000, 7800000, 100000, CHZ);
//			cout << 'x' << pf << endl;
			if ((pf > 7570000) && (pf < 7630000)) {
				if (!pfc) {
					butterout.clear();
					pf = butter.feed(pf);
				} else {
					pf = butter.feed(pf);
				}
				if (pf < lf) lf = pf;
				pfc++;
			}
		} else {
			if (pfc > 80) {
				// cout << i << ' ' << i - prev_i << ' ' << pfc << ' ' << lf << ' ' << lpf.val << ' ' << (1820.0 / (lpf.val / 7600000.0)) << endl;
				prev_i = i;
			}

			lf = 8000000.0;

			if ((pfc > 80) && (pfc < 256)) i += (1820 - 256); 
			pfc = 0;
		}
	}
#endif
	delete [] data;
	delete [] ddata;

	return rv;
}

