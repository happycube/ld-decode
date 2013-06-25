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

/* Convolutions/Linear difference equation - used for running filters (compute with Octave, etc) */

class LDE {
	protected:
		int order;
		double *a, *b;
		double *y, *x;
	public:
		LDE(int _order, double *_b, double *_a = NULL) {
			order = _order + 1;
			if (a) {
				a = _a;
			} else {
				a = new double[order];
				memset(a, 0, sizeof(double) * order);
				a[0] = 1;
			}
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

/* freq = (315.0/88.0)*4.0; */
/* [n, Wn] = buttord((4.75/freq),(6/freq),5,20); [b, a] = butter(n, Wn, 'high'); */ 
double butter_hp_a[] {1.0000000000000000, -2.5477665133399001, 3.4711460168307182, -2.8593664037376740, 1.5268811433436142, -0.5152325185165261, 0.1011938476710476, -0.0088319540333235};
double butter_hp_b[] {0.0939876437302563, -0.6579135061117938, 1.9737405183353813, -3.2895675305589691, 3.2895675305589691, -1.9737405183353813, 0.6579135061117938, -0.0939876437302563}; 

/* [n, Wn] = buttord((9/freq),(11/freq),5,20); [b, a] = butter(n, Wn); printf("%.15f, ", a); printf("\n");printf("%.15f, ", b); printf("\n"); */

double butter_vlp_28a[] {1.000000000000000, -3.158234920673198, 5.114344712366162, -5.125405870554332, 3.422893181883937, -1.535675781320924, 0.448655610713883, -0.077507747696208, 0.006035943167793}; 
double butter_vlp_28b[] {0.000371504405809, 0.002972035246472, 0.010402123362653, 0.020804246725305, 0.026005308406632, 0.020804246725305, 0.010402123362653, 0.002972035246472, 0.000371504405809}; 

/* b = remez(128, [0 (2.5/freq) (2.5/freq) (4.5/freq) (5/freq) 1], [1 1 1 2.5 0 0], "bandpass", 64) 
 * (note:  older octave-signal version does not converge on this 
 */

double remez_video_b[] {-0.005283744753615, 0.005816942836669, 0.005894634243617, 0.004048576350532, 0.000125319794896, -0.003053316540670, -0.002635630017031, 0.001009381422714, 0.004127628210791, 0.003093527318651, -0.001677796593564, -0.005603637812976, -0.004277181682051, 0.001753226138760, 0.006844163241262, 0.005538846190903, -0.001628792657750, -0.007915637970272, -0.006687198871883, 0.001588035403844, 0.008996735530715, 0.007652101176095, -0.001983044005598, -0.010618026364779, -0.008911826877547, 0.002648504400234, 0.013069531193109, 0.011177617378051, -0.002661258416354, -0.015546799565779, -0.014060770594173, 0.001809705605413, 0.017185645784779, 0.016174038156356, -0.001682914145682, -0.019277240892007, -0.017933588755227, 0.003159052840831, 0.023994288112510, 0.022247712328122, -0.003576123351677, -0.029927340251047, -0.029571381477889, 0.000597528477214, 0.033356440812685, 0.035599694603303, 0.001887347234603, -0.036474161446189, -0.039336768676278, 0.001393587424660, 0.048408124673997, 0.050928453956187, -0.004183657891692, -0.071546238424124, -0.082748565086720, -0.011676025009251, 0.090551705034350, 0.130553505658253, 0.055299772733543, -0.088562225680068, -0.177544703680999, -0.107239751253985, 0.114588076194348, 0.358712832519984, 0.464111069481044, 0.358712832519984, 0.114588076194348, -0.107239751253985, -0.177544703680999, -0.088562225680068, 0.055299772733543, 0.130553505658253, 0.090551705034350, -0.011676025009251, -0.082748565086720, -0.071546238424124, -0.004183657891692, 0.050928453956187, 0.048408124673997, 0.001393587424660, -0.039336768676278, -0.036474161446189, 0.001887347234603, 0.035599694603303, 0.033356440812685, 0.000597528477214, -0.029571381477889, -0.029927340251047, -0.003576123351677, 0.022247712328122, 0.023994288112510, 0.003159052840831, -0.017933588755227, -0.019277240892007, -0.001682914145682, 0.016174038156356, 0.017185645784779, 0.001809705605413, -0.014060770594173, -0.015546799565779, -0.002661258416354, 0.011177617378051, 0.013069531193109, 0.002648504400234, -0.008911826877547, -0.010618026364779, -0.001983044005598, 0.007652101176095, 0.008996735530715, 0.001588035403844, -0.006687198871883, -0.007915637970272, -0.001628792657750, 0.005538846190903, 0.006844163241262, 0.001753226138760, -0.004277181682051, -0.005603637812976, -0.001677796593564, 0.003093527318651, 0.004127628210791, 0.001009381422714, -0.002635630017031, -0.003053316540670, 0.000125319794896, 0.004048576350532, 0.005894634243617, 0.005816942836669, -0.005283744753615};

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

	LDE butterin(8, butter_hp_b, butter_hp_a);
	LDE filterout(128, remez_video_b);
	
	for (int i = 0; i < dlen; i++) {
		total += data[i];
	}

	avg = (double)total / (double)dlen;
	cerr << avg << endl;
	
	for (int i = 0; i < dlen; i++) {
		//cerr << i << endl;
//		ddata[i] = butterin.feed((double)data[i] - avg);
		ddata[i] = ((double)data[i] - avg);
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
		pf = filterout.feed(pf - 8500000) + 8500000;
		outbuf[bufloc] = pf;
		//cerr << pf << ' ' << endl;
	
		synccount = (pf < 7750000) ? synccount + 1 : 0;
		if ((bufloc == 4096) || (synccount == 60)) {
			int ll = i - prevsync;
			double sf = 2.0;
			int outlen = bufloc / sf;
			double filtered[bufloc + 16];
			
			double pf_sync = peakfreq(ddata, i, 32, 7500000, 7700000, 10000, CHZ);
	
			LDE butterp1(8, butter_vlp_28b, butter_vlp_28a);
			LDE butterp2(8, butter_vlp_28b, butter_vlp_28a);

			if ((ll > 1800) && (ll < 1840)) {
				sf = ll / 910.0; //linelen.feed(ll);
//				sf = 2.0 * (7605000.0 / pf_sync); // ll / 910.0; //linelen.feed(ll);
//				sf = 2.0;
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

