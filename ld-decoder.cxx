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

template <class T> class CircBuf {
	protected:
		bool firstpass;
		long count, cur;
		T latest;	
		T *buf;
		T total;
		double decay;
	public:
		CircBuf(int size, double _decay = 0.0) {
			buf = new T[size];

			decay = _decay;
			count = size;
			cur = 0;
			total = 0;
			firstpass = true;
		}

		double _feed(T nv)
		{
			total = 0;
			buf[cur] = nv;
			cur++;
			if (cur == count) {
				cur = 0;
			}

			for (int i = 0; i < count; i++) {
				int p = cur - i;

				if (p < 0) p += 8;	
				total += buf[p] * (1.0 - (decay * (count - i)));
			}

			return total / count;
		}
		
		double feed(T nv) {
			latest = nv;
			return _feed(nv);
		}
};

unsigned char rdata[1024*1024*32];

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

		inline double feed(double val) {
			double a0;

			if (!a) a0 = 1;

			for (int i = order - 1; i >= 1; i--) {
				x[i] = x[i - 1];
				if (a) y[i] = y[i - 1];
			}
		
			x[0] = val;
	
			y[0] = ((b[0] / a0) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			for (int o = 1; o < order; o++) {
				y[0] += ((b[o] / a0) * x[o]);
				if (a) y[0] -= ((a[o] / a[0]) * y[o]);
				//cerr << o << ' ' << x[o] << ' ' << y[o] << ' ' << a[o] << ' ' << b[o] << ' ' << (b[o] * x[o]) << ' ' << -(a[o] * y[o]) << ' ' << y[0] << endl;
			}

			return y[0];
		}
		double val() {return y[0];}
};

// 4.2mhz filter
const double f_inband8_b[] {-3.5634174409531622e-03, 9.4654740832740107e-03, 9.1456278081537348e-02, 2.4141004764330087e-01, 3.2246323526568188e-01, 2.4141004764330090e-01, 9.1456278081537348e-02, 9.4654740832740124e-03, -3.5634174409531609e-03}; 

const double f_inband7_b[] { 2.0639067636214502e-02, 6.5484287559733512e-02, 1.6641090209130313e-01, 2.4746574271274874e-01, 2.4746574271274879e-01, 1.6641090209130316e-01, 6.5484287559733539e-02, 2.0639067636214502e-02 }; 

// 8-tap 3.5mhz high-pass fir1
const double f_hp8_b[] {-5.2233122995139940e-04, -1.7082609318519331e-02, -8.5929313061105295e-02, -1.9084603032392095e-01, 7.5704600929723254e-01, -1.9084603032392097e-01, -8.5929313061105309e-02, -1.7082609318519335e-02, -5.2233122995139940e-04};

const double f_a[256] {1,};

const double zero = 7600000.0;
const double one = 9400000.0;
const double mfactor = 65536.0 / (one - zero);

const int linelen = 2048;

// todo?:  move into object

const int low = 7400000, high=9800000, bd = 200000;
const int nbands = ((high + 1 - low) / bd);

double fbin[nbands];

double c_cos[nbands][linelen];
double c_sin[nbands][linelen];

//CircBuf<double> *cd_q[nbands], *cd_i[nbands];
LDE *cd_q[nbands], *cd_i[nbands];
	
LDE lpf45(7, NULL, f_inband7_b);

void init_table()
{
	int N = 8;

	for (int f = low, j = 0; f < high; f+= bd, j++) {
//		cd_q[j] = new CircBuf<double>(N, 1.0/N);
//		cd_i[j] = new CircBuf<double>(N, 1.0/N);
		cd_q[j] = new LDE(8, NULL, f_inband8_b);
		cd_i[j] = new LDE(8, NULL, f_inband8_b);
		fbin[j] = CHZ / f;

		for (int i = 0; i < linelen; i++) {
			c_cos[j][i] = cos((2.0 * M_PIl * ((double)i / fbin[j]))); 
			c_sin[j][i] = sin((2.0 * M_PIl * ((double)i / fbin[j]))); 
		}
	}
}

int decode_line(unsigned char *rawdata, double *output)
{
	double data[linelen], out[linelen];
	int rv = 0, total = 0;
	LDE lpf_in(8, NULL, f_hp8_b);

	for (int i = 0; i < linelen; i++) {
		total += rawdata[i];
	}

	double avg = (double)total / (double)linelen;

	// perform averaging and low-pass filtering on input
	for (int i = 0; i < linelen; i++) {
		//data[i] = lpf_in.feed(rawdata[i] - avg);
		data[i] = (rawdata[i] - avg);
	}

	double phase[6400];
	memset(phase, 0, sizeof(phase));

	// perform multi-band FT
	for (int i = 1; i < linelen; i++) {
		int npeak = -1;
		double level[linelen], peak = 50000;
		int f, j;

		double pf = 0.0;

		for (f = low, j = 0; f < high; f += bd, j++) {
			double fcq = cd_q[j]->feed(data[i] * c_cos[j][i]); 
			double fci = cd_i[j]->feed(-data[i] * c_sin[j][i]); 

			level[j] = atan2(fci, fcq) - phase[j]; 
			if (level[j] > M_PIl) level[j] -= (2 * M_PIl);
			else if (level[j] < -M_PIl) level[j] += (2 * M_PIl);

			if (fabs(level[j]) < peak) {
				npeak = j;
				peak = level[j];
				pf = f + ((f / 2.0) * level[j]);
			}
			phase[j] = atan2(fci, fcq);
		}

		out[i] = lpf45.feed(pf);
	}

	double savg = 0, tvolt = 0;
	for (int i = 0; i < 1820; i++) {
		unsigned short iout;
		double tmpout = ((double)(out[i + 128] - zero) * mfactor);

		output[i] = (out[i + 128] - zero) / (9400000.0 - 7600000.0);
		tvolt += output[i];
	}

	savg = tvolt / 1820.0;	
	double sdev = 0.0;
	for (int i = 0; i < 1820.0; i++) {
		sdev += ((output[i] - savg) * (output[i] - savg));
	}	
	sdev = sqrt(sdev / 1820.0);

	cerr << "avg " << savg << " sdev " << sdev << " snr " << 10 * log(savg / sdev) << endl;

	return rv;
}

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
	double output[2048];
	unsigned char inbuf[2048];

	cerr << std::setprecision(16);

	cerr << argc << endl;

	cerr << strncmp(argv[1], "-", 1) << endl;

	if (argc >= 2 && (strncmp(argv[1], "-", 1))) {
		fd = open(argv[1], O_RDONLY);
	}

	if (argc >= 3) {
		unsigned long long offset = atoll(argv[2]);

		if (offset) lseek64(fd, offset, SEEK_SET);
	}
		
	if (argc >= 4) {
		if ((size_t)atoi(argv[3]) < dlen) {
			dlen = atoi(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	init_table();
	rv = read(fd, inbuf, 2048);

	int i = 2048;

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		int rv = decode_line(inbuf, output);
		cerr << i << ' ' << rv << endl;

		if (write(1, output, sizeof(double) * 1820) != sizeof(double) * 1820) {
			//cerr << "write error\n";
			exit(0);
		}

		i += 1820;
		memmove(inbuf, &inbuf[1820], 228);
		rv = read(fd, &inbuf[228], 1820) + 228;
		
		if (rv < 2048) return 0;
		cerr << i << ' ' << rv << endl;
	}
	return 0;
}

