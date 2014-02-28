/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

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
				if (order == 13) {
					double t[4];
		
					// Cycling through destinations reduces pipeline stalls.	
					t[0] = b[0] * x[0];
					t[1] = b[1] * x[1];
					t[2] = b[2] * x[2];
					t[3] = b[3] * x[3];
					t[0] += b[4] * x[4];
					t[1] += b[5] * x[5];
					t[2] += b[6] * x[6];
					t[3] += b[7] * x[7];
					t[0] += b[8] * x[8];
					t[1] += b[9] * x[9];
					t[2] += b[10] * x[10];
					t[3] += b[11] * x[11];
					y0 = t[0] + t[1] + t[2] + t[3] + (b[12] * x[12]);
				} else for (int o = 0; o < order; o++) {
					y0 += b[o] * x[o];
				}
			}

			y[0] = y0;
			return y[0];
		}
		double val() {return y[0];}
};

// b = fir2(8, [0, 3.0/freq, 3.5/freq, 4.0/freq, 5/freq, 7/freq, 9/freq, 11/freq, 13/freq, 1], [0.0, 0.0, 0.5, 1.0, 1.2, 1.6, 2.0, 2.4, 2.6, 2.6] 
//const double f_boost6_b[] {-4.033954487174667e-03, -3.408583476980324e-02, -5.031202829325306e-01, 1.454592400360107e+00, -5.031202829325309e-01, -3.408583476980324e-02, -4.033954487174666e-03};
//const double f_boost8_b[] {1.990859784029516e-03, -1.466569224478291e-02, -3.522213674516057e-02, -6.922384231866260e-01, 1.669825180053711e+00, -6.922384231866261e-01, -3.522213674516058e-02, -1.466569224478292e-02, 1.990859784029516e-03};


// b = fir2(12, [0 .18 .22 .5 1], [0 0 1 2 3], 'hamming'); freqz(b)
const double f_boost12_b[] {2.963585204586335e-03, 8.021303205163649e-04, -8.167321049713539e-04, -5.586785422763135e-02, -1.209392722622762e-01, -6.272452360792947e-01, 1.689996991838728e+00, -6.272452360792948e-01, -1.209392722622763e-01, -5.586785422763134e-02, -8.167321049713538e-04, 8.021303205163657e-04, 2.963585204586334e-03};

const double f_boost16_b[] {3.023991564221081e-03, 4.233186409767337e-03, 7.954665760931824e-03, 2.061366484849445e-03, -1.422694634466230e-03, -7.408019315126677e-02, -1.359026202658482e-01, -6.450343643150648e-01, 1.689996991838728e+00, -6.450343643150648e-01, -1.359026202658483e-01, -7.408019315126678e-02, -1.422694634466230e-03, 2.061366484849445e-03, 7.954665760931824e-03, 4.233186409767340e-03, 3.023991564221081e-03};

//const double f_boost16_b[] {-0.0050930113529 , -0.00686822662698 , -0.00168241501333 , -0.00705635391054 , -0.0687556532642 , -0.13429140818 , -0.0399158340449 , 0.216750729476 , 0.363913859251 , 0.216750729476 , -0.0399158340449 , -0.13429140818 , -0.0687556532642 , -0.00705635391054 , -0.00168241501333 , -0.00686822662698 , -0.0050930113529 };

const double f_afilt12_b[] {3.922718601230534e-03, 5.509003626732362e-03, -1.667423239655722e-03, -4.181643575364793e-02, -1.214946615984729e-01, -2.070707760267587e-01, 7.555600946599786e-01, -2.070707760267588e-01, -1.214946615984730e-01, -4.181643575364795e-02, -1.667423239655722e-03, 5.509003626732367e-03, 3.922718601230534e-03};

//const double f_boost8_b[] {8.188360043288829e-04, -1.959020553078470e-02, -6.802011723017314e-02, -4.157977388307656e-01, 1.209527775037999e+00, -4.157977388307657e-01, -6.802011723017315e-02, -1.959020553078471e-02, 8.188360043288829e-04};

const double f_boost8_b[] {-1.252993897181109e-03, -1.811981140446628e-02, -8.500709379119413e-02, -1.844252402264797e-01, 7.660358082164418e-01, -1.844252402264797e-01, -8.500709379119414e-02, -1.811981140446629e-02, -1.252993897181109e-03};

const double f_lpf525_12_hamming_b[] {2.416267218983970e-03, -4.599440255094788e-03, -2.435276138108525e-02, -1.709969522380537e-02, 9.102385774622326e-02, 2.708622944399880e-01, 3.634989549095802e-01, 2.708622944399882e-01, 9.102385774622331e-02, -1.709969522380538e-02, -2.435276138108525e-02, -4.599440255094792e-03, 2.416267218983970e-03};

const double f_lpf49_8_b[] {-6.035564708478322e-03, -1.459747550010019e-03, 7.617213234063192e-02, 2.530939844348266e-01, 3.564583909660596e-01, 2.530939844348267e-01, 7.617213234063196e-02, -1.459747550010020e-03, -6.035564708478321e-03};

const double f_lpf45_8_b[] {9.550931633601412e-19, 1.601492907105197e-03, 6.040483227758160e-02, 2.483137482510164e-01, 3.793598531285934e-01, 2.483137482510165e-01, 6.040483227758162e-02, 1.601492907105199e-03, 9.550931633601412e-19};

const double f_lpf45_12_hamming_b[] {-1.560564704684075e-03, -8.799707436385511e-03, -1.757949972644727e-02, 1.072420923958327e-02, 1.127204763471358e-01, 2.482016652603697e-01, 3.125868420408562e-01, 2.482016652603697e-01, 1.127204763471359e-01, 1.072420923958327e-02, -1.757949972644727e-02, -8.799707436385517e-03, -1.560564704684075e-03  };

// freq = freq =4.0*(315.0/88.0)
// fir1(12, (4.2/freq), 'hamming');
const double f_lpf42_12_hamming_b[] {-2.968012952158944e-03, -8.970442103421515e-03, -1.254603780275414e-02, 2.162767371309263e-02, 1.184891740848597e-01, 2.378741316708058e-01, 2.929870267791529e-01, 2.378741316708059e-01, 1.184891740848597e-01, 2.162767371309263e-02, -1.254603780275414e-02, -8.970442103421522e-03, -2.968012952158944e-03}; 

const double f_lpf30_16_hamming_b[] {-2.764895502720406e-03, -5.220462214367938e-03, -8.137721102693703e-03, -3.120835066368537e-03, 2.151916440426718e-02, 7.057010452167467e-02, 1.339005076970342e-01, 1.883266182415400e-01, 2.098550380432692e-01, 1.883266182415399e-01, 1.339005076970343e-01, 7.057010452167471e-02, 2.151916440426718e-02, -3.120835066368536e-03, -8.137721102693705e-03, -5.220462214367943e-03, -2.764895502720406e-03};

const double f_lpf35_16_hamming_b[] {-5.182956535966573e-04, -4.174028437151462e-03, -1.126381254549101e-02, -1.456598548706209e-02, 3.510439201231994e-03, 5.671595743858979e-02, 1.370914830220347e-01, 2.119161192395519e-01, 2.425762464437853e-01, 2.119161192395519e-01, 1.370914830220347e-01, 5.671595743858982e-02, 3.510439201231995e-03, -1.456598548706209e-02, -1.126381254549101e-02, -4.174028437151466e-03, -5.182956535966573e-04};

const double f_lpf35_16_python_b[] {-0.000441330317833 , -0.00410580778703 , -0.0112866761199 , -0.0148376907459 , 0.00298625401005 , 0.0562463748607 , 0.137108704283 , 0.212569087382 , 0.243522168871 , 0.212569087382 , 0.137108704283 , 0.0562463748607 , 0.00298625401005 , -0.0148376907459 , -0.0112866761199 , -0.00410580778703 , -0.000441330317833};

const double f_lpf45_16_python_b[] {0.0031653903905 , 0.00306014145217 , -0.00398454468472 , -0.0224868006252 , -0.0309181593988 , 0.013503739459 , 0.12605232633 , 0.25518176899 , 0.312852276173 , 0.25518176899 , 0.12605232633 , 0.013503739459 , -0.0309181593988 , -0.0224868006252 , -0.00398454468472 , 0.00306014145217 , 0.0031653903905};

const double f_lpf55_16_python_b[] {-0.000723397637219 , 0.00433368634435 , 0.00931049560886 , -0.00571459940902 , -0.0426674090828 , -0.0349785521301 , 0.0915883051498 , 0.286887403184 , 0.383928135944 , 0.286887403184 , 0.0915883051498 , -0.0349785521301 , -0.0426674090828 , -0.00571459940902 , 0.00931049560886 , 0.00433368634435 , -0.000723397637219};

const double f_lpf40_16_hamming_b[] {2.072595013361582e-03, -8.346396795579358e-04, -9.749056644931597e-03, -2.173598335596238e-02, -1.492934693656081e-02, 3.741335236370385e-02, 1.348268127802617e-01, 2.344615998458949e-01, 2.769493332275816e-01, 2.344615998458949e-01, 1.348268127802617e-01, 3.741335236370387e-02, -1.492934693656081e-02, -2.173598335596238e-02, -9.749056644931598e-03, -8.346396795579367e-04, 2.072595013361582e-03};
//const double f_lpf40_16_hamming_b[] {+0.0009957268915790, -0.0031904586206958, -0.0132827104419253, -0.0202383155846346, +0.0037119767122397, +0.0791997228694475, +0.1863911336253358, +0.2664129245486536, +0.2664129245486536, +0.1863911336253359, +0.0791997228694475, +0.0037119767122397, -0.0202383155846346, -0.0132827104419253, -0.0031904586206958, +0.0009957268915790};
//const double f_lpf30_16_hamming_b[] {-0.0027232929766121, -0.0052314380584097, -0.0082818086836746, -0.0034742916052344, +0.0210461556331407, +0.0702617355565447, +0.1340510944780587, +0.1889847932062197, +0.2107341048999342, +0.1889847932062197, +0.1340510944780587, +0.0702617355565447, +0.0210461556331407, -0.0034742916052344, -0.0082818086836746, -0.0052314380584097, -0.0027232929766121 };

const double f_lpf40_8_b[] {5.010487312257435e-19, 4.533965882743306e-03, 6.918575012753858e-02, 2.454450712419436e-01, 3.616704254955491e-01, 2.454450712419436e-01, 6.918575012753861e-02, 4.533965882743313e-03, 5.010487312257435e-19};

const double f_lpf30_8_b[] {-8.776697132906939e-19, 1.039295235883352e-02, 8.350051647243457e-02, 2.395856771132667e-01, 3.330417081109302e-01, 2.395856771132668e-01, 8.350051647243462e-02, 1.039295235883353e-02, -8.776697132906937e-19 };

const double f_lpf13_8_b[] {1.511108761398408e-02, 4.481461214778652e-02, 1.207230841165654e-01, 2.014075783203990e-01, 2.358872756025299e-01, 2.014075783203991e-01, 1.207230841165654e-01, 4.481461214778654e-02, 1.511108761398408e-02};

const double f_lpf06_8_b[] {-3.968132946649921e-18, 1.937504813888935e-02, 1.005269160761195e-01, 2.306204207693455e-01, 2.989552300312914e-01, 2.306204207693455e-01, 1.005269160761196e-01, 1.937504813888937e-02, -3.968132946649921e-18};

// allpass(16, 0, 4500000, .18, 28636363)
const double f_allpass_32_a[] {1.000000000000000e+00, -4.661913380623261e+00, 1.064710585646689e+01, -1.586434405195780e+01, 1.732760974789974e+01, -1.477833292685084e+01, 1.023735345653153e+01, -5.915510605579856e+00, 2.905871482191667e+00, -1.230567627146483e+00, 4.539790471091109e-01, -1.470684389054119e-01, 4.208842895460067e-02, -1.068797172802007e-02, 2.415921342991526e-03, -4.870790014993134e-04, 8.767422026987641e-05, -1.408965327232657e-05, 2.019564936217143e-06, -2.576737932141534e-07, 2.917239117680707e-08, -2.917651156698731e-09, 2.562406646490355e-10, -1.960487056801784e-11, 1.293078301449386e-12, -7.250455560811260e-14, 3.391158222648691e-15, -1.288268167152384e-16, 3.821507774727634e-18, -8.309773947720257e-20, 1.178872530133606e-21, -8.193088729422592e-24};
const double f_allpass_32_b[] {-8.193088729422592e-24, 1.178872530133606e-21, -8.309773947720258e-20, 3.821507774727635e-18, -1.288268167152384e-16, 3.391158222648691e-15, -7.250455560811263e-14, 1.293078301449386e-12, -1.960487056801785e-11, 2.562406646490355e-10, -2.917651156698731e-09, 2.917239117680706e-08, -2.576737932141534e-07, 2.019564936217142e-06, -1.408965327232657e-05, 8.767422026987638e-05, -4.870790014993133e-04, 2.415921342991524e-03, -1.068797172802007e-02, 4.208842895460066e-02, -1.470684389054119e-01, 4.539790471091108e-01, -1.230567627146483e+00, 2.905871482191666e+00, -5.915510605579854e+00, 1.023735345653153e+01, -1.477833292685084e+01, 1.732760974789974e+01, -1.586434405195780e+01, 1.064710585646689e+01, -4.661913380623261e+00, 1.000000000000000e+00};

// [n, Wc] = buttord((4.2 / freq), (5.0 / freq), 3, 20); [b, a] = butter(n, Wc)
const double f_lpf42b_6_a[] {1.000000000000000e+00, -1.725766598897363e+00, 1.442154506105485e+00, -5.692339148539284e-01, 9.129202080332011e-02};
const double f_lpf42b_6_b[] {1.490287582234461e-02, 5.961150328937842e-02, 8.941725493406763e-02, 5.961150328937842e-02, 1.490287582234461e-02};

const double f_lpf42b_3_a[] {1.000000000000000e+00, -1.302684590787800e+00, 7.909829879855602e-01, -1.641975612274331e-01};
const double f_lpf42b_3_b[] {4.051260449629090e-02, 1.215378134888727e-01, 1.215378134888727e-01, 4.051260449629090e-02  };
 

//Filter f_lpf525(32, NULL, f_lpf525_32_hamming_b);	
Filter f_lpf525(12, NULL, f_lpf525_12_hamming_b);	
Filter f_lpf49(8, NULL, f_lpf49_8_b);
Filter f_lpf45(8, NULL, f_lpf45_8_b);
Filter f_lpf40(8, NULL, f_lpf40_8_b);
Filter f_lpf45_12(12, NULL, f_lpf45_12_hamming_b);
Filter f_lpf42_12(12, NULL, f_lpf42_12_hamming_b);
Filter f_lpf42b_12(3, f_lpf42b_3_a, f_lpf42b_3_b);
Filter f_lpf40_16(16, NULL, f_lpf45_16_python_b);
Filter f_lpf30(8, NULL, f_lpf30_8_b);
Filter f_lpf13(8, NULL, f_lpf13_8_b);
Filter f_lpf06(8, NULL, f_lpf06_8_b);

Filter f_allpass(31, f_allpass_32_a, f_allpass_32_b);

// From http://lists.apple.com/archives/perfoptimization-dev/2005/Jan/msg00051.html.  Used w/o permission, but will replace when
// going integer... probably!
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


typedef vector<complex<double>> v_cossin;

class FM_demod {
	protected:
		double ilf;
		vector<Filter> f_q, f_i;
		Filter *f_pre, *f_post;

		vector<v_cossin> ldft;
		double avglevel[40];

		double cbuf[9];
	
		int linelen;

		int min_offset;

		double deemp;

		vector<double> fb;
	public:
		FM_demod(int _linelen, vector<double> _fb, Filter *prefilt, vector<Filter *> filt, Filter *postfilt) {
			int i = 0;
			linelen = _linelen;

			fb = _fb;

			ilf = 8600000;
			deemp = 0;

			for (double f : fb) {
				v_cossin tmpdft;
				double fmult = f / CHZ; 

				for (int i = 0; i < linelen; i++) {
					tmpdft.push_back(complex<double>(sin(i * 2.0 * M_PIl * fmult), cos(i * 2.0 * M_PIl * fmult))); 
					// cerr << sin(i * 2.0 * M_PIl * fmult) << ' ' << cos(i * 2.0 * M_PIl * fmult) << endl;
				}	
				ldft.push_back(tmpdft);

				f_i.push_back(Filter(filt[i]));
				f_q.push_back(Filter(filt[i]));

				i++;
			}
	
			f_pre = prefilt ? new Filter(*prefilt) : NULL;
			f_post = postfilt ? new Filter(*postfilt) : NULL;

			for (int i = 0; i < 40; i++) avglevel[i] = 30;
			for (int i = 0; i < 9; i++) cbuf[i] = 8100000;

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
			
			for (int i = 0; i < 9; i++) cbuf[i] = 8100000;

			if (in.size() < (size_t)linelen) return out;

			for (double n : in) avg += n / in.size();
			//cerr << avg << endl;

			int i = 0;
			for (double n : in) {
				vector<double> angle(fb.size() + 1);
				double peak = 500000, pf = 0.0;
				int npeak;
				int j = 0;

			//	n -= avg;
				total += fabs(n);
				if (f_pre) n = f_pre->feed(n);

				angle[j] = 0;

//				cerr << i << ' ';
	
				for (double f: fb) {
					double fci = f_i[j].feed(n * ldft[j][i].real());
					double fcq = f_q[j].feed(-n * ldft[j][i].imag());
					double at2 = fast_atan2(fci, fcq);	
	
//					cerr << n << ' ' << fci << ' ' << fcq << ' ' ;

					level[j] = ctor(fci, fcq);
	
					angle[j] = at2 - phase[j];
					if (angle[j] > M_PIl) angle[j] -= (2 * M_PIl);
					else if (angle[j] < -M_PIl) angle[j] += (2 * M_PIl);
					
//					cerr << at2 << ' ' << angle[j] << ' '; 
				//	cerr << angle[j] << ' ';
						
					if (fabs(angle[j]) < fabs(peak)) {
						npeak = j;
						peak = angle[j];
						pf = f + ((f / 2.0) * angle[j]);
					}
//					cerr << pf << endl;
					phase[j] = at2;

				//	cerr << f << ' ' << pf << ' ' << f + ((f / 2.0) * angle[j]) << ' ' << fci << ' ' << fcq << ' ' << ' ' << level[j] << ' ' << phase[j] << ' ' << peak << endl;

					j++;
				}
	
				double thisout = pf;	
//				cerr << pf << endl;

				if (f_post) thisout = f_post->feed(pf);	
				if (i > min_offset) {
					int bin = (thisout - 7600000) / 200000;
					if (1 || bin < 0) bin = 0;

					avglevel[bin] *= 0.9;
					avglevel[bin] += level[npeak] * .1;

//					if (fabs(shift) > 50000) thisout += shift;
//					cerr << ' ' << thisout << endl ;
//					out.push_back(((level[npeak] / avglevel[bin]) * 1200000) + 7600000); 
//					out.push_back((-(level[npeak] - 30) * (1500000.0 / 10.0)) + 9300000); 
					out.push_back(((level[npeak] / avglevel[bin]) > 0.3) ? thisout : 0);
//					out.push_back(thisout);
				};
				i++;
			}

//			cerr << total / in.size() << endl;
			return out;
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1;
	//double output[2048];
	unsigned char inbuf[2048];

	cerr << std::setprecision(10);
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
		if ((size_t)atoll(argv[3]) < dlen) {
			dlen = atoll(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
	Filter f_boost16(16, NULL, f_boost16_b);

	//FM_demod video(2048, {7600000, 8100000, 8400000, 8700000, 9000000, 9300000}, NULL /*&f_boost16*/, {&f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16}, NULL);

//	FM_demod video(2048, {8700000}, &f_boost16, {&f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16}, NULL);
	FM_demod video(2048, {8500000}, &f_boost16, {&f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16}, NULL);
//	FM_demod video(2048, {7600000, 8100000, 8400000, 8700000, 9000000, 9300000}, &f_boost16, {&f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16}, NULL);
//	FM_demod video(2048, {7600000, 8100000, 8700000, 9300000}, &f_boost16, {&f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16, &f_lpf40_16}, NULL);

	double charge = 0, prev = 8700000;

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;
		vector<unsigned short> ioutbuf;

		for (int j = 0; j < 2048; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);

		vector<unsigned short> bout;

		for (int i = 0; i < outline.size(); i++) {
			double n = outline[i];
			int in;

			if (n > 0) {
				charge += ((n - prev) * 1.0);
				prev = n;
				n -= (charge * 0.5);
				charge *= 0.9;

//				cerr << n << ' ';

				n -= 7600000.0;
				n /= (9300000.0 - 7600000.0);
				if (n < 0) n = 0;
				in = 1 + (n * 57344.0);
				if (in > 65535) in = 65535;
//				cerr << in << endl;
			} else {
				in = 0;
			}

			bout.push_back(in);
		}
		
		unsigned short *boutput = bout.data();
		int len = outline.size();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}

		i += (len > 1820) ? 1820 : len;
		memmove(inbuf, &inbuf[len], 2048 - len);
		rv = read(fd, &inbuf[(2048 - len)], len) + (2048 - len);
		
		if (rv < 2048) return 0;
		cerr << i << ' ' << rv << endl;
	}
	return 0;
}

