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
		T *buf;
		T total;
	public:
		CircBuf(int size) {
			buf = new T[size];

			count = size;
			cur = 0;
			total = 0;
			firstpass = true;
		}

		double feed(T nv)
		{
			if (!firstpass) {
				total -= buf[cur];
			}  

			buf[cur] = nv;
			total += nv;
			cur++;
			if (cur == count) {
				cur = 0; firstpass = false;
			}

			if (firstpass) {
				return total / cur;
			} else {
				return total / count;
			}
		}
};

class LowPass {
	protected:
		bool first;
	public:
		double alpha;
		double val;
		
		LowPass(double _alpha = 0.15) {
			alpha = _alpha;	
			first = true;
			val = 0.0;
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

unsigned char rdata[1024*1024*32];

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

inline void dftc(double *buf, int offset, int len, double bin, double &fc, double &fci) 
{
	fc = fci = 0.0;

	for (int k = (-len + 1); k < len; k++) {
		double o = buf[offset + k]; 
		
		fc += (o * cos((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
		fci -= (o * sin((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
	}
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
		bin[fbin] = dft(&buf[offset - len], len, len, (basefreq / f));
//		bin[fbin] = dft(buf_mdc, len, len, (basefreq / f));
//		cerr << f << ' ' << bin[fbin] << endl;
		if (bin[fbin] > peak) {
			peak = bin[fbin];
			peakbin = fbin;
	//		cerr << f << ' ' << peak << endl;
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
		pf = (!peakbin) ? lf : hf;	
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

// look for a zero crossing to sync up to
int findzc(double *x, int len)
{
	double buf_mdc[len];

	dc_filter(buf_mdc, x, len);

	for (int i = 1; i < len; i++) {
		if ((buf_mdc[i] > 0) && (buf_mdc[i - 1] < 0)) return i;
	}
	return 0;
}

/* [n, Wn] = buttord((4.75/freq),(6/freq),5,20); [b, a] = butter(n, Wn, 'high'); */ 
const double butter_hp_a[] {1.000000000000000, -5.452003763582253, 13.301505580218667, -18.897609846239369, 17.055662325697007, -9.993957663170113, 3.707195076964163, -0.794935153408986, 0.075363617536322}; 
const double butter_hp_b[] {0.274524347761003, -2.196194782088027, 7.686681737308096, -15.373363474616191, 19.216704343270241, -15.373363474616191, 7.686681737308096, -2.196194782088027, 0.274524347761003}; 

/* [n, Wn] = buttord([(6/28.636), (20/28.636)],[(5.3/28.636),(21.5/28.636)],5,20) */
const double butter_bp_a[] {1.000000000000000, -1.708560919841575, 1.848799350100783, -1.812154162835113, 2.409265394434789, -2.181187978172917, 1.580615611624372, -1.068095638262071, 0.837490336169044, -0.479425849004081, 0.231495442539485, -0.101805027917706, 0.051011251354331, -0.016095112555307, 0.004363569816507, -0.000846544909261, 0.000229303114358};
const double butter_bp_b[] {0.006009756284377, 0.000000000000000, -0.048078050275014, 0.000000000000000, 0.168273175962549, 0.000000000000000, -0.336546351925098, 0.000000000000000, 0.420682939906373, 0.000000000000000, -0.336546351925098, 0.000000000000000, 0.168273175962549, 0.000000000000000, -0.048078050275014, 0.000000000000000, 0.006009756284377}; 

/* [n, Wn] = buttord((9/freq),(11/freq),5,20); [b, a] = butter(n, Wn); printf("%.15f, ", a); printf("\n");printf("%.15f, ", b); printf("\n"); */

//const double butter_vlp_28a[] {1.000000000000000, -3.158234920673198, 5.114344712366162, -5.125405870554332, 3.422893181883937, -1.535675781320924, 0.448655610713883, -0.077507747696208, 0.006035943167793}; 
//const double butter_vlp_28b[] {0.000371504405809, 0.002972035246472, 0.010402123362653, 0.020804246725305, 0.026005308406632, 0.020804246725305, 0.010402123362653, 0.002972035246472, 0.000371504405809}; 

/* [n, Wn] = buttord((4.5/freq),(6/freq),3,25); [b, a] = butter(n, Wn); printf("%f %f\n", n, Wn); printf("%.15f, ", a); printf("\n");printf("%.15f, ", b); printf("\n"); */

const double butter_vlp_28a[] {1.000000000000000, -2.955334800381594, 4.607255143193481, -4.467535165870464, 2.906391161426700, -1.274216653993614, 0.364989006532751, -0.061949530725109, 0.004749610655610};
const double butter_vlp_28b[] {0.000485737386085, 0.003885899088680, 0.013600646810380, 0.027201293620760, 0.034001617025950, 0.027201293620760, 0.013600646810380, 0.003885899088680, 0.000485737386085};

const double zero = 7500000.0;
const double one = 9400000.0;
const double mfactor = 65536.0 / (one - zero);

int main(int argc, char *argv[])
{
	int rv = 0, fd, dlen = 1024 * 1024 * 2;
	long long total = 0;
	double avg = 0.0;

	unsigned char *data;
	double *ddata;

	cerr << std::setprecision(16);

	data = new unsigned char[dlen + 1];
#if 1
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
#endif
	
	ddata = new double[dlen + 1];

	double *freq = new double[dlen];
	memset(freq, 0, sizeof(double) * dlen);
#if 0
	double lphase = 0.0, cphase = 0.0;

	for (int i = 0; i < dlen; i++) {
		cphase += ((FSC / 2) / CHZ);
		freq[i] = 8800000 + (sin(cphase * M_PIl * 2.0) * 200000);
		lphase += (freq[i] / CHZ);
		data[i] = (sin(lphase * M_PIl * 2.0) * 64) + 128;
	} 
#endif

	//LDE butterin(8, butter_hp_a, butter_hp_b);
	LDE butterin(16, butter_bp_a, butter_bp_b);
	LDE butterout(8, butter_vlp_28a, butter_vlp_28b);
	
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
	double outbuf[32768], outbuf_nf[32768];
	int bufloc = 0;
/*
	CircBuf<double> cbvar(32);

	LowPass lpavg(0.99);
	lpavg.feed(ddata[0]);

	for (int i = 16; i < dlen; i++) {		
		lpavg.feed(ddata[i]);

		double lpgap = (cbvar.feed(fabs(ddata[i] - lpavg.val))) / (M_PIl / 4.0) * 1.0;

		double cdata = ddata[i];
		double pcdata = ddata[i - 1];

		double g1 = (atan2(pcdata, (lpgap / 2.0)) / (M_PIl / 4.0));
                double g2 = (atan2(cdata, (lpgap / 2.0)) / (M_PIl / 4.0));

//		cerr << i << ' ' << (int)data[i] << ' ' << ddata[i] << ' ' << lpavg.val << ' ' << lpgap << ' ' << g1 << ' ' << g2 << endl;
	}	
	
	return 0;
*/	
	#define N 8 

	int ti;
	double synctime = 0;
	double offset = 0.0;

	int prevsync = 0, synccount = 0;
	double prev_offset = 0.0;

	LowPass linelen(0.0);

	for (int i = 128, ti = 128; i < dlen - 128; i++) {		
/*
		ti++;
		if (synctime && i == (int)(synctime + .5)) {
			double pf = peakfreq(ddata, i, 32, 7300000, 7900000, 100000, CHZ);
			double pf2 = peakfreq(ddata, i, 32, pf - 40000, pf + 40000, 10000, CHZ);

			cerr << "SYNC: " << pf << ' ' << pf2 << ' ' << 1820 * (7600000.0 / pf2) << endl;
			synctime += ((7600000.0 / pf2) * 1820);
			offset += ((7600000.0 / pf2) * 1820) - 1820;
			i = ti + (offset + .5); 
		}
*/
		// One rough pass to get the approximate frequency for a pixel, and then a final pass to resolve it
		double pf = peakfreq(ddata, i, N, 7300000, 9500000, 100000, CHZ);

		if (pf != 0) {
			double pf2 = peakfreq(ddata, i, N, pf - 40000, pf + 40000, 10000, CHZ);
		
			if (pf2 != 0.0) pf = pf2;
		}
	
		// cerr << i << ' ' << freq[i] << ' ' << pf << ' ' ;	
		outbuf_nf[bufloc++] = pf;
		pf = butterout.feed(pf - 8500000) + 8500000;
		outbuf[bufloc] = pf;
		//cerr << pf << ' ' << endl;
	
		synccount = (pf < 7750000) ? synccount + 1 : 0;
		if ((bufloc == 4096) || (synccount == 60)) {
			int ll = i - prevsync;
			double sf = 2.0;
			int outlen = bufloc / sf;
			double filtered[bufloc + 16];
			
			double pf_sync = peakfreq(ddata, i, 32, 7500000, 7700000, 10000, CHZ);
	
			LDE butterp1(8, butter_vlp_28a, butter_vlp_28b);
			LDE butterp2(8, butter_vlp_28a, butter_vlp_28b);

			if ((ll > 1800) && (ll < 1840)) {
				sf = ll / 910.0; //linelen.feed(ll);
				outlen = bufloc / sf;
			}	
		
			cerr << "SYNC " << pf_sync << ' ' << ll << ' ' << sf << ' ' << bufloc << ' ' << bufloc / sf << ' ' << outlen << ' ' << linelen.val << endl; 

			for (int j = 0; j < bufloc; j++) {
				filtered[j] = outbuf[j];
				//cerr << outbuf_nf[j] << ' ' << outbuf[j] << ' ' << filtered[j] << endl;
			}
/*			for (int j = bufloc - 1; j >= 0; j--) {
				filtered[j] = butterp2.feed(filtered[j] - 7600000) + 7600000;
				cerr << j << ' ' << outbuf_nf[j] << ' ' << outbuf[j] << ' ' << filtered[j] << endl;
			}
*/	
			unsigned short output[outlen + 1]; 
			double val = 0.0, cur = prev_offset;
			for (int j = 0; j < outlen; j++) {
				double ncur = cur + sf;

//				cerr << fabs(cur) << ' ' << outbuf_nf[(int)fabs(cur)] << ' ';
				val = filtered[(int)floor(cur)] * (1 - (cur - floor(cur))); 
				for (int k = floor(cur + 1); k < floor(ncur); k++) {
					val += filtered[k]; 
//					cerr << outbuf[k] << ' ';
				} 
				if (ncur != floor(ncur)) {
//					cerr << 'e'<< outbuf[(int)floor(ncur)];
					val += filtered[(int)floor(ncur)] * (ncur - floor(ncur)); 
				}
				filtered[j] = val / sf * (2.0 / sf);
//				cerr << j << ' ' << filtered[j] << endl;
//				cerr << endl << j << ' ' << cur << ' ' << ncur << ' ' << val << ' ' << (ncur - floor(ncur)) << endl;
				cur = ncur;
			}
			
			for (int j = 0; j < outlen; j++) {
				unsigned short out;
				double tmpout = ((double)(filtered[j] - zero) * mfactor);
				
				if (tmpout < 0) out = 0;
				else if (tmpout > 65535) out = 65535;
				else out = tmpout; 

				output[j] = out;
			}
			
			if (write(1, output, 2 * outlen) != 2 * outlen) {
				cerr << "write error\n";
				exit(0);
			}

			prevsync = i;
			
			outbuf[0] = outbuf[bufloc - 1];
			prev_offset = 0; // cur - floor(cur);
			cerr << endl << outbuf[0] << ' ' << cur << ' ' << prev_offset << endl;
			bufloc = 0;
		}
	};

	delete [] data;
	delete [] ddata;

	return rv;
}

