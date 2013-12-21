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

const int max_filter_order = 128 + 1;
class Filter {
	protected:
		int order;
		__declspec(align(32)) double b[max_filter_order];
		__declspec(align(32)) double x[max_filter_order];
		double y0;
	public:
		Filter(int _order, const double *_a, const double *_b) {
			order = _order + 1;
		
			memcpy(b, _b, sizeof(double) * (order + 1));

			y0 = 0;
	
			clear();
		}

		Filter(Filter *orig) {
			order = orig->order;
			memcpy(b, orig->b, sizeof(b));
				
			clear();
		}

		void clear(double val = 0) {
			for (int i = 0; i < order; i++) {
				x[i] = val;
			}
		}

		inline double feed(double val) {
			memmove(&x[1], x, sizeof(double) * (order - 1));
		
			x[0] = val;
			y0 = 0; // ((b[0] / a0) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			if (order == 17) {
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
				y0 += b[13] * x[13];
				y0 += b[14] * x[14];
				y0 += b[15] * x[15];
				y0 += b[16] * x[16];
			} else for (int o = 0; o < order; o++) {
				y0 += b[o] * x[o];
			}

			return y0;
		}
		double val() {return y0;}
};

// b = fir2(16, [0 .15 .2 .5 1], [0 0 1 1 1], 'hamming'); freqz(b)
const double f_afilt16_b[] {2.8319553800409043e-03, 3.2282450120912558e-03, 1.7173845888535961e-03, -8.6398254017342382e-03, -3.4194614714312573e-02, -7.5039936510398628e-02, -1.2219905386849417e-01, -1.6033026685193086e-01, 8.2499694824218750e-01, -1.6033026685193089e-01, -1.2219905386849413e-01, -7.5039936510398655e-02, -3.4194614714312579e-02, -8.6398254017342364e-03, 1.7173845888535965e-03, 3.2282450120912592e-03, 2.8319553800409043e-03};

const double f_boost16_b[] {3.123765469711817e-03, 2.997477562454424e-03, 3.750031772606975e-03, -6.673430389299294e-03, -1.357392588270026e-02, -8.285925814646711e-02, -1.301633550658124e-01, -6.195450317461929e-01, 1.724998474121094e+00, -6.195450317461930e-01, -1.301633550658124e-01, -8.285925814646714e-02, -1.357392588270026e-02, -6.673430389299293e-03, 3.750031772606975e-03, 2.997477562454426e-03, 3.123765469711817e-03};

// fir1(15, (4.0/freq), 'hamming');
const double f_lpf40_16_hamming_b[] {-2.028767853690441e-03, -5.146764387302929e-03, -9.901392487754552e-03, -8.028961431539007e-03, 1.455573714480611e-02, 6.572472577779680e-02, 1.357376803746136e-01, 1.977678364433565e-01, 2.226398128394282e-01, 1.977678364433565e-01, 1.357376803746136e-01, 6.572472577779684e-02, 1.455573714480611e-02, -8.028961431539007e-03, -9.901392487754554e-03, -5.146764387302935e-03, -2.028767853690441e-03};

// freq = freq =5.0*(315.0/88.0)

Filter f_lpf40(16, NULL, f_lpf40_16_hamming_b);

typedef vector<complex<double>> v_cossin;

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
	if ( fabs( z ) < 1.0f )
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

			// 16-order pre, 16-order ...
			min_offset = 48;
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

					double at2;

					at2 = fast_atan2(fci, fcq);	

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
					if (bin < 0) bin = 0;
					if (bin > 10) bin = 10;

					avglevel[bin] *= 0.9;
					avglevel[bin] += level[npeak] * .1;

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
	int rv = 0, fd = 0;
	size_t dlen = -1;
	//double output[2048];
	unsigned char inbuf[4096];

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
		if ((size_t)atoi(argv[3]) < dlen) {
			dlen = (size_t)atoi(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 4096);

	int i = 4096;
	
	Filter f_afilt16(16, NULL, f_afilt16_b);
	Filter f_boost16(16, NULL, f_boost16_b);

	FM_demod video(4096, {7600000, 8100000, 8400000, 8700000, 9000000, 9300000}, &f_boost16, {&f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40, &f_lpf40}, NULL);

	double deemp[10], orig[10];

	for (int i = 0; i < 10; i++) deemp[i] = 8300000;
	
	while ((rv == 4096) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;
		vector<unsigned short> ioutbuf;

		for (int j = 0; j < 4096; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);

		vector<unsigned short> bout;

		for (int i = 0; i < outline.size(); i++) {
			double n = outline[i];
			int in;

			if (n > 0) {
				int entry = i % 9;
				double diff = n - deemp[entry];

				orig[entry] = n;
	 			n -= (diff * (1.0/3.0));
				deemp[entry] = n;

				n -= 7600000.0;
				n /= (9300000.0 - 7600000.0);
				if (n < 0) n = 0;
				in = 1 + (n * 62000.0);
				if (in > 65535) in = 65535;
			} else {
				deemp[(i % 10)] = deemp[((i - 1) % 10)];
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

		i += len;
		memmove(inbuf, &inbuf[len], 4096 - len);
		rv = read(fd, &inbuf[(4096 - len)], len) + (4096 - len);
		
		if (rv < 4096) return 0;
		cerr << i << ' ' << rv << ' ' << outline.size() << endl;
	}
	return 0;
}

