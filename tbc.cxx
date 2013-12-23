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
//const double CHZ = (1000000.0*(315.0/88.0)*8.0);
//const double FSC = (1000000.0*(315.0/88.0));

using namespace std;

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
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

// back-reason for selecting 30:  14.318/1.3*e = 29.939.  seems to work better than 31 ;) 
const double f28_1_3mhz_b30[] {4.914004914004915e-03, 5.531455998921954e-03, 7.356823678403171e-03, 1.031033062576930e-02, 1.426289441492169e-02, 1.904176904176904e-02, 2.443809475353342e-02, 3.021602622216704e-02, 3.612304011689930e-02, 4.190097158553291e-02, 4.729729729729729e-02, 5.207617192414463e-02, 5.602873571329703e-02, 5.898224266066317e-02, 6.080761034014438e-02, 6.142506142506142e-02, 6.080761034014438e-02, 5.898224266066317e-02, 5.602873571329704e-02, 5.207617192414465e-02, 4.729729729729731e-02, 4.190097158553292e-02, 3.612304011689932e-02, 3.021602622216705e-02, 2.443809475353343e-02, 1.904176904176904e-02, 1.426289441492169e-02, 1.031033062576930e-02, 7.356823678403167e-03, 5.531455998921954e-03, 4.914004914004915e-03};

const double f28_0_6mhz_b65[] {2.274019329164298e-03, 2.335061058268382e-03, 2.517616315402780e-03, 2.819980631318463e-03, 3.239330911865343e-03, 3.771751796461725e-03, 4.412272214761106e-03, 5.154911800196637e-03, 5.992736727052425e-03, 6.917924449726024e-03, 7.921836739729059e-03, 8.995100338499179e-03, 1.012769447298977e-02, 1.130904441692792e-02, 1.252812022418446e-02, 1.377353971240908e-02, 1.503367473540020e-02, 1.629675975197302e-02, 1.755100167764746e-02, 1.878468999350057e-02, 1.998630608412639e-02, 2.114463078384454e-02, 2.224884912702732e-02, 2.328865132451982e-02, 2.425432902336347e-02, 2.513686595107182e-02, 2.592802209813746e-02, 2.662041065278063e-02, 2.720756696962055e-02, 2.768400892832751e-02, 2.804528811870335e-02, 2.828803137428890e-02, 2.840997226671035e-02, 2.840997226671035e-02, 2.828803137428890e-02, 2.804528811870335e-02, 2.768400892832751e-02, 2.720756696962055e-02, 2.662041065278064e-02, 2.592802209813747e-02, 2.513686595107182e-02, 2.425432902336347e-02, 2.328865132451982e-02, 2.224884912702732e-02, 2.114463078384455e-02, 1.998630608412640e-02, 1.878468999350057e-02, 1.755100167764746e-02, 1.629675975197302e-02, 1.503367473540020e-02, 1.377353971240908e-02, 1.252812022418446e-02, 1.130904441692792e-02, 1.012769447298977e-02, 8.995100338499189e-03, 7.921836739729063e-03, 6.917924449726024e-03, 5.992736727052432e-03, 5.154911800196641e-03, 4.412272214761106e-03, 3.771751796461728e-03, 3.239330911865346e-03, 2.819980631318465e-03, 2.517616315402780e-03, 2.335061058268382e-03, 2.274019329164298e-03};

const double f_hsync8[] {1.447786467971050e-02, 4.395811440315845e-02, 1.202636955256379e-01, 2.024216184054497e-01, 2.377574139720867e-01, 2.024216184054497e-01, 1.202636955256379e-01, 4.395811440315847e-02, 1.447786467971050e-02};

inline double IRE(double in) 
{
	return (in * 140.0) - 40.0;
}

enum tbc_type {TBC_HSYNC, TBC_CBURST};

class TBC {
	protected:
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;
		Filter *f_post;

		Filter *f_linelen;

		double fc, fci;
		double freq;

		tbc_type tbc;

		int cfline;

		int field, fieldcount;

		int counter, lastsync;
		bool insync;
		double peaksync, peaksynci, peaksyncq;

		double _sin[32], _cos[32];

		vector<double> prev, buf_1h;
		double circbuf[18];

		double phase, level;
		int phase_count;
		bool phased;

		double adjfreq;

		double poffset, pix_poffset;

		vector<double> line;
	
		int igap;
	public:
		bool get_newphase(double &afreq, double &np) {
			if (phased) {
				afreq = adjfreq;
				np = phase;
				phased = false;
				return true;
			} else return false;
		}	

		void set_tbc(tbc_type type) {
			tbc = type;
		}

		TBC(double _freq = 8.0) {
			counter = 0;
			phased = insync = false;

			fieldcount = -10;
			field = -1;
			cfline = -1;

			pix_poffset = poffset = 0;
			adjfreq = 1.0;

			lastsync = -1;

			level = phase = 0.0;

			freq = _freq;

			igap = -1;
					
			buf_1h.resize(1820);
			prev.resize(32);
	
			for (int e = 0; e < 8; e++) {
				_cos[e] = cos(phase + (2.0 * M_PIl * ((double)e / freq)));
				_sin[e] = sin(phase + (2.0 * M_PIl * ((double)e / freq)));
			}

			f_i = new Filter(30, NULL, f28_1_3mhz_b30);
			f_q = new Filter(30, NULL, f28_1_3mhz_b30);
			
			f_synci = new Filter(65, NULL, f28_0_6mhz_b65);
			f_syncq = new Filter(65, NULL, f28_0_6mhz_b65);
		
			f_linelen = new Filter(8, NULL, f_hsync8);
			for (int i = 0; i < 9; i++) f_linelen->feed(1820);
		}

		bool expectsync() {
			if (insync || (cfline <= 0)) return true;
			if (lastsync > 1700) return true; 
			if ((cfline >= 250) && (lastsync > 850) && (lastsync < 980)) return true; 

			return false;
		}

		void feed(double in) {
			double dn = (double) in / 62000.0;
			bool exp_sync = expectsync();	

			if (!dn || ((dn < 0.1) && !exp_sync)) {
				dn = buf_1h[counter % 1820]; 
				if ((dn < 0.1) && !exp_sync) {
					dn = 0.101;	
				}
			}

			buf_1h[counter % 1820] = dn;
			prev[counter % 32] = dn;

			counter++;
			if (lastsync >= 0) lastsync++;

//			cerr << insync << ' ' << lastsync << endl;

			int count = 0;
			if (insync == false) {
				for (int i = 0; exp_sync && i < 32; i++) {
					if (prev[i] < 0.1) {
						count++;
					}
				}
				if (exp_sync && count >= 24) {
					if ((igap > 880) && (igap < 940)) {
						f_linelen->feed(igap * 2.0);
						cfline = 0;
					} else {
						if ((igap > 1800) && (igap < 1840)) f_linelen->feed(igap);
					}
					
					igap = lastsync;

					lastsync = 0;
					peaksynci = peaksyncq = peaksync = 0;

					cerr << cfline << " sync at " << counter - 24 << ' ' << igap << ' ' << insync << endl;
					insync = true;
					prev.clear();
					line.clear();
				}
					
				line.push_back(dn);

				while (igap > 3500) igap -= 1820;

				if ((igap > 1700) && (igap < 1900) && lastsync == 250) {
					fc = peaksyncq;
					fci = peaksynci;
					level = peaksync;
					if ((level > .02) && (level < .10)) {
						double padj = atan2(fci, ctor(fc, fci));

						if (fc > 0) {
							if (igap > 1820) 
								padj = (M_PIl / 2.0) - padj; 
							else {
								padj = -(M_PIl / 2.0) - padj; 
							}
						}

						phase -= (padj * sqrt(2.0));
						phased = true;
						phase_count = counter;

						for (int e = 0; e < 8; e++) {
							_cos[e] = cos(phase + (2.0 * M_PIl * ((double)e / freq)));
							_sin[e] = sin(phase + (2.0 * M_PIl * ((double)e / freq)));
						}

						pix_poffset = phase / M_PIl * 4.0;
						poffset += (igap - 1820);	

						if (tbc == TBC_HSYNC) {
							adjfreq = 1820.0 / f_linelen->val();
						} else {
							adjfreq = 1820.0 / (1820 + (padj * (M_PIl / 2.0)));
						}
					}

					cerr << counter << " level " << level << " q " << fc << " i " << fci << " phase " << atan2(fci, ctor(fc, fci)) << " adjfreq " << adjfreq << ' ' << igap << ':' << f_linelen->val() << ' ' << poffset - pix_poffset << endl ;
				}
			} else {
				for (int i = 0; i < 32; i++) {
					if (prev[i] > 0.2) count++;
				}
				if (count >= 16) {
					insync = false;
					prev.clear();
					fc = fci = 0;
				}
			}

			if ((lastsync > 100) && (lastsync < 250)) { 
				double q = f_syncq->feed(dn * _cos[counter % 8]);
				double i = f_synci->feed(-dn * _sin[counter % 8]);

				double synclev = ctor(i, q);

				if (synclev > peaksync) {
					peaksynci = i;
					peaksyncq = q;
					peaksync = synclev;
				}
			}

			// Automatically jump to the next line on HSYNC failure
			if (lastsync == (1820 + 260)) {
				lastsync -= 1820;
				cfline++;	
			}
		}
};

class Resample : public vector<double> {
	protected:
		int prebuf;

		double cval, cloc;
		double factor;

		queue<double> delaybuf;
	public:
		Resample(int _prebuf = 1820) {
			cval = cloc = 0;
			prebuf = _prebuf;
			factor = 1.0;
		}

		void setscale(double _n) {factor = _n;}

		void feed(double n) {
			delaybuf.push(n);

			if (delaybuf.size() >= 1820) {
				double len = factor;
				double newval = delaybuf.front();
				while (len > 0.0) {
					double avail = 1.0 - (cloc - floor(cloc));  
					if (avail > len) {
						cval += (len * newval) / factor; 
						cloc += len;
						len = 0.0;
					} else {
						cval += (avail * newval);
						//cerr << "V " << cloc << ' ' << newval << ' ' << cval << endl;
						push_back(cval);
						cval = 0;					
						cloc += avail;
						len -= avail;
					} 
				}
				delaybuf.pop();
			} 
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
	//double output[2048];
	unsigned short inbuf[2048];

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

	vector<unsigned short> outbuf;	

	int ntsc_passes = 2;
	vector<TBC *> tbc;
	vector<Resample *> delaybuf;

	for (int i = 0; i < ntsc_passes - 1; i++) {
		tbc.push_back(new TBC());
		delaybuf.push_back(new Resample());
	} 
	tbc.push_back(new TBC());
	delaybuf.push_back(new Resample());

	tbc[0]->set_tbc(TBC_HSYNC);
	tbc[1]->set_tbc(TBC_CBURST);

	int count = 0;
	double nextfreq = 1.0000, nextphase = 0.0;
		
	while ((rv > 0) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;

		for (int i = 0; i < (rv / 2); i++) {
			int in = inbuf[i];

			count++;
			tbc[0]->feed(in);
			delaybuf[0]->feed(in);

			for (int j = 0; j < ntsc_passes; j++) { 
				if (tbc[j]->get_newphase(nextfreq, nextphase)) {
					cerr << "newscale " << j << " " << nextfreq << endl;
					delaybuf[j]->setscale(nextfreq);		
//					nextfreq = 1.0;
				}

				if (!j) {
					for (double v: *delaybuf[j]) {
						tbc[1]->feed(v);
						delaybuf[1]->feed(v);
					}
					delaybuf[0]->clear();
				}
			}
				
			for (double v: *delaybuf[1]) {
				if (v < 0) v = 0;
				if (v > 65535) v = 65535;
				outbuf.push_back((unsigned short)v);
			}
			delaybuf[1]->clear();
		}
		
		i += rv;
		if (i % 2) inbuf[0] = inbuf[rv];
		rv = read(fd, &inbuf[i % 2], 2048 - (i % 2));

		unsigned short *boutput = outbuf.data();
		if (write(1, boutput, outbuf.size() * 2) != outbuf.size() * 2) {
			exit(0);
		}
		outbuf.clear();
	}
	return 0;
}

