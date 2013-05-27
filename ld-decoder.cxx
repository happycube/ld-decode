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
#define CHZ 1000000.0*(315.0/88.0)*8.0
#define FSC 1000000.0*(315.0/88.0)

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
		
//	dc_filter(buf_mdc, &buf[offset - len], (len * 2) + 1);
	
	// we include an extra bin on each side so we can do quadratric interp across the whole range 
	lf -= step;
	for (f = lf; f < hf + step + 1; f += step) { 
		bin[fbin] = dft(&buf[offset - len], len, len, (basefreq / f));
		if (bin[fbin] > peak) {
			peak = bin[fbin];
			peakbin = fbin;
		}
		fbin++;
//		cerr << i << ':' << f << ' ' << fc << ',' << fci << ' ' << ctor(fc, fci) / N << ' ' << atan2(fci, ctor(fc, fci)) << endl;
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
		cerr << "out of range on sample " <<  offset << " with step " << step;
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

			for (int i = 0; i < order; i++) {
				x[i] = y[i] = 0;
			}
		}

		~LDE() {
			delete [] x;
			delete [] y;
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
	[a, b] = butter(16, 0.097924, 'high')
	printf("%.8f, ", a)
*/

const double butter_hp_b[] = {0.20647902526747857754330084389949, -3.30366440427965724069281350239180, 24.77748303209742886110689141787589, -115.62825414978800608878373168408871, 375.79182598681103399940184317529202, -901.90038236834641338646179065108299, 1653.48403434196848138526547700166702, -2362.12004905995490844361484050750732, 2657.38505519244927199906669557094574, -2362.12004905995490844361484050750732, 1653.48403434196848138526547700166702, -901.90038236834641338646179065108299, 375.79182598681103399940184317529202, -115.62825414978800608878373168408871, 24.77748303209742886110689141787589, -3.30366440427965724069281350239180, 0.20647902526747857754330084389949}; 
const double butter_hp_a[] = {1.00000000000000000000000000000000, -12.86170756446714946719112049322575, 77.80017740541025261791219236329198, -293.75959794017700232870993204414845, 774.83735716097351087228162214159966, -1513.69268253862560413836035877466202, 2265.32085282868365538888610899448395, -2648.95087949110074987402185797691345, 2445.79518280118281836621463298797607, -1788.85430416912390683137346059083939, 1032.90116095567964293877594172954559, -465.85215205623853762517683207988739, 160.87228176988406858072266913950443, -41.11744213191413876984370290301740, 7.33505345580190848409074533265084, -0.81593407233554682278509062598459, 0.04263358787540802441462517435866};

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
	if (argc >= 3) lseek64(fd, atoi(argv[2]), SEEK_SET);
	
	if (argc >= 4) {
		if ((size_t)atoi(argv[3]) < sizeof(data)) {
			dlen = atoi(argv[3]); 
		}
	}

	data = new unsigned char[dlen + 1];

	dlen = read(fd, data, dlen);
	cout << std::setprecision(8);
	
	ddata = new double[dlen + 1];

	LDE butter(16, butter_hp_a, butter_hp_b);

	for (int i = 0; i < dlen; i++) {
		total += data[i];
	}

	avg = (double)total / (double)dlen;
	cerr << avg << endl;
	
	for (int i = 0; i < dlen; i++) {
		//cerr << i << endl;
		ddata[i] = butter.feed((double)data[i] - avg);
		//if (i < 100) cerr << (double)(data[i] - avg) << ", ";
		if (i < 100) cerr << (double)(ddata[i]) << ", ";
		total += ddata[i];
	}

	cout << dlen<<endl;
		
	bool insync = false;
	char outbuf[4096];
	int bufloc = 0;
	
	LowPass lpf(0.2);

	for (int i = 8; i < dlen - 8; i++) {		
		// One rough pass to get the approximate frequency for a pixel, and then a final pass to resolve it
		double pf = peakfreq(ddata, i, 8, 7000000, 10000000, 250000, CHZ);

		if (pf != 0) {
			double pf2 = peakfreq(ddata, i, 8, pf - 100000, pf + 100000, 20000, CHZ);
		
			if (pf2 != 0.0) pf = pf2;
		}

		if (insync) {
			if (pf > 7900000) {
				insync = false;
				//cerr << i << ' ' << pf << ' ' << pf / 7600000.0 << endl;
			}
		} else {
			if (pf < 7650000) {
				insync = true;
			}
		}

		unsigned char out;
		double tmpout = ((double)(pf - zero) * mfactor);
			
		if (tmpout < 0) out = 0;
		else if (tmpout > 255) out = 255;
		else out = tmpout; 
				
		//cerr << i << ' ' << pf << ' ' << pf << ' ' << (int)out << endl;

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
					lpf.reset(pf);
				} else {
					lpf.feed(pf);
				}
				if (pf < lf) lf = pf;
				pfc++;
			}
		} else {
			if (pfc > 80) {
				cout << i << ' ' << i - prev_i << ' ' << pfc << ' ' << lf << ' ' << lpf.val << ' ' << (1820.0 / (lpf.val / 7600000.0)) << endl;
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


