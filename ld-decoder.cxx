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
			for (int o = 0; o < order; o++) {
				y0 += ((b[o] / a0) * x[o]);
				if (isIIR && o) y0 -= ((a[o] / a0) * y[o]);
				//cerr << o << ' ' << x[o] << ' ' << y[o] << ' ' << a[o] << ' ' << b[o] << ' ' << (b[o] * x[o]) << ' ' << -(a[o] * y[o]) << ' ' << y[0] << endl;
			}

			y[0] = y0;
			return y[0];
		}
		double val() {return y[0];}
};

// b = fir2(8, [0, 3.0/freq, 3.5/freq, 4.0/freq, 5/freq, 7/freq, 9/freq, 11/freq, 13/freq, 1], [0.0, 0.0, 0.5, 1.0, 1.2, 1.6, 2.0, 2.4, 2.6, 2.6] 
//const double f_boost6_b[] {-4.033954487174667e-03, -3.408583476980324e-02, -5.031202829325306e-01, 1.454592400360107e+00, -5.031202829325309e-01, -3.408583476980324e-02, -4.033954487174666e-03};
//const double f_boost8_b[] {1.990859784029516e-03, -1.466569224478291e-02, -3.522213674516057e-02, -6.922384231866260e-01, 1.669825180053711e+00, -6.922384231866261e-01, -3.522213674516058e-02, -1.466569224478292e-02, 1.990859784029516e-03};
const double f_boost16_b[] {1.598977954996517e-04, 3.075456659938196e-03, 9.185596072285866e-03, 1.709531178223861e-02, 3.432562296816891e-03, -3.610562619607920e-02, -9.514006526914356e-02, -6.305237888418010e-01, 1.454592400360107e+00, -6.305237888418012e-01, -9.514006526914358e-02, -3.610562619607921e-02, 3.432562296816892e-03, 1.709531178223861e-02, 9.185596072285866e-03, 3.075456659938199e-03, 1.598977954996517e-04};

const double f_afilt12_b[] {3.922718601230534e-03, 5.509003626732362e-03, -1.667423239655722e-03, -4.181643575364793e-02, -1.214946615984729e-01, -2.070707760267587e-01, 7.555600946599786e-01, -2.070707760267588e-01, -1.214946615984730e-01, -4.181643575364795e-02, -1.667423239655722e-03, 5.509003626732367e-03, 3.922718601230534e-03};

//const double f_boost8_b[] {8.188360043288829e-04, -1.959020553078470e-02, -6.802011723017314e-02, -4.157977388307656e-01, 1.209527775037999e+00, -4.157977388307657e-01, -6.802011723017315e-02, -1.959020553078471e-02, 8.188360043288829e-04};

const double f_boost8_b[] {-1.252993897181109e-03, -1.811981140446628e-02, -8.500709379119413e-02, -1.844252402264797e-01, 7.660358082164418e-01, -1.844252402264797e-01, -8.500709379119414e-02, -1.811981140446629e-02, -1.252993897181109e-03};

const double f_lpf49_8_b[] {-6.035564708478322e-03, -1.459747550010019e-03, 7.617213234063192e-02, 2.530939844348266e-01, 3.564583909660596e-01, 2.530939844348267e-01, 7.617213234063196e-02, -1.459747550010020e-03, -6.035564708478321e-03};

const double f_lpf45_8_b[] {-4.889502734137763e-03, 4.595036240066151e-03, 8.519412674978986e-02, 2.466567238634809e-01, 3.368872317616017e-01, 2.466567238634810e-01, 8.519412674978988e-02, 4.595036240066152e-03, -4.889502734137763e-03};

const double f_lpf40_8_b[] {-2.502779651724930e-03, 1.269617303003584e-02, 9.521478723491596e-02, 2.378965425850819e-01, 3.133905536033823e-01, 2.378965425850820e-01, 9.521478723491597e-02, 1.269617303003585e-02, -2.502779651724931e-03};

const double f_lpf13_8_b[] {1.511108761398408e-02, 4.481461214778652e-02, 1.207230841165654e-01, 2.014075783203990e-01, 2.358872756025299e-01, 2.014075783203991e-01, 1.207230841165654e-01, 4.481461214778654e-02, 1.511108761398408e-02};

typedef vector<complex<double>> v_cossin;

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
		FM_demod(int _linelen, vector<double> _fb, Filter *prefilt, Filter *filt, Filter *postfilt) {
			linelen = _linelen;

			fb = _fb;

			for (double f : fb) {
				v_cossin tmpdft;
				double fmult = f / CHZ; 

				for (int i = 0; i < linelen; i++) {
					tmpdft.push_back(complex<double>(sin(i * 2.0 * M_PIl * fmult), cos(i * 2.0 * M_PIl * fmult))); 
				}	
				ldft.push_back(tmpdft);

				f_i.push_back(Filter(filt));
				f_q.push_back(Filter(filt));
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
					int bin = (npeak - 7600000) / 500000;
					avglevel[bin] *= 0.98;
					avglevel[bin] += level[npeak] * .02;

					//cerr << thisout << ' ' << avglevel[bin] << ' ' << level[npeak] << endl; 

					out.push_back(((level[npeak] / avglevel[bin]) > 0.4) ? thisout : 0);
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
	
	Filter f_boost8(8, NULL, f_boost8_b);
	Filter f_boost16(8, NULL, f_boost16_b);
	
	Filter f_afilt12(12, NULL, f_afilt12_b);

	Filter f_lpf49(8, NULL, f_lpf49_8_b);
	Filter f_lpf45(8, NULL, f_lpf45_8_b);
	Filter f_lpf40(8, NULL, f_lpf40_8_b);
	Filter f_lpf13(8, NULL, f_lpf13_8_b);

//	vector<double> fb({7600000, 8100000, 8300000, 8500000, 8700000, 8900000, 9100000, 9300000}); 
//	vector<double> fb({7600000, 8100000, 8600000, 9100000}); 
	vector<double> fb({8100000, 8700000, 9100000}); 
	//vector<double> fb({8500000}); 

	FM_demod video(2048, fb, &f_afilt12, &f_lpf45, NULL);
//	FM_demod video(2048, fb, NULL, &f_lpf45, NULL);
	
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
				n -= 7600000.0;
				n /= (9400000.0 - 7600000.0);
				if (n < 0) n = 0;
				in = 1 + (n * 62000.0);
				if (in > 65535) in = 65535;
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

