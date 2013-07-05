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

// 4.5mhz filter
const double f_inband8_b[] { -4.8895027341377632e-03, 4.5950362400661512e-03, 8.5194126749789864e-02, 2.4665672386348092e-01, 3.3688723176160174e-01, 2.4665672386348100e-01, 8.5194126749789878e-02, 4.5950362400661521e-03, -4.8895027341377632e-03}; 
const double f_inband8_a[9] {1, 0,};

// b = fir1(24, [(4.5/14.318)])
const double f_inband_b[] {-0.001458335318862, -0.002737915886599, -0.001836705992068, 0.004085617415551, 0.012370069525266, 0.010951080350295, -0.010588722259342, -0.041169486390469, -0.043903285021353, 0.017273375962974, 0.138109125865719, 0.261765401589396, 0.314279560318985, 0.261765401589396, 0.138109125865719, 0.017273375962974, -0.043903285021353, -0.041169486390469, -0.010588722259342, 0.010951080350295, 0.012370069525266, 0.004085617415551, -0.001836705992068, -0.002737915886599, -0.001458335318862};
// 4.2
//const double f_inband_b[] {-0.0021258831152027, -0.0017413220525271, 0.0010739857696014, 0.0069735741472413, 0.0108121362068461, 0.0027940210838033, -0.0200361248301128, -0.0417508398061147, -0.0311706453651985, 0.0346581583070210, 0.1444228282223425, 0.2495691561345716, 0.2930419105954573, 0.2495691561345716, 0.1444228282223425, 0.0346581583070210, -0.0311706453651985, -0.0417508398061147, -0.0200361248301128, 0.0027940210838033, 0.0108121362068461, 0.0069735741472413, 0.0010739857696014, -0.0017413220525271, -0.0021258831152027};
const double f_inband_a[25] {1, 0,};

const double f_flat_b[] {0, 0, 0, 0, 1, 0, 0, 0, 0};
const double f_flat_a[] {1, 0, 0, 0, 0, 0, 0, 0, 0};

const double f_diff_b[] {-0.0001635329437577, 0.0000250863493418, -0.0000491628576317, 0.0002990414592446, 0.0003996311166487, -0.0022588454691466, 0.0008485791841910, 0.0065302903475175, -0.0085278240384115, -0.0087503258843905, 0.0273990327824906, -0.0040853009352476, -0.0557297381930505, 0.0577653216430894, 0.0825424814206669, -0.2995204674752212, 0.4063410034179687, -0.2995204674752212, 0.0825424814206669, 0.0577653216430894, -0.0557297381930505, -0.0040853009352476, 0.0273990327824906, -0.0087503258843905, -0.0085278240384115, 0.0065302903475175, 0.0008485791841910, -0.0022588454691466, 0.0003996311166487, 0.0002990414592446, -0.0000491628576317, 0.0000250863493418, -0.0001635329437577};
const double f_diff_a[33] {1,};

// 3.5mhz fir1
//const double f_hp_b[] {-5.2233122995139940e-04, -1.7082609318519331e-02, -8.5929313061105295e-02, -1.9084603032392095e-01, 7.5704600929723254e-01, -1.9084603032392097e-01, -8.5929313061105309e-02, -1.7082609318519335e-02, -5.2233122995139940e-04}; 
//const double f_hp_b[] { 4.8532613891468770e-04, 8.3390507431009651e-04, 7.6869993408222299e-04, 2.0690363502716850e-04, -7.1004989863944273e-04, -1.5399702230112086e-03, -1.6590132291091372e-03, -6.3102914998487008e-04, 1.3457397262763970e-03, 3.2651198285648729e-03, 3.7005630528483013e-03, 1.6988706219031816e-03, -2.3100665249408746e-03, -6.2805595979030975e-03, -7.4213411391159199e-03, -3.9159736278543186e-03, 3.4628609286186051e-03, 1.1022046672099554e-02, 1.3725619417974226e-02, 8.1714270701632903e-03, -4.6285461225751374e-03, -1.8553394109051539e-02, -2.4784285266225312e-02, -1.6623676456192293e-02, 5.6251394069828471e-03, 3.2613737881770924e-02, 4.8555731456348221e-02, 3.7976938900159532e-02, -6.2948092938117572e-03, -7.7907146600187480e-02, -1.5757890608989139e-01, -2.1987460976329917e-01, 7.5635985531755634e-01, -2.1987460976329917e-01, -1.5757890608989139e-01, -7.7907146600187480e-02, -6.2948092938117581e-03, 3.7976938900159539e-02, 4.8555731456348221e-02, 3.2613737881770931e-02, 5.6251394069828480e-03, -1.6623676456192293e-02, -2.4784285266225312e-02, -1.8553394109051539e-02, -4.6285461225751400e-03, 8.1714270701632886e-03, 1.3725619417974231e-02, 1.1022046672099552e-02, 3.4628609286186055e-03, -3.9159736278543220e-03, -7.4213411391159181e-03, -6.2805595979031001e-03, -2.3100665249408741e-03, 1.6988706219031816e-03, 3.7005630528483039e-03, 3.2651198285648724e-03, 1.3457397262763974e-03, -6.3102914998487019e-04, -1.6590132291091379e-03, -1.5399702230112094e-03, -7.1004989863944338e-04, 2.0690363502716912e-04, 7.6869993408222343e-04, 8.3390507431009759e-04, 4.8532613891468770e-04}; 
const double f_hp_b[] { -3.6315861562715454e-04, 6.2894182939766063e-04, 3.0111986214688283e-04, 1.8845833191473188e-03, -7.9280012703750267e-04, 8.9325610952693194e-04, -3.6912268163235727e-03, -7.8333995702427366e-05, -2.7354939869451674e-03, 3.1063458422602233e-03, 3.3540027639192586e-03, 3.5246830244444567e-03, 3.8719858692722606e-03, -8.0936656980037085e-03, -9.6597768805999605e-04, -1.6733302769842608e-02, 8.6205303103566080e-03, -4.7516842775922928e-03, 2.5745041780324610e-02, 3.2867510961838487e-03, 9.6084093191679161e-03, -1.4845258455340094e-02, -3.0615710235647582e-02, -8.5976135903761460e-03, -2.8181449677278210e-02, 6.2403079730476013e-02, 6.7735184952764926e-04, 1.0496976497636988e-01, -6.6878788705777473e-02, 9.1965871412481217e-03, -2.4476309912599065e-01, -1.3583380546459459e-01, 6.5304594558071272e-01, -1.3583380546459459e-01, -2.4476309912599065e-01, 9.1965871412481217e-03, -6.6878788705777459e-02, 1.0496976497636989e-01, 6.7735184952764894e-04, 6.2403079730476020e-02, -2.8181449677278213e-02, -8.5976135903761443e-03, -3.0615710235647582e-02, -1.4845258455340096e-02, 9.6084093191679213e-03, 3.2867510961838492e-03, 2.5745041780324617e-02, -4.7516842775922911e-03, 8.6205303103566097e-03, -1.6733302769842622e-02, -9.6597768805999561e-04, -8.0936656980037120e-03, 3.8719858692722584e-03, 3.5246830244444584e-03, 3.3540027639192608e-03, 3.1063458422602220e-03, -2.7354939869451678e-03, -7.8333995702427596e-05, -3.6912268163235727e-03, 8.9325610952693054e-04, -7.9280012703750375e-04, 1.8845833191473184e-03, 3.0111986214688429e-04, 6.2894182939765998e-04, -3.6315861562715454e-04};

const double f_a[256] {1,};

const double zero = 7500000.0;
const double one = 9400000.0;
const double mfactor = 65536.0 / (one - zero);

const int linelen = 2048;

// todo?:  move into object

const int low = 7400000, high=9800000, bd = 100000;
const int nbands = ((high + 1 - low) / bd);

double fbin[nbands];

double c_cos[nbands][linelen];
double c_sin[nbands][linelen];

CircBuf<double> *cd_q[nbands], *cd_i[nbands];
	
LDE *lpf45[nbands];

void init_table()
{
	int N = 8;

	for (int f = low, j = 0; f < high; f+= bd, j++) {
		cd_q[j] = new CircBuf<double>(N, 1.0/N);
		cd_i[j] = new CircBuf<double>(N, 1.0/N);
		fbin[j] = CHZ / f;
		//lpf45[j] = new LDE(24, NULL, f_inband_b);
		lpf45[j] = new LDE(8, NULL, f_inband8_b);

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

int decode_line(unsigned char *rawdata, unsigned short *output)
{
	double data[linelen], out[linelen];
	int rv = 0, total = 0;
	LDE lpf_in(64, NULL, f_hp_b);

	for (int i = 0; i < linelen; i++) {
		total += rawdata[i];
	}

	double avg = (double)total / (double)linelen;

	// perform averaging and low-pass filtering on input
	for (int i = 0; i < linelen; i++) {
		data[i] = lpf_in.feed(rawdata[i] - avg);
	//	data[i] = (rawdata[i] - avg);
	}

	// perform multi-band FT
	for (int i = 0; i < linelen; i++) {
		int npeak = -1;
		double level[linelen], peak = -1;
		int f, j;

		for (f = low, j = 0; f < high; f += bd, j++) {
			double fcq = cd_q[j]->feed(data[i] * c_cos[j][i]); 
			double fci = cd_i[j]->feed(-data[i] * c_sin[j][i]); 

			level[j] = ctor(fcq, fci);
			level[j] = lpf45[j]->feed(level[j]);
			if (level[j] > peak) {peak = level[j]; npeak = j;}
		}
		double pf = (npeak * bd) + low;
	
		//cerr << i << ' ' << pf << ' ' << peak << endl;
	
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
			pf = (!npeak) ? low : f;	
		}
		out[i] = pf;
	}
#if 0 // decided not to do tbc here afterall
	int sync = findsync(out, 2048);

	rv = sync;
	cerr << 'x' << sync << endl;
	if ((sync <= 256) || (sync > 512)) {
		rv = -abs(sync);
		sync = 0;
	}

	int sync2 = findsync(out + (sync + 1800), (2048 - sync - 1800));

	if (sync2 > 0) sync2 += (sync + 1800);
	//cerr << sync2 << ' ' << (2048 - sync - 1800) << endl;

	// get color burst values 
	double pi, pq;
	double scale[32];

	for (int i = 40; i < 72; i++) {
		scale[i - 40] = (out[i] - 8000000) / 400000; 
	}

	dftc(scale, 16, 16, 8, pi, pq);
	cerr << pi << ' ' << pq << ' ' << atan2(pi, pq) << endl;
#endif
	double halfout[910];	
	for (int j = 0; j < 910; j++) {
		halfout[j] = (out[(j * 2) + 64] + out[(j * 2) + 65]) / 2;
	}	

	for (int i = 0; i < 910; i++) {
		unsigned short iout;
		double tmpout = ((double)(halfout[i] - zero) * mfactor);

		if (tmpout < 0) iout = 0;
		else if (tmpout > 65535) iout = 65535;
		else iout = tmpout;

		output[i] = iout;
	}
			
	return rv;
}

int main(int argc, char *argv[])
{
	int rv = 0, fd, dlen = 1024 * 1024 * 2;
	long long total = 0;
	double avg = 0.0;
	unsigned short output[1820];

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
		freq[i] = 8500000 + (sin(cphase * M_PIl * 2.0) * 000000);
		lphase += (freq[i] / CHZ);
		data[i] = (sin(lphase * M_PIl * 2.0) * 64) + 128;
	} 
#endif

	init_table();

	int i = 4096;
	while ((i + 1820) < dlen) {	
		int rv = decode_line(&data[i], output);
		cerr << i << ' ' << rv << endl;

		i+=1820;
		if (write(1, output, 2 * 910) != 2 * 910) {
			//cerr << "write error\n";
			exit(0);
		}
/*
		if ((rv < 0) && (rv >= -256)) {
			i -= 128;
		} else if ((rv < 0) && (rv >= -256)) {
			i += 128;
		}
*/
	}
	return 0;
}

