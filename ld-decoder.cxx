/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <vector>
#include <complex>
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
//			delete [] x;
//			delete [] y;
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

// longer-duration .5mhz filter, used for sync

const double f_0_5mhz_b[] {2.8935325675960790e-03, 3.4577251216393609e-03, 4.7838244505790843e-03, 6.9572831696391620e-03, 1.0011907953112537e-02, 1.3924181711788889e-02, 1.8611409324653432e-02, 2.3933941132695716e-02, 2.9701434113594740e-02, 3.5682813848999163e-02, 4.1619323616848357e-02, 4.7239811465409724e-02, 5.2277230286682991e-02, 5.6485223640968835e-02, 5.9653649812310708e-02, 6.1621960508198896e-02, 6.2289494550564671e-02, 6.1621960508198896e-02, 5.9653649812310708e-02, 5.6485223640968821e-02, 5.2277230286682998e-02, 4.7239811465409724e-02, 4.1619323616848378e-02, 3.5682813848999170e-02, 2.9701434113594740e-02, 2.3933941132695712e-02, 1.8611409324653432e-02, 1.3924181711788901e-02, 1.0011907953112541e-02, 6.9572831696391620e-03, 4.7838244505790896e-03, 3.4577251216393622e-03, 2.8935325675960790e-03 };

// 4.2mhz filter
const double f_inband4_b[] {0.0208161638876772, 0.2314704348431369, 0.4954268025383716, 0.2314704348431369, 0.0208161638876772};

const double f_inband8_b[] {-3.5634174409531622e-03, 9.4654740832740107e-03, 9.1456278081537348e-02, 2.4141004764330087e-01, 3.2246323526568188e-01, 2.4141004764330090e-01, 9.1456278081537348e-02, 9.4654740832740124e-03, -3.5634174409531609e-03}; 

//const double f_inband7_b[] { 2.0639067636214502e-02, 6.5484287559733512e-02, 1.6641090209130313e-01, 2.4746574271274874e-01, 2.4746574271274879e-01, 1.6641090209130316e-01, 6.5484287559733539e-02, 2.0639067636214502e-02 }; 

const double f_inband7_b[] { -6.2211448918489030e-04, 2.8265367663495418e-02, 1.5675884606312396e-01, 3.1559790076256550e-01, 3.1559790076256550e-01, 1.5675884606312396e-01, 2.8265367663495432e-02, -6.2211448918488910e-04};

// 8-tap 3.5mhz high-pass fir1
const double f_hp8_b[] {-5.2233122995139940e-04, -1.7082609318519331e-02, -8.5929313061105295e-02, -1.9084603032392095e-01, 7.5704600929723254e-01, -1.9084603032392097e-01, -8.5929313061105309e-02, -1.7082609318519335e-02, -5.2233122995139940e-04};

const double f_butter4_a[] {1.0000000000000000, -1.6232715948812961, 1.3304266228523409, -0.5121023075052276, 0.0810552055606200};
const double f_butter4_b[] {0.0172567453766523, 0.0690269815066093, 0.1035404722599139, 0.0690269815066093, 0.0172567453766523};

const double f_butter6_a[] {1.0000000000000000, -2.4594002236413273, 3.0570327078873287, -2.1912939461291545, 0.9464602376928106, -0.2285198647947151, 0.0239658552682254};
const double f_butter6_b[] {0.0023163244731745, 0.0138979468390470, 0.0347448670976174, 0.0463264894634899, 0.0347448670976174, 0.0138979468390470, 0.0023163244731745};

const double f_butter8_a[] {1.0000000000000000, -3.2910431389188823, 5.4649816845801347, -5.5946268902911909, 3.8014233895293916, -1.7314645265989386, 0.5125138525205987, -0.0895781664897369, 0.0070486692595647};
const double f_butter8_b[] {0.0003095893499646, 0.0024767147997169, 0.0086685017990093, 0.0173370035980186, 0.0216712544975232, 0.0173370035980186, 0.0086685017990093, 0.0024767147997169, 0.0003095893499646};

//const double f_boost6_b[] {0.0171085311223133, 0.0066159866434093, -0.0287374093196349, -1.4956846203123810, 4.1364660365098924, -1.4956846203123810, -0.0287374093196349, 0.0066159866434093, 0.0171085311223133};
//const double f_boost6_b[] {0.0254170399264351, -0.0059024716440027, -0.0364988745431467, -1.8598195331511393, 4.9380431080332725, -1.8598195331511400, -0.0364988745431467, -0.0059024716440027, 0.0254170399264351};
// fir2(8, [0, 4/freq, 5/freq, 6/freq, 10/freq, 1], [1.0, 1.0, 2, 3, 4, 5])
const double f_boost6_b[] {0.0111989816340250, 0.0048865621882266, -0.0481490541009254, -0.8694087656392513, 2.8936261819359768, -0.8694087656392512, -0.0481490541009254, 0.0048865621882266, 0.0111989816340250};
//const double f_boost6_b[] {0.0168027211008027, 0.0022145267218688, 0.0416814439546960, -1.4449168967980353, 3.8620269283049078, -1.4449168967980355, 0.0416814439546960, 0.0022145267218688, 0.0168027211008027};

const double f_a[256] {1,};

const double zero = 7600000.0;
const double one = 9400000.0;
const double mfactor = 65536.0 / (one - zero);

const int linelen = 2048;

// todo?:  move into object

const int low = 7400000, high=9800000, bd = 300000;
const int nbands = ((high + 1 - low) / bd);

double fbin[nbands];

LDE lpf45(7, NULL, f_inband7_b);

struct FreqBand : public vector<double> {
	public:
		double flow, fhigh, gap;
		double fbase;

	//	FreqBand(double _fbase = CHZ, double _flow = 7500000, double _fhigh = 9600000, double _gap = 100000) {
		FreqBand(double _fbase = CHZ, double _flow = 7600000, double _fhigh = 9300000, double _gap = 250000) {
			flow = _flow;
			fhigh = _fhigh;
			gap = _gap;
			fbase = _fbase;
			
			int numbands = floor(((fhigh - flow) / gap) + 1);

			for (int i = 0; i < numbands; i++) push_back(flow + (gap * i));
		}
};

typedef vector<complex<double>> cossin;

class FM_demod {
	protected:
		vector<LDE> f_q, f_i;
		LDE *f_post;
		vector<cossin> ldft;
	
		int linelen;

		int min_offset;

		FreqBand fb;
	public:
		FM_demod(int _linelen, FreqBand _fb, int _filt_size, const double *filt_a, const double *filt_b, int pf_size, const double *pf_a, const double *pf_b) {
			linelen = _linelen;

			fb = _fb;

			for (double f : fb) {
				cossin tmpdft;
				double fmult = f / fb.fbase; 

				for (int i = 0; i < linelen; i++) {
					tmpdft.push_back(complex<double>(sin(i * 2.0 * M_PIl * fmult), cos(i * 2.0 * M_PIl * fmult))); 
				}	
				ldft.push_back(tmpdft);

				if (filt_a) {
					f_i.push_back(LDE(_filt_size, filt_a, filt_b));
					f_q.push_back(LDE(_filt_size, filt_a, filt_b));
				} else {
					f_i.push_back(LDE(_filt_size, NULL, filt_b));
					f_q.push_back(LDE(_filt_size, NULL, filt_b));
				}

				f_post = new LDE(pf_size, NULL, pf_b);

				min_offset = 9 + _filt_size + pf_size + 2;
			}	
		}

		vector<double> process(vector<double> in) 
		{
			vector<double> out;
			vector<double> phase(in.size());
			double avg = 0, total = 0.0;

			LDE boost(8, NULL, f_boost6_b);

			if (in.size() < (size_t)linelen) return out;

			for (double n : in) avg += n / in.size();

			int i = 0;
			for (double n : in) {
				double level[fb.size() + 1];
				double peak = 500000, pf = 0.0;
				int npeak;
				int j = 0;

				n -= avg;
				total += fabs(n);
				n = boost.feed(n);
	
//				auto c = ldft[j]->begin(); 
				for (double f: fb) {
//					cerr << j << ' ' << f << endl;
					double fci = f_i[j].feed(n * ldft[j][i].real());
					double fcq = f_q[j].feed(-n * ldft[j][i].imag());
			
					level[j] = atan2(fci, fcq) - phase[j]; 
					if (level[j] > M_PIl) level[j] -= (2 * M_PIl);
					else if (level[j] < -M_PIl) level[j] += (2 * M_PIl);
						
					if (fabs(level[j]) < peak) {
						npeak = j;
						peak = level[j];
						pf = f + ((f / 2.0) * level[j]);
					}
					phase[j] = atan2(fci, fcq);

//					cerr << f << ' ' << pf << ' ' << fci << ' ' << fcq << ' ' << level[j] << ' ' << phase[j] << ' ' << peak << endl;

					j++;
				}
	
				double thisout = pf;	
				thisout = f_post->feed(pf);	
				if (i > min_offset) out.push_back(thisout);
				i++;
			}
/*		
			double avgout = 0.0;	
			for (double n : out) {
				n = (n - zero) / (9400000.0 - 7600000.0);
				avgout += n / out.size();
			}
			
			double sdev = 0.0;	
			for (double n : out) {
				sdev += ((n - avgout) * (n - avgout));
			}
*/

			cerr << total / in.size() << endl;
			return out;
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
	//double output[2048];
	unsigned char inbuf[2048];
	FreqBand fb;

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
			dlen = atoi(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;

//	FM_demod video(2048, fb, 4, f_butter4_a, f_butter4_b, 7, NULL, f_inband7_b);
	FM_demod video(2048, fb, 6, f_butter6_a, f_butter6_b, 7, NULL, f_inband7_b);
//	FM_demod video(2048, fb, 8, f_butter8_a, f_butter8_b, 8, NULL, f_inband8_b);
//	FM_demod video(2048, fb, 8, NULL, f_inband8_b, 7, NULL, f_inband7_b);
//	FM_demod video(2048, fb, 4, NULL, f_inband4_b, 7, NULL, f_inband7_b);

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;

		for (int j = 0; j < 2048; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);
		double *output = outline.data();

		vector<unsigned short> bout;
		for (double n : outline) {
//			cerr << n << ' ' << endl;
			n -= 7600000.0;
			n /= (9300000.0 - 7600000.0);
			if (n < 0) n = 0;
			if (n > (65535.0 / 62000.0)) n = (65535.0 / 62000.0);
			bout.push_back(n * 62000.0);
		}

		unsigned short *boutput = bout.data();
		int len = outline.size();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}

/*
//		int rv = decode_line(inbuf, output);
		cerr << i << ' ' << rv << endl;

		int len = outline.size();

		if (write(1, output, sizeof(double) * outline.size()) != sizeof(double) * outline.size()) {
			//cerr << "write error\n";
			exit(0);
		}
*/
		i += len;
		memmove(inbuf, &inbuf[len], 2048 - len);
		rv = read(fd, &inbuf[(2048 - len)], len) + (2048 - len);
		
		if (rv < 2048) return 0;
		cerr << i << ' ' << rv << endl;
	}
	return 0;
}

