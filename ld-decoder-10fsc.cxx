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
const double CHZ = (1000000.0*(315.0/88.0)*10.0);

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
					y0 += b[0] * x[0];
					y0 += b[1] * x[1];
					y0 += b[2] * x[2];
					y0 += b[3] * x[3];
					y0 += b[4] * x[4];
					y0 += b[5] * x[5];
					y0 += b[6] * x[6];
					y0 += b[7] * x[7];
					y0 += b[8] * x[8];
					y0 += b[9] * x[9];
					y0 += b[10] * x[10];
					y0 += b[11] * x[11];
					y0 += b[12] * x[12];
				} else for (int o = 0; o < order; o++) {
					y0 += b[o] * x[o];
				}
			}

			y[0] = y0;
			return y[0];
		}
		double val() {return y[0];}
};

// b = fir2(16, [0 .15 .2 .5 1], [0 0 1 1 1], 'hamming'); freqz(b)
const double f_afilt16_b[] {2.8319553800409043e-03, 3.2282450120912558e-03, 1.7173845888535961e-03, -8.6398254017342382e-03, -3.4194614714312573e-02, -7.5039936510398628e-02, -1.2219905386849417e-01, -1.6033026685193086e-01, 8.2499694824218750e-01, -1.6033026685193089e-01, -1.2219905386849413e-01, -7.5039936510398655e-02, -3.4194614714312579e-02, -8.6398254017342364e-03, 1.7173845888535965e-03, 3.2282450120912592e-03, 2.8319553800409043e-03};

const double f_boost16_b[] {3.123765469711817e-03, 2.997477562454424e-03, 3.750031772606975e-03, -6.673430389299294e-03, -1.357392588270026e-02, -8.285925814646711e-02, -1.301633550658124e-01, -6.195450317461929e-01, 1.724998474121094e+00, -6.195450317461930e-01, -1.301633550658124e-01, -8.285925814646714e-02, -1.357392588270026e-02, -6.673430389299293e-03, 3.750031772606975e-03, 2.997477562454426e-03, 3.123765469711817e-03};

// fir1(15, (4.0/freq), 'hamming');
const double f_lpf40_15_hamming_b[] {-2.946846406369798e-03, -5.818304239908221e-03, -8.744902449172498e-03, -1.174167602472263e-04, 3.446404677343186e-02, 9.712591957457362e-02, 1.688365234767659e-01, 2.172009800309264e-01, 2.172009800309265e-01, 1.688365234767659e-01, 9.712591957457366e-02, 3.446404677343189e-02, -1.174167602472263e-04, -8.744902449172497e-03, -5.818304239908217e-03, -2.946846406369798e-03};

const double f_lpf40_32_hamming_b[] {-1.5652363638468312e-03, -1.6478881564047881e-03, -9.2742743690339626e-04, 1.2777474036302190e-03, 4.9093082118189680e-03, 8.1341641447971388e-03, 7.5421180415871049e-03, 1.3228248202934751e-04, -1.3715675929761275e-02, -2.8224201974851419e-02, -3.3068670365790559e-02, -1.7577386171408627e-02, 2.3359994514177564e-02, 8.4806879207920474e-02, 1.5161797160788967e-01, 2.0345139860864575e-01, 2.2298924435294154e-01, 2.0345139860864575e-01, 1.5161797160788965e-01, 8.4806879207920460e-02, 2.3359994514177564e-02, -1.7577386171408627e-02, -3.3068670365790580e-02, -2.8224201974851423e-02, -1.3715675929761277e-02, 1.3228248202934624e-04, 7.5421180415871049e-03, 8.1341641447971475e-03, 4.9093082118189697e-03, 1.2777474036302192e-03, -9.2742743690339712e-04, -1.6478881564047894e-03, -1.5652363638468312e-03};

// freq = freq =5.0*(315.0/88.0)

// [n, Wc] = buttord((4.5 / freq), (6 / freq), 3, 15); [b, a] = butter(n, Wc)
const double f_lpf_6_a[] {1.0000000000000000e+00, -2.9603188604519133e+00, 4.0945616955978696e+00, -3.2164775768368816e+00, 1.4931150232709849e+00, -3.8399487942244304e-01, 4.2481926938480144e-02};
const double f_lpf_6_b[] {1.0838645171265180e-03, 6.5031871027591073e-03, 1.6257967756897768e-02, 2.1677290342530360e-02, 1.6257967756897768e-02, 6.5031871027591073e-03, 1.0838645171265180e-03};
 

//Filter f_lpf525(32, NULL, f_lpf525_32_hamming_b);	
//Filter f_lpf40(32, NULL, f_lpf40_32_hamming_b);
Filter f_lpf40(15, NULL, f_lpf40_15_hamming_b);

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

			int i = 0;
			for (double n : in) {
				vector<double> angle(fb.size() + 1);
				double peak = 500000, pf = 0.0;
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
					double at2 = atan2(fci, fcq);	
	
//					cerr << fci << ' ' << fcq << endl;

					level[j] = ctor(fci, fcq);
	
					angle[j] = at2 - phase[j];
					if (angle[j] > M_PIl) angle[j] -= (2 * M_PIl);
					else if (angle[j] < -M_PIl) angle[j] += (2 * M_PIl);
						
					if (fabs(angle[j]) < fabs(peak)) {
						npeak = j;
						peak = angle[j];
						pf = f + ((f / 2.0) * angle[j]);
					}
					phase[j] = at2;

//					cerr << f << ' ' << pf << ' ' << f + ((f / 2.0) * angle[j]) << ' ' << fci << ' ' << fcq << ' ' << ' ' << level[j] << ' ' << phase[j] << ' ' << peak << endl;

					j++;
				}
	
				double thisout = pf;	

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
//					out.push_back(((level[npeak] / avglevel[bin]) > 0.3) ? thisout : 0);
					out.push_back(thisout);
				};
				i++;
			}

//			cerr << total / in.size() << endl;
			return out;
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
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
		
	if (argc >= 3) {
		if ((size_t)atoi(argv[3]) < dlen) {
			dlen = atoi(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
	Filter f_afilt16(16, NULL, f_afilt16_b);
	Filter f_boost16(16, NULL, f_boost16_b);

//	vector<double> fb({7600000, 8100000, 8300000, 8500000, 8700000, 8900000, 9100000, 9300000}); 
//	vector<double> fb({7600000, 8100000, 8600000, 9100000}); 
	vector<double> fb({7600000, 8100000, 8700000, 9100000}); 
	//vector<double> fb({8500000}); 

	FM_demod video(2048, {7600000, 8100000, 8400000, 8700000, 9000000, 9300000, 9600000}, &f_boost16, {&f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40}, NULL);

	double deemp[10], orig[10];

	for (int i = 0; i < 10; i++) deemp[i] = 8300000;
	
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
				int entry = i % 9;
				double diff = n - deemp[entry];

//				cerr << n << ' ' << diff << ' ' << (n - 9300000) / diff << ' ' << (n - 8100000) / diff;
				orig[entry] = n;
	 			n -= (diff * .3);
///	 			n -= (diff * .4);
//	 			n -= (diff * (fabs(diff) / 4800000));
				deemp[entry] = n;
//				cerr << ' ' << n << endl;

				n -= 7600000.0;
				n /= (9300000.0 - 7600000.0);
				if (n < 0) n = 0;
				in = 1 + (n * 62000.0);
				if (in > 65535) in = 65535;
			} else {
				deemp[(i % 7)] = deemp[((i - 1) % 7)];
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

