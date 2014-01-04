/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

// to decode resulting audio: sox -r 48k -e signed -b 16 -c 2 [in] [out.wav]

#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <vector>
#include <list>
#include <queue>
#include <complex>
#include <unistd.h>
#include <sys/fcntl.h>
#include <fftw3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// capture frequency and fundamental NTSC color frequency
const double CHZ = (1000000.0*(315.0/88.0)*8.0);

using namespace std;

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

	return dftc(buf, offset, len, bin, fc, fci);
}

class Filter {
	protected:
		int order;
		bool isIIR;
		vector<double> a, b;
		vector<double> y, x;
	public:
		Filter(int _order, const double *_a, const double *_b) {
			order = _order + 1;
			if (_a) {
				a.insert(b.begin(), _a, _a + order);
				isIIR = true;
			} else {
				a.push_back(1.0);
				isIIR = false;
			}
			b.insert(b.begin(), _b, _b + order);
			x.resize(order);
			y.resize(order);
	
			clear();
		}

		Filter(Filter *orig) {
			order = orig->order;
			isIIR = orig->isIIR;
			a = orig->a;
			b = orig->b;
			x.resize(order);
			y.resize(order);
				
			clear();
		}

		void clear(double val = 0) {
			for (int i = 0; i < order; i++) {
				x[i] = y[i] = val;
			}
		}

		inline double feed(double val) {
			double a0 = a[0];
			double y0;

			double *x_data = x.data();
			double *y_data = y.data();

			memmove(&x_data[1], x_data, sizeof(double) * (order - 1)); 
			if (isIIR) memmove(&y_data[1], y_data, sizeof(double) * (order - 1)); 

			x[0] = val;
			y0 = 0; // ((b[0] / a0) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			if (isIIR) {
				for (int o = 0; o < order; o++) {
					y0 += ((b[o] / a0) * x[o]);
					if (o) y0 -= ((a[o] / a0) * y[o]);
					//cerr << o << ' ' << x[o] << ' ' << y[o] << ' ' << a[o] << ' ' << b[o] << ' ' << (b[o] * x[o]) << ' ' << -(a[o] * y[o]) << ' ' << y[0] << endl;
				}
			} else {
				for (int o = 0; o < order; o++) {
					y0 += b[o] * x[o];
				}
			}

			y[0] = y0;
			return y[0];
		}
		double val() {return y[0];}
};


double f_bpfaud_32_b[] {-4.274276021174761e-03, -2.488356498115624e-03, 1.719837367951319e-03, 9.967306416511662e-03, 2.151523149181729e-02, 3.135594054041439e-02, 3.106676431413005e-02, 1.305182346703847e-02, -2.365612914173255e-02, -6.961110873399148e-02, -1.064086042746723e-01, -1.139718144697020e-01, -8.070816804859979e-02, -1.125476596869346e-02, 7.291826882034491e-02, 1.413481438338137e-01, 1.676264676180753e-01, 1.413481438338137e-01, 7.291826882034491e-02, -1.125476596869345e-02, -8.070816804859980e-02, -1.139718144697020e-01, -1.064086042746724e-01, -6.961110873399151e-02, -2.365612914173255e-02, 1.305182346703847e-02, 3.106676431413005e-02, 3.135594054041441e-02, 2.151523149181730e-02, 9.967306416511661e-03, 1.719837367951320e-03, -2.488356498115625e-03, -4.274276021174761e-03};

Filter f_bandpass(32, NULL, f_bpfaud_32_b);

// [b, a] = butter(6, .32)
double f_lpf_quarter_a[] {1.000000000000000e+00, -2.140755924193053e+00, 2.500582566075432e+00, -1.685599607428541e+00, 6.975629209793702e-01, -1.617798751801715e-01, 1.643942872818916e-02};
double f_lpf_quarter_b[] {3.538273577831657e-03, 2.122964146698994e-02, 5.307410366747485e-02, 7.076547155663314e-02, 5.307410366747485e-02, 2.122964146698994e-02, 3.538273577831657e-03};

// b=fir2(64, [0.0, 1.85/freq, 2.1/freq, 3.0/freq, 3.25/freq, 1], [0, 0, 1, 1, 0, 0])

double f_lpf_quarter64_2ch_b[] {-6.378418695449696e-04, -6.865695191419821e-05, 4.771641580941544e-04, 8.451488830495845e-04, 9.010530003969349e-04, 6.236273046937000e-04, 1.964267562559569e-04, -6.134522846292778e-06, 3.928052991381848e-04, 1.457568379454407e-03, 2.678442041466711e-03, 2.994170549401783e-03, 1.229663303236383e-03, -3.151966642431959e-03, -9.336359757760298e-03, -1.495121648384806e-02, -1.669405389830028e-02, -1.174112860392878e-02, 5.797730154887880e-04, 1.767058487149051e-02, 3.384510053359726e-02, 4.207095802523704e-02, 3.679883106055227e-02, 1.676592624947535e-02, -1.354391544736211e-02, -4.469653698017552e-02, -6.536823024181375e-02, -6.664578519521241e-02, -4.585747822572043e-02, -8.251916687134743e-03, 3.437176990156273e-02, 6.773296893777304e-02, 8.031907515092329e-02, 6.773296893777304e-02, 3.437176990156273e-02, -8.251916687134745e-03, -4.585747822572043e-02, -6.664578519521243e-02, -6.536823024181375e-02, -4.469653698017552e-02, -1.354391544736211e-02, 1.676592624947535e-02, 3.679883106055226e-02, 4.207095802523705e-02, 3.384510053359728e-02, 1.767058487149051e-02, 5.797730154887895e-04, -1.174112860392879e-02, -1.669405389830029e-02, -1.495121648384807e-02, -9.336359757760298e-03, -3.151966642431960e-03, 1.229663303236383e-03, 2.994170549401782e-03, 2.678442041466714e-03, 1.457568379454407e-03, 3.928052991381851e-04, -6.134522846293424e-06, 1.964267562559574e-04, 6.236273046937000e-04, 9.010530003969354e-04, 8.451488830495845e-04, 4.771641580941547e-04, -6.865695191419721e-05, -6.378418695449696e-04}; 


double f_leftaudio_64_2fsc_b[] {1.009004356629935e-04, -3.873860604215851e-04, 1.691498224276943e-04, 3.338997271048287e-05, 1.701096232917530e-04, -2.432560495076417e-04, -6.269838775924242e-04, 1.697071384178128e-03, -6.495571476183425e-04, -2.924774224643013e-03, 4.789701555456593e-03, -1.464445675808394e-04, -8.120210963311215e-03, 9.136710433747837e-03, 2.923549637234024e-03, -1.681994539269498e-02, 1.315146534045153e-02, 1.022024275392471e-02, -2.816198474310274e-02, 1.434204234728808e-02, 2.231515689718438e-02, -3.961255463755695e-02, 1.038157013812677e-02, 3.786933100720142e-02, -4.765871949133768e-02, 3.927157384897606e-04, 5.363772112384513e-02, -4.918767933901359e-02, -1.425014764736776e-02, 6.545920248526164e-02, -4.291384227001158e-02, -3.011470193718555e-02, 6.985126842151992e-02, -3.011470193718555e-02, -4.291384227001158e-02, 6.545920248526164e-02, -1.425014764736776e-02, -4.918767933901359e-02, 5.363772112384512e-02, 3.927157384897600e-04, -4.765871949133769e-02, 3.786933100720143e-02, 1.038157013812677e-02, -3.961255463755696e-02, 2.231515689718439e-02, 1.434204234728808e-02, -2.816198474310275e-02, 1.022024275392471e-02, 1.315146534045153e-02, -1.681994539269500e-02, 2.923549637234026e-03, 9.136710433747842e-03, -8.120210963311215e-03, -1.464445675808396e-04, 4.789701555456597e-03, -2.924774224643012e-03, -6.495571476183428e-04, 1.697071384178130e-03, -6.269838775924243e-04, -2.432560495076416e-04, 1.701096232917533e-04, 3.338997271048271e-05, 1.691498224276943e-04, -3.873860604215849e-04, 1.009004356629935e-04};


//Filter f_quarter(6, f_lpf_quarter_a, f_lpf_quarter_b);
Filter f_quarter(64, NULL, f_lpf_quarter64_2ch_b);
Filter f_left(64, NULL, f_leftaudio_64_2fsc_b);

// [b, a] = butter(3, .05/(freq/4));
double f_lpf01_2fsc_a[] {1.000000000000000e+00, -2.912241901643419e+00, 2.828292351114106e+00, -9.159695351108759e-01};
double f_lpf01_2fsc_b[] {1.011429497640438e-05, 3.034288492921315e-05, 3.034288492921315e-05, 1.011429497640438e-05};

Filter f_lpf01(3, f_lpf01_2fsc_a, f_lpf01_2fsc_b);

//double f_lpf01_2fsc_a[] {1.000000000000000e+00, -2.912241901643419e+00, 2.828292351114106e+00, -9.159695351108759e-01};
//double f_lpf01_2fsc_b[] {1.011429497640438e-05, 3.034288492921315e-05, 3.034288492921315e-05, 1.011429497640438e-05};

//Filter f_lpf01(3, f_lpf01_2fsc_a, f_lpf01_2fsc_b);

//double f_lpf01_2fsc_b[] {2.239736109519457e-03, 2.306968635482532e-03, 2.498299811328071e-03, 2.812706736982004e-03, 3.247918530712125e-03, 3.800434395293336e-03, 4.465554416280051e-03, 5.237422816321554e-03, 6.109083257173393e-03, 7.072545652725587e-03, 8.118863833379703e-03, 9.238223285800790e-03, 1.042003808371613e-02, 1.165305602621700e-02, 1.292547091103182e-02, 1.422504079245975e-02, 1.553921100794433e-02, 1.685524070435937e-02, 1.816033155556718e-02, 1.944175733714332e-02, 2.068699301264223e-02, 2.188384198855174e-02, 2.302056021214384e-02, 2.408597581761258e-02, 2.506960307088019e-02, 2.596174942178517e-02, 2.675361454342825e-02, 2.743738032149537e-02, 2.800629085051970e-02, 2.845472159828571e-02, 2.877823701280743e-02, 2.897363596731682e-02, 2.903898456618686e-02, 2.897363596731682e-02, 2.877823701280743e-02, 2.845472159828571e-02, 2.800629085051970e-02, 2.743738032149537e-02, 2.675361454342825e-02, 2.596174942178517e-02, 2.506960307088020e-02, 2.408597581761258e-02, 2.302056021214384e-02, 2.188384198855174e-02, 2.068699301264224e-02, 1.944175733714332e-02, 1.816033155556719e-02, 1.685524070435937e-02, 1.553921100794433e-02, 1.422504079245976e-02, 1.292547091103182e-02, 1.165305602621700e-02, 1.042003808371613e-02, 9.238223285800793e-03, 8.118863833379708e-03, 7.072545652725584e-03, 6.109083257173395e-03, 5.237422816321559e-03, 4.465554416280051e-03, 3.800434395293337e-03, 3.247918530712129e-03, 2.812706736982004e-03, 2.498299811328072e-03, 2.306968635482532e-03, 2.239736109519457e-03};
//Filter f_lpf01(64, NULL, f_lpf01_2fsc_b);

// [b, a] = butter(8, .05/(freq/4)); freqz(b, a)
double f_bw_butter8_a[] {1.000000000000000e+00, -7.775067326231071e+00, 2.645069259842671e+01, -5.142591273705536e+01, 6.249662457557615e+01, -4.861386304351296e+01, 2.363699401111408e+01, -6.568017814173656e+00, 7.985497358684126e-01};
double f_bw_butter8_b[] {4.806230409482173e-14, 3.844984327585739e-13, 1.345744514655009e-12, 2.691489029310017e-12, 3.364361286637521e-12, 2.691489029310017e-12, 1.345744514655009e-12, 3.844984327585739e-13, 4.806230409482173e-14};

Filter f_bw_butter8(8, f_bw_butter8_a, f_bw_butter8_b);

//double f_half_b_32[] {-7.824131153672732e-05, -1.886690961620114e-03, 1.124869615005853e-04, 3.860727739407968e-03, -2.100103216227518e-04, -8.239972541815445e-03, 3.559643443760880e-04, 1.594429034476104e-02, -5.281288528729093e-04, -2.867436125800037e-02, 7.002933613697306e-04, 5.071849366419014e-02, -8.462473841230669e-04, -9.802069708133478e-02, 9.437707442452334e-04, 3.159651338326527e-01, 4.997663774408457e-01, 3.159651338326527e-01, 9.437707442452335e-04, -9.802069708133476e-02, -8.462473841230670e-04, 5.071849366419014e-02, 7.002933613697310e-04, -2.867436125800038e-02, -5.281288528729094e-04, 1.594429034476104e-02, 3.559643443760879e-04, -8.239972541815454e-03, -2.100103216227519e-04, 3.860727739407968e-03, 1.124869615005854e-04, -1.886690961620116e-03, -7.824131153672732e-05};
//Filter f_half_l(32, NULL, f_half_b_32);
//Filter f_half_r(32, NULL, f_half_b_32);

double f_half_b_16[] {-7.826708210150440e-05, -5.238783816352566e-03, 2.100794933236211e-04, 2.321108986025089e-02, -5.283028041851547e-04, -7.610962749200613e-02, 8.465261150466882e-04, 3.077217922643445e-01, 4.999309869233592e-01, 3.077217922643445e-01, 8.465261150466883e-04, -7.610962749200616e-02, -5.283028041851548e-04, 2.321108986025089e-02, 2.100794933236211e-04, -5.238783816352571e-03, -7.826708210150440e-05};
Filter f_half_l(16, NULL, f_half_b_16);
Filter f_half_r(16, NULL, f_half_b_16);

typedef vector<complex<double>> v_cossin;

const double PI_FLOAT = M_PIl;
const double PIBY2_FLOAT = (M_PIl/2.0);
// |error| < 0.005
double fast_atan2( double y, double x )
{
        if ( x == 0.0f )
        {
                if ( y > 0.0f ) return PIBY2_FLOAT;
                if ( y == 0.0f ) return 0.0f;
                return -PIBY2_FLOAT;
        }
        double atan;
        double z = y/x;
        if (  fabs( z ) < 1.0f  )
        {
                atan = z/(1.0f + 0.28f*z*z);
                if ( x < 0.0f )
                {
                        if ( y < 0.0f ) return atan - PI_FLOAT;
                        return atan + PI_FLOAT;
                }
        }
        else
        {
                atan = PIBY2_FLOAT - z/(z*z + 0.28f);
                if ( y < 0.0f ) return atan - PI_FLOAT;
        }
        return atan;
}


class FM_demod {
	protected:
		vector<Filter> f_q, f_i;
		Filter *f_pre, *f_post;

		vector<v_cossin> ldft;
		vector<double> avglevel;
	
		int linelen;

		int min_offset;

		vector<double> fb;
	public:
		FM_demod(int _linelen, vector<double> _fb, Filter *prefilt, vector<Filter *> filt, Filter *postfilt, double freq = CHZ) {
			int i = 0;
			linelen = _linelen;

			fb = _fb;

			for (double f : fb) {
				v_cossin tmpdft;
				double fmult = f / freq; 

				for (int i = 0; i < linelen; i++) {
					tmpdft.push_back(complex<double>(sin(i * 2.0 * M_PIl * fmult), cos(i * 2.0 * M_PIl * fmult))); 
				}	
				ldft.push_back(tmpdft);

				f_i.push_back(Filter(filt[i]));
				f_q.push_back(Filter(filt[i]));

				i++;
			}
	
			f_pre = prefilt ? new Filter(*prefilt) : NULL;
			f_post = postfilt ? new Filter(*postfilt) : NULL;

			avglevel.assign(_fb.size(), 30.0);

			min_offset = 128;
		}

		~FM_demod() {
			if (f_pre) free(f_pre);
			if (f_post) free(f_post);
		}

		vector<double> process(vector<double> in) 
		{
			vector<double> out;
			vector<double> phase(fb.size() + 1);
			vector<double> level(fb.size() + 1);
			double avg = 0, total = 0.0;

			if (in.size() < (size_t)linelen) return out;

			for (double n : in) avg += n / in.size();

			int i = 0;
			for (double n : in) {
				vector<double> angle(fb.size() + 1);
				double peak = 0, pf = 0.0;
				int npeak;
				int j = 0;

				n -= avg;
				total += fabs(n);
				if (f_pre) n = f_pre->feed(n);

				angle[j] = 0;

				//cerr << n << endl;
	
				for (double f: fb) {
					double fci = f_i[j].feed(n * ldft[j][i].real());
					double fcq = f_q[j].feed(-n * ldft[j][i].imag());
					double at2 = fast_atan2(fci, fcq);	
	
//					cerr << fci << ' ' << fcq << endl;

					level[j] = ctor(fci, fcq);
	
					angle[j] = at2 - phase[j];
					if (angle[j] > M_PIl) angle[j] -= (2 * M_PIl);
					else if (angle[j] < -M_PIl) angle[j] += (2 * M_PIl);

					if (level[j] > peak) {
						npeak = j;
						peak = level[j];
						pf = f + ((f / 2.0) * angle[j]);
					}				
					phase[j] = at2;

//					cerr << f << ' ' << pf << ' ' << f + ((f / 2.0) * angle[j]) << ' ' << fci << ' ' << fcq << ' ' << ' ' << level[j] << ' ' << phase[j] << ' ' << peak << endl;

					j++;
				}

//				cerr << pf << endl;
	
				if (i > min_offset) out.push_back(pf);
				i++;
			}

//			cerr << total / in.size() << endl;
			return out;
		}
};

double time_inc = 1.0 / 15734.0;

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
	//double output[2048];
	unsigned char inbuf[2048];
	long long offset = 0;
	long long cur = 0;
	long long guide = 0;

	bool have_guide = false;

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	if (argc >= 2 && (strncmp(argv[1], "-", 1))) {
		fd = open(argv[1], O_RDONLY);
	}

	if (argc >= 3) {
		offset = atoll(argv[2]);
	}

	double gap;
	long long first = 0;

	if (argc >= 4) {
		if (!strcmp(argv[3], "-")) {
			have_guide = true;

			cin >> first >> gap;
			cerr << first << endl; 

			offset += first;
			cur = guide = first;
		} else if ((size_t)atoll(argv[3]) < dlen) {
			dlen = atoll(argv[3]); 
		}
	}
			
	if (offset) lseek64(fd, offset, SEEK_SET);

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
//	vector<double> fb({7600000, 8100000, 8300000, 8500000, 8700000, 8900000, 9100000, 9300000}); 
//	vector<double> fb({7600000, 8100000, 8600000, 9100000}); 
	vector<double> fb({2300000}); 
	//vector<double> fb({8500000}); 

	FM_demod left(512, {2200000, 2301136.0, 2400000}, NULL, {&f_lpf01, &f_lpf01, &f_lpf01}, NULL, CHZ/4.0);
	FM_demod right(512, {2710000, 2812499.0, 2910000}, NULL, {&f_lpf01, &f_lpf01, &f_lpf01}, NULL, CHZ/4.0);
//	FM_demod left(512, {2200000, 2400000}, NULL, {&f_lpf01, &f_lpf01, &f_lpf01}, NULL, CHZ/4.0);
//	FM_demod right(512, {2710000, 2910000}, NULL, {&f_lpf01, &f_lpf01, &f_lpf01}, NULL, CHZ/4.0);
//	FM_demod video(2048, fb, NULL, &f_lpf45, NULL);

	double t_n = 0.0;

	int x = 0;
	long long total = 0;	
	double pt = 1, t = 0;
	int zc_count = 0;
	double zc_dist = 0;

	double speed = 1.0;
	double ntime = 0;
	long long next = -1;

	double time1 = 0.0, time2 = 0.0;
	long long pt1 = -1, pt2 = first;

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;
		vector<unsigned short> ioutbuf;

		for (int j = 0; j < 2048; j++) {
			f_quarter.feed(inbuf[j]);
			if (!(j % 4)) dinbuf.push_back(f_quarter.val());
		}

		vector<double> outleft = left.process(dinbuf);
		vector<double> outright = right.process(dinbuf);

		vector<short> bout;
				
		t_n = 0;

		//cerr << 'L' << outline.size() << endl;
		for (int i = 0; i < outleft.size(); i++) {
			short output;
	
			cur += 4;	
			if (cur > pt2) {
//				cerr << "cur " << cur << " pt1 " << pt1 << " pt2 " << pt2 << endl;
				time1 = time2;
				time2 += time_inc;

				pt1 = pt2; 

				if (have_guide) {
					cin >> pt2 >> gap;
					if (pt2 == pt1) dlen = i; 
				} else {
					pt2 += 1820;
				}
//				cerr << "pt1 " << pt1 << " pt2 " << pt2 << " time1 " << time1 << " time2 " << time2 << endl;
			} 

			if ((next < 0) && (ntime < time2)) {
				double gap = pt2 - pt1; 
			
				if (ntime < time1) {
					cerr << "GLITCH:  next time is invalid " << ntime << ' ' << time1 << endl;
					ntime = time1;	
				}

				next = pt1 + (((ntime - time1) / time_inc) * gap); 
//				cerr << "ntime " << ntime << " next " << next << " off " << next - first << endl;
			}

			total++;
//			cerr << "cur " << cur << " next " << next << endl;

			if ((next > 0) && (cur > next)) {
				double n = outleft[i];
				n -= 2301136.0;
				n /= (150000.0);
				if (n < -1) n = -1;
				if (n > 1) n = 1;
				output = n * 32760;
				output = f_half_l.feed(output);
				if (!(total % 2)) bout.push_back(output);
				
				n = outright[i];
				n -= 2812499.0;
				n /= (150000.0);
				if (n < -1) n = -1;
				if (n > 1) n = 1;
				output = n * 32760;
				output = f_half_r.feed(output);
				if (!(total % 2)) bout.push_back(output);

				next = -1;
				ntime += (1.0 / 96000.0);
			}
		}
		
		short *boutput = bout.data();
		int len = outleft.size();
//		cerr << len << endl;
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}

		len *= 4;	
		i += (len >= 2048) ? 2048 : len;
		memmove(inbuf, &inbuf[len], 2048 - len);
		rv = read(fd, &inbuf[(2048 - len)], len) + (2048 - len);
		
		if (rv < 2048) return 0;
		//cerr << i << ' ' << rv << endl;
	}
	return 0;
}

