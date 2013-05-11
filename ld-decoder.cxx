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
	if (argc >= 3) lseek64(fd, atoi(argv[2]), SEEK_SET);
	
	if (argc >= 4) {
		if (atoi(argv[3]) < sizeof(data)) {
			dlen = atoi(argv[3]); 
		}
	}

	dlen = read(fd, data, dlen);
	cout << std::setprecision(8);

	for (int i = 0; i < dlen; i++) {
		if (data[i] > peak) peak = data[i];
		total += data[i];
	}

	avg = total / dlen;

	for (int i = 0; i < dlen; i++) {
		ddata[i] = (double)(data[i] - avg);
	}

	double curfreq = CHZ;

	double breq = curfreq / 8500000; 
	double freq = curfreq / 8500000; 
	double phase = 0.0;	

	LowPass lpfreq(0.20);
	LowPass lpsync(0.98);
	
	#define N 8

	bool insync = false;
	
	for (int i = N; i < dlen - N; i++) {
		double fc, fci;
		double bin[2048];
		double avg = 0.0;		
		
		for (int k = (-N + 1); k < N; k++) {
			avg += ddata[i + k] / ((2 * N) - 1);
		}

		// this is one bin of a DFT.  For quick+dirty reasons, I'm using lambdas inside the function.
		auto dft = [&](double f) -> double  
		{
			fc = fci = 0.0;
			freq = curfreq / (double)f;
	
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

		// One rough pass to get the approximate frequency, and then a final pass to resolve it
		tfreq = peakfinder(7600000, 9600000, 1000000);
		if (tfreq != 0) {
			double tfreq2 = peakfinder(tfreq - 100000, tfreq + 100000, 20000);
		
			if (tfreq2 != 0.0) tfreq = tfreq2;
		}

		lpfreq.feed(tfreq);

		// convert frequency into 8-bit unsigned output for the next phase
		const double zero = 7600000.0;
		const double one = 9300000.0;
		const double mfactor = 254.0 / (one - zero);

		if (insync) {
			if (tfreq > 7900000) {
				insync = false;
				if (fabs(lpsync.val - 7600000) < 100000) {
//					curfreq /= (lpsync.val / 7600000.0);
				}
				cerr << i << ' ' << lpsync.val << ' ' << (double)curfreq << ' ' << (double)CHZ << endl;
	
				breq = curfreq / 8500000; 
				freq = curfreq / 8500000; 
			}
			lpsync.feed(tfreq);
		} else {
			if (tfreq < 7700000) {
				insync = true;
				lpsync.reset(tfreq);
				// cerr << i << ' ' << tfreq << ' ' << lpfreq.val << endl;
			}
		}

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
			}
	};

	return 0;	
}
