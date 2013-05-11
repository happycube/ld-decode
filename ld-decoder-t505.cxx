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
//#define CHZ 500000000
#define FSC 1000000.0*(315.0/88.0)

using namespace std;

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
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
				val = val;
			} else {
				val = (alpha * val) + ((1 - alpha) * _val);	
			}
			return val;
		}
};

unsigned char data[28*1024*1024];
double ddata[28 * 1024 * 1024];

int main(int argc, char *argv[])
{
	int rv, fd, dlen = sizeof(data);
	unsigned char avg, peak = 0;
	long long total = 0;
	int rp;

	char outbuf[4096];
	int bufloc = 0;

	fd = open(argv[1], O_RDONLY);
	if (argc >= 3) lseek64(fd, atoi(argv[2]) * CHZ, SEEK_SET);

	if (argc >= 4) dlen = atoi(argv[3]); 
	if (dlen > sizeof(data)) dlen = sizeof(data);

	dlen = read(fd, data, dlen);
	
	cout << std::setprecision(8);

	for (int i = 0; i < dlen; i++) {
		if (data[i] > peak) peak = data[i];
		total += data[i];
	}

	avg = total / dlen;

	LowPass lpdata(0.075);
	for (int i = 0; i < dlen; i++) {
		lpdata.feed((double)(data[i] - avg));
		ddata[i] = lpdata.val;
	}

	double breq = CHZ / 8500000; 
	double freq = CHZ / 8500000; 
	double phase = 0.0;	
	
	#define N 8

//	LowPass lppeak(0.8), lptrough(0.8);
	double lppeak = 0.0, lptrough = 0.0;
	double pcdata = 0.0;

	LowPass fgap(0.85);
	LowPass lpf_freq(0.0);

	int zcgap = 0;

	double cphase = 0.0, tphase = 0.0, zcloc = 0.0;
	double crate = M_PIl / 2.0;
	
	for (int i = N; i < dlen - N; i++) {
		double fc, fci;
		double bin[2048];
		double avg = 0.0;		
		
		for (int k = (-N + 1); k < N; k++) {
			avg += ddata[i + k] / ((2 * N) - 1);
		}
			
		if ((ddata[i] > ddata[i - 1]) && (ddata[i] > ddata[i + 1])) {
			if (ddata[i] > lppeak) {
				lppeak = ddata[i];
			} else {
				lppeak = (.8 * lppeak) + (.2 * ddata[i]);
			}
//			if (lptrough < -lppeak) lptrough = -lppeak;
	//		lppeak = ddata[i];
		} 
		
		if ((ddata[i] < ddata[i - 1]) && (ddata[i] < ddata[i + 1])) {
			if (ddata[i] < lptrough) {
				lptrough = ddata[i];
			} else {
				lptrough = (.8 * lptrough) + (.2 * ddata[i]);
			}
//			if (lppeak < -lptrough) lppeak = -lptrough;
	//		lptrough = ddata[i];
		} 

		// this is one bin of a DFT.  For quick+dirty reasons, I'm using lambdas inside the function.
		auto dft = [&](double f) -> double  
		{
			fc = fci = 0.0;
			freq = CHZ / (double)f;
	
			for (int k = (-N + 1); k < N; k++) {
				double o = ddata[i + k]; 
				// double o = (ddata[i + k] - avg) * (1 - fabs((double)k / (double)N)); 

				// cerr << k << ' ' << o << ' ' << (ddata[i + k] - avg) << endl;

				fc += (o * cos(phase + (2.0 * M_PIl * ((double)(i - k) / freq)))); 
				fci -= (o * sin(phase + (2.0 * M_PIl * ((double)(i - k) / freq)))); 
		
			}
			return ctor(fc, fci);
		};
		
		double tfreq;	

		// Run a few bins of the DFT and use quadratric interpretation to find the frequency peak.  In effect due to the
		// DFT size, this is low pass filtered.
		auto peakfinder = [&](double lf, double hf, double step) -> double  
		{
			double peak = 0, peakfreq = 0;	
			int fbin = 0, peakbin = 0;
			int f;
	
			// we include an extra bin on each side so we can do quadratric interp across the whole range 
			lf -= step;
			for (f = lf; f < hf + step + 1; f += step) { 
				bin[fbin] = dft(f);
				if (bin[fbin] > peak) {
					peak = bin[fbin];
					peakfreq = f;
					peakbin = fbin;
				}
				fbin++;
//				cerr << i << ':' << f << ' ' << fc << ',' << fci << ' ' << ctor(fc, fci) / N << ' ' << atan2(fci, ctor(fc, fci)) << endl;
			}

			double dpi;
			double tfreq;	
			if ((peakbin >= 1) && (peakbin < (fbin - 1))) {
				double p0 = bin[peakbin - 1];
				double p2 = bin[peakbin + 1];
		
				dpi = (double)peakbin + ((p2 - p0) / (2.0 * ((2.0 * peak) - p0 - p2))); 
				tfreq = (dpi * step) + lf;	

				if (tfreq < 0) {
					cerr << "invalid freq " << tfreq << " peak bin " << (peakbin * step) + lf << endl;
					tfreq = 0;
				}
			} else {
				// this generally only happens during a long dropout
//				cerr << "out of range on sample " << i << " with step " << step;
				tfreq = 0;	
			}

			return tfreq;
		};
/*
		// One rough pass to get the approximate frequency, and then a final pass to resolve it
		tfreq = peakfinder(7600000, 9600000, 500000);
		if (tfreq != 0) {
			double tfreq2 = peakfinder(tfreq - 100000, tfreq + 100000, 10000);
		
			if (tfreq2 != 0.0) tfreq = tfreq2;
		}
*/
		{ 
			double lpgap = lppeak - lptrough;
			double cdata = (ddata[i] - lptrough) - (lpgap / 2);
			double gap = 0.0;

//			cerr << asin(cdata / lpgap) - asin(pcdata / lpgap) << endl;

			if (((cdata >= 0) && (!(pcdata >= 0))) ||
			    ((cdata < 0) && (!(pcdata < 0)))) {
				double g1 = (atan2(pcdata, (lpgap / 2.0)) / (M_PIl / 4.0));
				double g2 = (atan2(cdata, (lpgap / 2.0)) / (M_PIl / 4.0));
				bool half = false;

				if (g2 < 0) {
					g1 = -g1; g2 = -g2;
					half = true;
				};

				double gtot = g2 - g1;
				
				double new_zcloc = (double)i - 1.0 - (double)(g1 / gtot);
				fgap.feed(new_zcloc - zcloc);
				cerr << "zc: " << i << ':' << new_zcloc << ' ' << fgap.val << endl;

				cphase = (i - new_zcloc) / fgap.val;
				crate = new_zcloc - zcloc;
				cerr << cphase << endl;
				
				zcloc = new_zcloc;
				zcgap = 0.0;
			} else {
				cphase += (1.0 / crate);
				cerr << cphase << ' ' << zcloc + crate << ' ' << zcloc + fgap.val << endl;
			}
			
//			cerr << atan2(cdata, lpgap / 2) << ' ' << cdata << ' ' << pcdata << ' ' << lppeak - lptrough << ' ' ;

			pcdata = cdata;
		}

		if (fgap.val) lpf_freq.feed(CHZ / (fgap.val * 2.0));

//		cerr << lpf_freq.val << ' ' << tfreq << ' ' << ddata[i] << ' ' << lppeak << ' ' << lptrough << endl;
		tfreq = lpf_freq.val;
		
		// convert frequency into 8-bit unsigned output for the next phase
		const double zero = 7600000.0;
		const double one = 9500000.0;
		const double mfactor = 254.0 / (one - zero);

		unsigned char out;
		double tmpout = ((double)(tfreq - zero) * mfactor);

		if (tmpout < 0) out = 0;
		else if (tmpout > 255) out = 255;
		else out = tmpout; 

		outbuf[bufloc++] = out;
		if (bufloc == 4096) {	
			if (write(1, outbuf, 4096) != 4096) {
				cerr << "write error\n";
				exit(0);
			}
			bufloc = 0;
			memset(outbuf, 0, 4096);
		}
	};
	write(1, outbuf, bufloc);

	return 0;	
}
