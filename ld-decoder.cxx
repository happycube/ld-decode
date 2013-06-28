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

		double feed(T nv)
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

/* [n, Wn] = buttord((4.75/freq),(6/freq),5,20); [b, a] = butter(n, Wn, 'high'); */ 
const double butter_hp_a[] {1.000000000000000, -5.452003763582253, 13.301505580218667, -18.897609846239369, 17.055662325697007, -9.993957663170113, 3.707195076964163, -0.794935153408986, 0.075363617536322}; 
const double butter_hp_b[] {0.274524347761003, -2.196194782088027, 7.686681737308096, -15.373363474616191, 19.216704343270241, -15.373363474616191, 7.686681737308096, -2.196194782088027, 0.274524347761003}; 

/* [n, Wn] = buttord([(6/28.636), (20/28.636)],[(5.3/28.636),(21.5/28.636)],5,20) */
const double butter_bp_a[] {1.000000000000000, -1.708560919841575, 1.848799350100783, -1.812154162835113, 2.409265394434789, -2.181187978172917, 1.580615611624372, -1.068095638262071, 0.837490336169044, -0.479425849004081, 0.231495442539485, -0.101805027917706, 0.051011251354331, -0.016095112555307, 0.004363569816507, -0.000846544909261, 0.000229303114358};
const double butter_bp_b[] {0.006009756284377, 0.000000000000000, -0.048078050275014, 0.000000000000000, 0.168273175962549, 0.000000000000000, -0.336546351925098, 0.000000000000000, 0.420682939906373, 0.000000000000000, -0.336546351925098, 0.000000000000000, 0.168273175962549, 0.000000000000000, -0.048078050275014, 0.000000000000000, 0.006009756284377}; 

/*  b = fir2(32, [0 (2/14.318) (3/14.318) (4.5/14.318) (5.0/14.318) 1.0], [1 1 2 4 0 0]);*/
//const double sloper_b[] { -0.005466761616406, -0.000351999073346, 0.008289753201992, 0.012675324348554, -0.000191471023792, -0.029275356877612, -0.043358991235663, -0.003448368940716, 0.082197428496862, 0.134144115295690, 0.063430350582610, -0.119819463864256, -0.268913205779919, -0.207205193041071, 0.097593428758284, 0.464574836420657, 0.628603998819987, 0.464574836420657, 0.097593428758284, -0.207205193041071, -0.268913205779919, -0.119819463864256, 0.063430350582610, 0.134144115295690, 0.082197428496862, -0.003448368940716, -0.043358991235663, -0.029275356877612, -0.000191471023792, 0.012675324348554, 0.008289753201992, -0.000351999073346, -0.005466761616406}; 
const double sloper_a[130] {1, 0,};

/*  b = fir2(32, [0 (2/14.318) (3/14.318) (4.5/14.318) (5.0/14.318) 1.0], [1 1 2 4 0 0]);*/
const double sloper_b[] {-0.000382933090327, -0.006981809154571, -0.010728227199389, 0.002631923851791, 0.039289107592644, 0.066237756021515, 0.025065301059788, -0.093761155255764, -0.195764924035992, -0.140771313374372, 0.111345118277709, 0.419588831542530, 0.558754903157552, 0.419588831542530, 0.111345118277709, -0.140771313374372, -0.195764924035992, -0.093761155255764, 0.025065301059788, 0.066237756021515, 0.03928910759264}; 

// b = fir1(24, [(4.5/14.318)])
//const double f_inband_b[] {-0.001458335318862, -0.002737915886599, -0.001836705992068, 0.004085617415551, 0.012370069525266, 0.010951080350295, -0.010588722259342, -0.041169486390469, -0.043903285021353, 0.017273375962974, 0.138109125865719, 0.261765401589396, 0.314279560318985, 0.261765401589396, 0.138109125865719, 0.017273375962974, -0.043903285021353, -0.041169486390469, -0.010588722259342, 0.010951080350295, 0.012370069525266, 0.004085617415551, -0.001836705992068, -0.002737915886599, -0.001458335318862};
// 4.2
const double f_inband_b[] {-0.0021258831152027, -0.0017413220525271, 0.0010739857696014, 0.0069735741472413, 0.0108121362068461, 0.0027940210838033, -0.0200361248301128, -0.0417508398061147, -0.0311706453651985, 0.0346581583070210, 0.1444228282223425, 0.2495691561345716, 0.2930419105954573, 0.2495691561345716, 0.1444228282223425, 0.0346581583070210, -0.0311706453651985, -0.0417508398061147, -0.0200361248301128, 0.0027940210838033, 0.0108121362068461, 0.0069735741472413, 0.0010739857696014, -0.0017413220525271, -0.0021258831152027};
const double f_inband_a[25] {1, 0,};

const double f_flat_b[] {0, 0, 0, 0, 1, 0, 0, 0, 0};
const double f_flat_a[] {1, 0, 0, 0, 0, 0, 0, 0, 0};

const double f_diff_b[] {-0.0001635329437577, 0.0000250863493418, -0.0000491628576317, 0.0002990414592446, 0.0003996311166487, -0.0022588454691466, 0.0008485791841910, 0.0065302903475175, -0.0085278240384115, -0.0087503258843905, 0.0273990327824906, -0.0040853009352476, -0.0557297381930505, 0.0577653216430894, 0.0825424814206669, -0.2995204674752212, 0.4063410034179687, -0.2995204674752212, 0.0825424814206669, 0.0577653216430894, -0.0557297381930505, -0.0040853009352476, 0.0273990327824906, -0.0087503258843905, -0.0085278240384115, 0.0065302903475175, 0.0008485791841910, -0.0022588454691466, 0.0003996311166487, 0.0002990414592446, -0.0000491628576317, 0.0000250863493418, -0.0001635329437577};
const double f_diff_a[33] {1,};
 

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
		freq[i] = 8800000 + (sin(cphase * M_PIl * 2.0) * 000000);
		lphase += (freq[i] / CHZ);
		data[i] = (sin(lphase * M_PIl * 2.0) * 64) + 128;
	} 
#endif

	LDE butterin(16, butter_bp_a, butter_bp_b);
	//LDE butterout(24, sloper_a, sloper_b);
	LDE butterout(24, f_inband_a, f_inband_b);
	
	for (int i = 0; i < dlen; i++) {
		total += data[i];
	}

	avg = (double)total / (double)dlen;
	cerr << avg << endl;
	
	for (int i = 0; i < dlen; i++) {
		//cerr << i << endl;
	//	ddata[i] = butterin.feed((double)data[i] - avg);
		ddata[i] = ((double)data[i] - avg);
		//if (i < 100) cerr << (double)(data[i] - avg) << ", ";
		if (i < 100) cerr << (double)(ddata[i]) << ", ";
		total += ddata[i];
	}

	bool insync = false;
	double outbuf[32768], outbuf_nf[32768];
	int bufloc = 0;
	
	#define N 8 

	int ti;
	double synctime = 0;
	double offset = 0.0;

	int prevsync = 0, synccount = 0;
	double prev_offset = 0.0;

	int low = 7500000, high=9500000, bd = 100000;
	int nbands = ((high - low) / bd) + 2;

	LDE *inband_q[nbands];
	LDE *inband_i[nbands];
	double fbin[nbands];

	CircBuf<double> *cd_q[nbands], *cd_i[nbands];

	for (int f = low, j = 0; f < high; f+= bd, j++) {
//		inband_q[j] = new LDE(9, f_inband8_a, f_inband8_b);
//		inband_i[j] = new LDE(9, f_inband8_a, f_inband8_b);
		inband_q[j] = new LDE(32, f_diff_a, f_diff_b);
		inband_i[j] = new LDE(32, f_diff_a, f_diff_b);
		cd_q[j] = new CircBuf<double>(N, 0.1);
		cd_i[j] = new CircBuf<double>(N, 0.1);
		fbin[j] = CHZ / f;
	}

	for (int i = 128, ti = 0; i < dlen - 128; i++) {		
		double pf = 7600000;
		double level[nbands]; 
		double peak = 0;
		int npeak, f, j;

//		cerr << i << ' ';
		for (f = low, j = 0; f < high; f+= bd, j++) {
			//cerr << (j * bd) + low << ' ';
			//double fcq = inband_q[j]->feed(ddata[i] * cos((2.0 * M_PIl * ((double)i / fbin[j])))); 
			//double fci = inband_i[j]->feed(-ddata[i] * sin((2.0 * M_PIl * ((double)i / fbin[j])))); 
			double fcq = cd_q[j]->feed(ddata[i] * cos((2.0 * M_PIl * ((double)i / fbin[j])))); 
			double fci = cd_i[j]->feed(-ddata[i] * sin((2.0 * M_PIl * ((double)i / fbin[j])))); 
			//cerr << fbin[j] << ' ';
			//cerr << fcq << ' ';
			//cerr << fci << ' ';
			//cerr << ctor(fcq, fci) << ' ';
			level[j] = ctor(fcq, fci);
			if (level[j] > peak) {peak = level[j]; npeak = j;}
			//cerr << level[j] << endl; 
		}
//		cerr << endl << (npeak * bd) + low << ' ' << level[npeak] << endl;
		pf = (npeak * bd) + low;
	
		double dpi;
		if ((npeak >= 1) && (npeak < (j - 1))) {
			double p0 = level[npeak - 1];
			double p2 = level[npeak + 1];
		
			dpi = (double)npeak + ((p2 - p0) / (2.0 * ((2.0 * peak) - p0 - p2))); 
			pf = (dpi * bd) + low;	

			if (pf < 0) {
				cerr << "invalid freq " << pf << " peak bin " << (npeak * bd) + low << endl;
				pf = 0;
			}
		} else {
			pf = (!npeak) ? low : high;	
		}
		//cerr << i << ' ' << pf << ' ';
		pf = butterout.feed(pf - 8500000) + 8500000;
		outbuf[bufloc++] = pf;
		//cerr << outbuf[bufloc - 1] << endl;
	
		if (synccount < 60) {	
			synccount = (pf < 7750000) ? synccount + 1 : 0;
		} else {
			synccount = (pf > 8000000) ? -1 : synccount + 1;
		}
		if ((bufloc == 4096) || (synccount == -1)) {
			int ll = i - prevsync;
			double sf = 2.0;
			int outlen = bufloc / sf;
			double filtered[bufloc + 16];

			double pf_sync = 0;
			for (int t = bufloc - 1; t > bufloc - 31; t--) {
				pf_sync += outbuf[t] / 30.0;
			}
	
			if ((ll > 1800) && (ll < 1840)) {
				sf = ll / 910.0; //linelen.feed(ll);
//				sf = 2.0 * (7610000 / pf_sync); // ll / 910.0; //linelen.feed(ll);
//				sf = 2.0;
				outlen = bufloc / sf;
			}	
		
			cerr << "SYNC " << pf_sync << ' ' << ll << ' ' << sf << ' ' << bufloc << ' ' << bufloc / sf << ' ' << outlen << ' ' << (1820.0 ) / sf << endl; 

			for (int j = 0; j < bufloc; j++) {
				filtered[j] = outbuf[j];
			}

			unsigned short output[outlen + 1]; 
			double val = 0.0, cur = prev_offset;
			for (int j = 0; j < outlen; j++) {
				double ncur = cur + sf;

//				cerr << fabs(cur) << ' ' << outbuf_nf[(int)fabs(cur)] << ' ';
				val = filtered[(int)floor(cur)] * (1 - (cur - floor(cur))); 
				for (int k = floor(cur + 1); k < floor(ncur); k++) {
					val += filtered[k]; 
					//cerr << outbuf[k] << ' ';
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
			bufloc = 0;
		}
	};

	delete [] data;
	delete [] ddata;

	return rv;
}

