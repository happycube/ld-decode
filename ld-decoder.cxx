/* NTSC decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

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
#define CHZ 1000000.0*(315.0/88.0)*8.0

#define FSC 1000000.0*(315.0/88.0)

using namespace std;

double ctor(fftw_complex c)
{
	return sqrt((c[0] * c[0]) + (c[1] * c[1]));
} 

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
}


// state-containing high pass filter
class Highpass {
	private:
		double dt, RC;
		double a;
		double o_prev, in_prev;
	public:
		Highpass(double _dt = (1.0 / CHZ), double _RC = (1.0 / 2700000.0))
		{
			dt = _dt;
			RC = _RC;
			a = RC / (RC + dt);
			in_prev = o_prev = 0.0;

//			cout << RC << ',' << dt << ',' << a << endl;
		}	
		double iterate(double in) {
			double o;

			o = (a * o_prev) + (a * (in - in_prev)); 
			o_prev = o;
			in_prev = in;

			return o;
		}
};

// state-containing low pass filter
class Lowpass {
	private:
		double dt, RC;
		double a;
		double o_prev, in_prev;
	public:
		Lowpass(double _dt = (1.0 / CHZ), double _RC = (1.0 / 10000000.0))
		{
			dt = _dt;
			RC = _RC;
			a = dt / (RC + dt);
			in_prev = o_prev = 0.0;

//			cout << RC << ',' << dt << ',' << a << endl;
		}	
		double iterate(double in) {
			double o;

			o = (a * in) + ((1 - a) * o_prev); 
			o_prev = o;
			in_prev = in;

			return o;
		}
};

unsigned char data[28*1024*1024];
double ddata[28 * 1024 * 1024];

int main(int argc, char *argv[])
{
	int rv, fd, dlen;
	unsigned char avg, peak = 0;
	long long total = 0;
	int rp;

	fd = open(argv[1], O_RDONLY);
	if (argc >= 3) lseek64(fd, atoi(argv[2])*1024*1024, SEEK_SET);

	dlen = read(fd, data, sizeof(data));

	cout << std::setprecision(8);

	for (int i = 0; i < dlen; i++) {
		if (data[i] > peak) peak = data[i];
		total += data[i];
	}

	avg = total / dlen;

#define HP 0
#if HP 
	Highpass hp;
	Lowpass lp;

	// high pass
	for (int i = 0; i < dlen; i++) {
		double in = (double)(data[i] - avg);
		ddata[i] = hp.iterate(in); 
	}
#else
	for (int i = 0; i < dlen; i++) {
		ddata[i] = (double)(data[i] - avg);
	}
#endif

	double breq = CHZ / 8500000; 
	double freq = CHZ / 8500000; 
	double phase = 0.0;	
	
	#define N 8
	
	for (int i = N; i < dlen - N; i++) {
		double fc, fci;
		double peak = 0, peakfreq = 0;	
		double bin[2048];
		int fbin = 0, peakbin = 0;
		double avg = 0.0;		

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
			
		for (int k = (-N + 1); k < N; k++) {
			avg += ddata[i + k] / ((2 * N) - 1);
		}

		phase = 0.0;	
		for (int f = 7500000; f < 9400000 + 500000; f += 50000) { 
			bin[fbin] = dft(f);
			if (bin[fbin] > peak) {
				peak = bin[fbin];
				peakfreq = f;
				peakbin = fbin;
			}
			fbin++;
//			cerr << i << ':' << f << ' ' << fc << ',' << fci << ' ' << ctor(fc, fci) / N << ' ' << atan2(fci, ctor(fc, fci)) << endl;
		}

		double dpi;
		double tfreq;	
		if (peakbin >= 1) {
			double p0 = bin[peakbin - 1];
			double p2 = bin[peakbin + 1];
		
			dpi = (double)peakbin + ((p2 - p0) / (2.0 * ((2.0 * peak) - p0 - p2))); 
			tfreq = (dpi * 50000) + 7500000;	

			dft(tfreq);
//			cerr << i << ':' << tfreq << ' ' << fc << ',' << fci << ' ' << ctor(fc, fci) << ' ' << atan2(fci, ctor(fc, fci)) << endl;
//			phase -= atan2(fci, ctor(fc, fci));
		}

//		tfreq = (dpi * 50000) + 7500000;	
		// cerr << bin[0] << ' ' << tfreq << endl;
	
		const double zero = 7600000.0;
		const double one = 9300000.0;
		const double mfactor = 254.0 / (one - zero);

		unsigned char out;
		double tmpout = ((double)(tfreq - zero) * mfactor);

		if (tmpout < 0) out = 0;
		else if (tmpout > 255) out = 255;
		else out = tmpout; 

		write(1, &out, 1);	

//		cerr << i << ' ' << peakfreq << ' ' << peakbin << ':' << (dpi * 500000) + 7500000 << ' ' << (int) out << endl;
	};

	return 0;	
}
