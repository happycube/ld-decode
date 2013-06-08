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

/* [n, Wn] = buttord((4.75/28.636),(6/28.636),5,20); [b, a] = butter(n, Wn); */ 

const double butter_hp_b[] {0.274519698994363, -2.196157591954904, 7.686551571842164, -15.373103143684329, 19.216378929605412, -15.373103143684329, 7.686551571842164, -2.196157591954904, 0.274519698994363}; 
const double butter_hp_a[] {1.000000000000000, -5.451971339878093, 13.301357128600866, -18.897310764958611, 17.055320256020426, -9.993718550464875, 3.707093163051426, -0.794910674423948, 0.075361065158677};  

/* [n, Wn] = buttord((9/28.636),(11/28.636),5,20); [b, a] = butter(8, .30166); printf("%.15f, ", a); printf("\n");printf("%.15f, ", b); printf("\n"); */

const double butter_vlp_a[] {1.000000000000000, -3.158134334331964, 5.114084769831670, -5.125062350588971, 3.422619065378838, -1.535535239782429, 0.448610127017045, -0.077499208036140, 0.006035230997728};
const double butter_vlp_b[] {0.000371554923773, 0.002972439390181, 0.010403537865632, 0.020807075731264, 0.026008844664080, 0.020807075731264, 0.010403537865632, 0.002972439390181, 0.000371554923773}; 

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

	LDE butterin(8, butter_hp_a, butter_hp_b);
	LDE butterout(8, butter_vlp_a, butter_vlp_b);

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
				butterout.clear();
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
					pf = butterout.feed(pf);
				} else {
					pf = butterout.feed(pf);
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

