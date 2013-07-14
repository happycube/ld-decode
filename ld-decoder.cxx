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
//			_feed(nv);
//			_feed((latest * .75) + (nv * .25));
//			_feed((latest * .5) + (nv * .5));
//			_feed((latest * .25) + (nv * .75));
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

const double f_inband4_b[] { 3.5666419234145923e-02, 2.4104820178557229e-01, 4.4657075796056345e-01, 2.4104820178557235e-01, 3.5666419234145923e-02  };

// 4.2mhz filter
const double f_inband8_b[] {-3.5634174409531622e-03, 9.4654740832740107e-03, 9.1456278081537348e-02, 2.4141004764330087e-01, 3.2246323526568188e-01, 2.4141004764330090e-01, 9.1456278081537348e-02, 9.4654740832740124e-03, -3.5634174409531609e-03}; 
const double f_inband8_a[9] {1, 0,};

const double f_inband6_b[] {2.4022915041852354e-02, 9.3282252671075941e-02, 2.3198968207147672e-01, 3.0141030043118994e-01, 2.3198968207147680e-01, 9.3282252671075941e-02, 2.4022915041852354e-02  };

const double f_inband7_b[] { 2.0639067636214502e-02, 6.5484287559733512e-02, 1.6641090209130313e-01, 2.4746574271274874e-01, 2.4746574271274879e-01, 1.6641090209130316e-01, 6.5484287559733539e-02, 2.0639067636214502e-02 }; 

const double f_inband10_b[] { 1.4473689993225168e-02, 3.0481961953682260e-02, 7.2460474187224108e-02, 1.2449718560551960e-01, 1.6668129896367703e-01, 1.8281077859334358e-01, 1.6668129896367706e-01, 1.2449718560551964e-01, 7.2460474187224122e-02, 3.0481961953682267e-02, 1.4473689993225168e-02 };

const double f_inband12_b[] { 1.2044644014910172e-02, 2.1421282730098870e-02, 4.7063446272317504e-02, 8.2220344973345905e-02, 1.1748376963988481e-01, 1.4335163673986193e-01, 1.5282975125916140e-01, 1.4335163673986195e-01, 1.1748376963988487e-01, 8.2220344973345919e-02, 4.7063446272317497e-02, 2.1421282730098887e-02, 1.2044644014910171e-02 }; 

const double f_inband16_b[] { 8.9727868389106926e-03, 1.2981375511317471e-02, 2.4367856526345349e-02, 4.1492976778828870e-02, 6.1792338849973226e-02, 8.2174723473312908e-02, 9.9507815960196741e-02, 1.1111353861554261e-01, 1.1519317489114411e-01, 1.1111353861554263e-01, 9.9507815960196755e-02, 8.2174723473312936e-02, 6.1792338849973226e-02, 4.1492976778828863e-02, 2.4367856526345353e-02, 1.2981375511317481e-02, 8.9727868389106926e-03 }; 

// b = fir1(24, [(4.5/14.318)])
const double f_inband_b[] {-0.001458335318862, -0.002737915886599, -0.001836705992068, 0.004085617415551, 0.012370069525266, 0.010951080350295, -0.010588722259342, -0.041169486390469, -0.043903285021353, 0.017273375962974, 0.138109125865719, 0.261765401589396, 0.314279560318985, 0.261765401589396, 0.138109125865719, 0.017273375962974, -0.043903285021353, -0.041169486390469, -0.010588722259342, 0.010951080350295, 0.012370069525266, 0.004085617415551, -0.001836705992068, -0.002737915886599, -0.001458335318862};
// 4.2
//const double f_inband_b[] {-0.0021258831152027, -0.0017413220525271, 0.0010739857696014, 0.0069735741472413, 0.0108121362068461, 0.0027940210838033, -0.0200361248301128, -0.0417508398061147, -0.0311706453651985, 0.0346581583070210, 0.1444228282223425, 0.2495691561345716, 0.2930419105954573, 0.2495691561345716, 0.1444228282223425, 0.0346581583070210, -0.0311706453651985, -0.0417508398061147, -0.0200361248301128, 0.0027940210838033, 0.0108121362068461, 0.0069735741472413, 0.0010739857696014, -0.0017413220525271, -0.0021258831152027};
const double f_inband_a[25] {1, 0,};

const double f_flat_b[] {0, 0, 0, 0, 1, 0, 0, 0, 0};
const double f_flat_a[] {1, 0, 0, 0, 0, 0, 0, 0, 0};

const double f_diff_b[] {-0.0001635329437577, 0.0000250863493418, -0.0000491628576317, 0.0002990414592446, 0.0003996311166487, -0.0022588454691466, 0.0008485791841910, 0.0065302903475175, -0.0085278240384115, -0.0087503258843905, 0.0273990327824906, -0.0040853009352476, -0.0557297381930505, 0.0577653216430894, 0.0825424814206669, -0.2995204674752212, 0.4063410034179687, -0.2995204674752212, 0.0825424814206669, 0.0577653216430894, -0.0557297381930505, -0.0040853009352476, 0.0273990327824906, -0.0087503258843905, -0.0085278240384115, 0.0065302903475175, 0.0008485791841910, -0.0022588454691466, 0.0003996311166487, 0.0002990414592446, -0.0000491628576317, 0.0000250863493418, -0.0001635329437577};
const double f_diff_a[33] {1,};

// 8-tap 3.5mhz high-pass fir1
const double f_hp8_b[] {-5.2233122995139940e-04, -1.7082609318519331e-02, -8.5929313061105295e-02, -1.9084603032392095e-01, 7.5704600929723254e-01, -1.9084603032392097e-01, -8.5929313061105309e-02, -1.7082609318519335e-02, -5.2233122995139940e-04};

// 64-tap 3.75mhz high-pass fir1
const double f_hp_b[] {-7.0923708380408047e-04, -2.3251905255110359e-04, 4.8575571908952988e-04, 1.0722682497955394e-03, 1.0729041253752371e-03, 2.2351660282327550e-04, -1.2109437593036290e-03, -2.3437353448091678e-03, -2.0916071787832205e-03, -1.4451389624136754e-05, 2.9988472409555864e-03, 4.8921739972686215e-03, 3.6751803533387308e-03, -9.0450534328188935e-04, -6.4951986392191609e-03, -9.0863899372204942e-03, -5.6134947648300050e-03, 3.3196286192241167e-03, 1.2706494067793631e-02, 1.5565690867403271e-02, 7.6118157386835762e-03, -8.6920490026209021e-03, -2.3865906373439900e-02, -2.6165783531054587e-02, -9.3452659450452384e-03, 2.1133007715282752e-02, 4.7944921933848278e-02, 4.9258702461956509e-02, 1.0521353767674078e-02, -6.5645397779266534e-02, -1.5751039107008202e-01, -2.3235452500130585e-01, 7.3970080799953608e-01, -2.3235452500130585e-01, -1.5751039107008200e-01, -6.5645397779266534e-02, 1.0521353767674079e-02, 4.9258702461956516e-02, 4.7944921933848271e-02, 2.1133007715282752e-02, -9.3452659450452384e-03, -2.6165783531054594e-02, -2.3865906373439900e-02, -8.6920490026209038e-03, 7.6118157386835814e-03, 1.5565690867403271e-02, 1.2706494067793634e-02, 3.3196286192241201e-03, -5.6134947648300067e-03, -9.0863899372205046e-03, -6.4951986392191600e-03, -9.0450534328189065e-04, 3.6751803533387295e-03, 4.8921739972686232e-03, 2.9988472409555886e-03, -1.4451389624136642e-05, -2.0916071787832205e-03, -2.3437353448091699e-03, -1.2109437593036290e-03, 2.2351660282327518e-04, 1.0729041253752381e-03, 1.0722682497955394e-03, 4.8575571908952961e-04, -2.3251905255110346e-04, -7.0923708380408047e-04 };


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
		//cd_q[j] = new LDE(8, NULL, f_inband8_b);
		//cd_i[j] = new LDE(8, NULL, f_inband8_b);
		cd_q[j] = new LDE(8, NULL, f_inband8_b);
		cd_i[j] = new LDE(8, NULL, f_inband8_b);
		fbin[j] = CHZ / f;

		for (int i = 0; i < linelen; i++) {
			c_cos[j][i] = cos((2.0 * M_PIl * ((double)i / fbin[j]))); 
			c_sin[j][i] = sin((2.0 * M_PIl * ((double)i / fbin[j]))); 
		}
	}
}

int findsync(double *out, int len)	
{
	int stsync = -1, sync = 1;

	// find sync
	for (int i = 0; (i < len) && (sync <= 1); i++) {
//		cerr << i << ' ' << out[i] << endl;
		if (stsync == -1) {
			if (out[i] < 7610000) stsync = i;
		} else {
			if (out[i] > 8200000) {
				if ((i - stsync) > 30) {
					sync = stsync;
				} else stsync = -1;
			}
		}		
	}		

	return sync;
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

		double pf = 0.0, avg = 0.0;

		for (f = low, j = 0; f < high; f += bd, j++) {
//			double oq = cd_q[j]->val;
//			double oi = cd_i[j]->val;
			double fcq = cd_q[j]->feed(data[i] * c_cos[j][i]); 
			double fci = cd_i[j]->feed(-data[i] * c_sin[j][i]); 

			level[j] = atan2(fci, fcq) - phase[j]; 
			if (level[j] > M_PIl) level[j] -= (2 * M_PIl);
			else if (level[j] < -M_PIl) level[j] += (2 * M_PIl);

//			cerr << f << ' ' << level[j] << ' ' << f * (level[j] / 2.0) << endl; 
		
//			avg += f - (f * level[j] / (28.63636 / 16.0));	
//			avg += f + ((f / 2.0) * level[j]);
			//cerr << f << ' ' << level[j] << ' ' << f + ((f / 2.0) * level[j])  << ' ' << atan2(fcq, fci) << ' ' << fcq << ' ' << fci << ' ' << endl;
//			cerr << f << ' ' << level[j] << ' ' << f + ((f / 2.0) * level[j])  << ' ' << ctor(fcq, fci) << ' ' << ctor(fcq - oq, fci - oi) << ' ' << fcq - oq << ' ' << fci - oi<< ' ' << endl;
//			cerr << (9200000.0 - f) / (level[j] / (CHZ / f)) << endl;
//			cerr << f + ((9200000.0 / 2.0) * level[j]) << endl;

			if (fabs(level[j]) < peak) {
				npeak = j;
				peak = level[j];
				pf = f + ((f / 2.0) * level[j]);
			}
			phase[j] = atan2(fci, fcq);
		}

		pf = lpf45.feed(pf);

		out[i] = pf;
	}

	double savg = 0, tvolt = 0;
	for (int i = 0; i < 1820; i++) {
		unsigned short iout;
		double tmpout = ((double)(out[i + 128] - zero) * mfactor);

		output[i] = (out[i + 128] - zero) / (9400000.0 - 7600000.0);
		tvolt += output[i];

	//	cerr << i << ' ' << out[i + 128] << ' ' << output[i] << endl;
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
	
#if 0
	double *freq = new double[dlen];
	memset(freq, 0, sizeof(double) * dlen);
	double lphase = 0.0, cphase = 0.0;

	for (int i = 0; i < dlen; i++) {
		cphase += ((FSC / 2) / CHZ);
		freq[i] = 8500000 + (sin(cphase * M_PIl * 2.0) * 000000);
		lphase += (freq[i] / CHZ);
		data[i] = (sin(lphase * M_PIl * 2.0) * 64) + 128;
	} 
#endif

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

