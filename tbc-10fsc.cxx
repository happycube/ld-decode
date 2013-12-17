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

const double f35_1_3mhz_b37[] {-1.234967629730642e-03, -1.185466683134518e-03, -1.168034466004734e-03, -1.018179088134394e-03, -5.140864556073300e-04, 5.984847487321350e-04, 2.573596558144000e-03, 5.628653493395202e-03, 9.908630728154117e-03, 1.545574882129113e-02, 2.218888007617535e-02, 2.989593966974851e-02, 3.824102397754865e-02, 4.678629045338454e-02, 5.502674991770788e-02, 6.243449677938711e-02, 6.850765013626178e-02, 7.281858582758209e-02, 7.505600313509912e-02, 7.505600313509912e-02, 7.281858582758211e-02, 6.850765013626180e-02, 6.243449677938712e-02, 5.502674991770790e-02, 4.678629045338454e-02, 3.824102397754866e-02, 2.989593966974851e-02, 2.218888007617536e-02, 1.545574882129114e-02, 9.908630728154115e-03, 5.628653493395204e-03, 2.573596558144003e-03, 5.984847487321354e-04, -5.140864556073300e-04, -1.018179088134393e-03, -1.168034466004735e-03, -1.185466683134518e-03, -1.234967629730642e-03};

const double f35_0_6mhz_b81[] {-5.557093857983986e-04, -5.386061875052753e-04, -5.304121793359423e-04, -5.263776829954182e-04, -5.203068760237518e-04, -5.046571743032663e-04, -4.706854629670484e-04, -4.086385760416698e-04, -3.079841041580603e-04, -1.576763716088336e-04, 5.354869496762519e-05, 3.368570506749334e-04, 7.029863985426006e-04, 1.161911045570856e-03, 1.722510709077681e-03, 2.392252347477940e-03, 3.176893957593510e-03, 4.080218902859782e-03, 5.103808720191829e-03, 6.246861511330179e-03, 7.506061977108642e-03, 8.875507926065949e-03, 1.034669671316860e-02, 1.190857357553547e-02, 1.354764226882133e-02, 1.524813681159704e-02, 1.699225155821051e-02, 1.876042528588617e-02, 2.053167354082170e-02, 2.228396218014330e-02, 2.399461390784434e-02, 2.564073866497750e-02, 2.719967802389246e-02, 2.864945327371738e-02, 2.996920668350137e-02, 3.113962549740770e-02, 3.214333855280412e-02, 3.296527600953923e-02, 3.359298352257743e-02, 3.401688325927180e-02, 3.423047542955864e-02, 3.423047542955864e-02, 3.401688325927180e-02, 3.359298352257743e-02, 3.296527600953923e-02, 3.214333855280413e-02, 3.113962549740771e-02, 2.996920668350136e-02, 2.864945327371738e-02, 2.719967802389247e-02, 2.564073866497751e-02, 2.399461390784434e-02, 2.228396218014329e-02, 2.053167354082171e-02, 1.876042528588618e-02, 1.699225155821050e-02, 1.524813681159704e-02, 1.354764226882133e-02, 1.190857357553548e-02, 1.034669671316860e-02, 8.875507926065951e-03, 7.506061977108645e-03, 6.246861511330181e-03, 5.103808720191825e-03, 4.080218902859783e-03, 3.176893957593512e-03, 2.392252347477942e-03, 1.722510709077683e-03, 1.161911045570855e-03, 7.029863985426009e-04, 3.368570506749333e-04, 5.354869496762523e-05, -1.576763716088337e-04, -3.079841041580605e-04, -4.086385760416702e-04, -4.706854629670486e-04, -5.046571743032660e-04, -5.203068760237521e-04, -5.263776829954183e-04, -5.304121793359425e-04, -5.386061875052753e-04, -5.557093857983986e-04};

const double f_hsync8[] {1.447786467971050e-02, 4.395811440315845e-02, 1.202636955256379e-01, 2.024216184054497e-01, 2.377574139720867e-01, 2.024216184054497e-01, 1.202636955256379e-01, 4.395811440315847e-02, 1.447786467971050e-02};

// todo?:  move into object

const int low = 7400000, high=9800000, bd = 300000;
const int nbands = ((high + 1 - low) / bd);

double fbin[nbands];

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

		double _sin[40], _cos[40];

		vector<double> prev, buf_1h;
		double circbuf[32];

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

		TBC(double _freq = 10.0) {
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
					
			buf_1h.resize(2275);
			prev.resize(40);
	
			for (int e = 0; e < 10; e++) {
				_cos[e] = cos(phase + (2.0 * M_PIl * ((double)e / freq)));
				_sin[e] = sin(phase + (2.0 * M_PIl * ((double)e / freq)));
			}

			f_i = new Filter(37, NULL, f35_1_3mhz_b37);
			f_q = new Filter(37, NULL, f35_1_3mhz_b37);
			
			f_synci = new Filter(81, NULL, f35_0_6mhz_b81);
			f_syncq = new Filter(81, NULL, f35_0_6mhz_b81);
		
			f_linelen = new Filter(8, NULL, f_hsync8);
			for (int i = 0; i < 9; i++) f_linelen->feed(2275);
		}

		bool expectsync() {
			if (insync || (cfline <= 0)) return true;
			if (lastsync > 2100) return true; 
			if ((cfline >= 250) && (lastsync > 1062) && (lastsync < 1200)) return true; 

			return false;
		}

		void feed(double in) {
			double dn = (double) in / 62000.0;
			bool exp_sync = expectsync();	

			if (!dn || ((dn < 0.1) && !exp_sync)) {
				dn = buf_1h[counter % 2275]; 
				if ((dn < 0.1) && !exp_sync) {
					dn = 0.101;	
				}
			}

			buf_1h[counter % 2275] = dn;
			prev[counter % 40] = dn;

			counter++;
			if (lastsync >= 0) lastsync++;

//			cerr << insync << ' ' << lastsync << endl;

			int count = 0;
			if (insync == false) {
				for (int i = 0; exp_sync && i < 40; i++) {
					if (prev[i] < 0.1) {
						count++;
					}
				}
				if (exp_sync && count >= 40) {
					if ((igap > 1062) && (igap < 1200)) {
						f_linelen->feed(igap * 2.0);
						cfline = 0;
					} else {
						if ((igap > 2200) && (igap < 2350)) f_linelen->feed(igap);
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

				while (igap > 3500) igap -= 2275;

				if ((igap > 2175) && (igap < 2370) && lastsync == 310) {
					fc = peaksyncq;
					fci = peaksynci;
					level = peaksync;
					if ((level > .02) && (level < .20)) {
						double padj = atan2(fci, ctor(fc, fci));

						if (fc > 0) {
							if (igap > 2275) 
								padj = (M_PIl / 2.0) - padj; 
							else {
								padj = -(M_PIl / 2.0) - padj; 
							}
						}

						phase -= (padj * sqrt(2.0));
						phased = true;
						phase_count = counter;

						for (int e = 0; e < 10; e++) {
							_cos[e] = cos(phase + (2.0 * M_PIl * ((double)e / freq)));
							_sin[e] = sin(phase + (2.0 * M_PIl * ((double)e / freq)));
						}

						pix_poffset = phase / M_PIl * 4.0;
						poffset += (igap - 2275);	

						if (tbc == TBC_HSYNC) {
							adjfreq = 2275.0 / f_linelen->val();
						} else {
							adjfreq = 2275.0 / (2275 + (padj * (M_PIl / 1.5)));
						}
					}

					cerr << counter << " level " << level << " q " << fc << " i " << fci << " phase " << atan2(fci, ctor(fc, fci)) << " adjfreq " << adjfreq << ' ' << igap << ':' << f_linelen->val() << ' ' << poffset - pix_poffset << endl ;
				}
			} else {
				for (int i = 0; i < 40; i++) {
					if (prev[i] > 0.2) count++;
				}
				if (count >= 20) {
					insync = false;
					prev.clear();
					fc = fci = 0;
				}
			}

			if ((lastsync > 125) && (lastsync < 310)) { 
				double q = f_syncq->feed(dn * _cos[counter % 10]);
				double i = f_synci->feed(-dn * _sin[counter % 10]);

				double synclev = ctor(i, q);

				if (synclev > peaksync) {
					peaksynci = i;
					peaksyncq = q;
					peaksync = synclev;
				}
			}

			// Automatically jump to the next line on HSYNC failure
			if (lastsync == (2275 + 320)) {
				lastsync -= 2275;
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
		Resample(int _prebuf = 2275) {
			cval = cloc = 0;
			prebuf = _prebuf;
			factor = 1.0;
		}

		void setscale(double _n) {factor = _n;}

		void feed(double n) {
			delaybuf.push(n);

			if (delaybuf.size() >= 2275) {
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
		
	if (argc >= 3) {
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
			//cerr << "write error\n";
			exit(0);
		}
		outbuf.clear();
	}
	return 0;
}

