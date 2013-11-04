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

// [n, Wc] = buttord(4.0 / freq, 3.5 / freq, 6, 12); [b, a] = butter(n, Wc)
const double f_butter6_a[] {1.000000000000000e+00, -2.352249761025037e+00, 2.861013965944460e+00, -2.009740195346082e+00, 8.553145693150709e-01, -2.037566682488971e-01, 2.113751308567020e-02};
const double f_butter6_b[] {2.683115995706020e-03, 1.609869597423612e-02, 4.024673993559030e-02, 5.366231991412039e-02, 4.024673993559030e-02, 1.609869597423612e-02, 2.683115995706020e-03};  

const double f_butter8_a[] {1.000000000000000e+00, -7.999995183466980e+00, 2.799996628428046e+01, -5.599989885287620e+01, 6.999983142151834e+01, -5.599983142157634e+01, 2.799989885298059e+01, -7.999966284338464e+00, 9.999951834785804e-01};
const double f_butter8_b[] {2.374220925679126e-51, 1.899376740543300e-50, 6.647818591901551e-50, 1.329563718380310e-49, 1.661954647975388e-49, 1.329563718380310e-49, 6.647818591901551e-50, 1.899376740543300e-50, 2.374220925679126e-51}; 

// fir2(8, [0, 4/freq, 5/freq, 6/freq, 10/freq, 1], [1.0, 1.0, 2, 3, 4, 5])
//const double f_boost6_b[] {0.0111989816340250, 0.0048865621882266, -0.0481490541009254, -0.8694087656392513, 2.8936261819359768, -0.8694087656392512, -0.0481490541009254, 0.0048865621882266, 0.0111989816340250};
// fir2(8, [0, 3.0/freq, 3.5/freq, 5/freq, 6/freq, 10/freq, 1], [0.0, 0.0, 1.0, 2, 3, 4, 5]) 
//const double f_boost8_b[] {8.226231487511369e-03, -1.760999224010931e-02, -1.354044946940760e-01, -1.040291091550781e+00, 2.684106353139590e+00, -1.040291091550782e+00, -1.354044946940761e-01, -1.760999224010932e-02, 8.226231487511367e-03};
// b = fir2(8, [0, 3.0/freq, 3.5/freq, 4.0/freq, 5/freq, 7/freq, 9/freq, 11/freq, 13/freq, 1], [0.0, 0.0, 0.5, 1.0, 1.2, 1.6, 2.0, 2.4, 2.6, 2.6] 
const double f_boost6_b[] {-4.033954487174667e-03, -3.408583476980324e-02, -5.031202829325306e-01, 1.454592400360107e+00, -5.031202829325309e-01, -3.408583476980324e-02, -4.033954487174666e-03};
const double f_boost8_b[] {1.990859784029516e-03, -1.466569224478291e-02, -3.522213674516057e-02, -6.922384231866260e-01, 1.669825180053711e+00, -6.922384231866261e-01, -3.522213674516058e-02, -1.466569224478292e-02, 1.990859784029516e-03};
const double f_boost16_b[] {1.598977954996517e-04, 3.075456659938196e-03, 9.185596072285866e-03, 1.709531178223861e-02, 3.432562296816891e-03, -3.610562619607920e-02, -9.514006526914356e-02, -6.305237888418010e-01, 1.454592400360107e+00, -6.305237888418012e-01, -9.514006526914358e-02, -3.610562619607921e-02, 3.432562296816892e-03, 1.709531178223861e-02, 9.185596072285866e-03, 3.075456659938199e-03, 1.598977954996517e-04};

// back-reason for selecting 30:  14.318/1.3*e = 29.939.  seems to work better than 31 ;) 
const double f28_1_3mhz_b30[] {4.914004914004915e-03, 5.531455998921954e-03, 7.356823678403171e-03, 1.031033062576930e-02, 1.426289441492169e-02, 1.904176904176904e-02, 2.443809475353342e-02, 3.021602622216704e-02, 3.612304011689930e-02, 4.190097158553291e-02, 4.729729729729729e-02, 5.207617192414463e-02, 5.602873571329703e-02, 5.898224266066317e-02, 6.080761034014438e-02, 6.142506142506142e-02, 6.080761034014438e-02, 5.898224266066317e-02, 5.602873571329704e-02, 5.207617192414465e-02, 4.729729729729731e-02, 4.190097158553292e-02, 3.612304011689932e-02, 3.021602622216705e-02, 2.443809475353343e-02, 1.904176904176904e-02, 1.426289441492169e-02, 1.031033062576930e-02, 7.356823678403167e-03, 5.531455998921954e-03, 4.914004914004915e-03};

const double f28_0_6mhz_b65[] {2.274019329164298e-03, 2.335061058268382e-03, 2.517616315402780e-03, 2.819980631318463e-03, 3.239330911865343e-03, 3.771751796461725e-03, 4.412272214761106e-03, 5.154911800196637e-03, 5.992736727052425e-03, 6.917924449726024e-03, 7.921836739729059e-03, 8.995100338499179e-03, 1.012769447298977e-02, 1.130904441692792e-02, 1.252812022418446e-02, 1.377353971240908e-02, 1.503367473540020e-02, 1.629675975197302e-02, 1.755100167764746e-02, 1.878468999350057e-02, 1.998630608412639e-02, 2.114463078384454e-02, 2.224884912702732e-02, 2.328865132451982e-02, 2.425432902336347e-02, 2.513686595107182e-02, 2.592802209813746e-02, 2.662041065278063e-02, 2.720756696962055e-02, 2.768400892832751e-02, 2.804528811870335e-02, 2.828803137428890e-02, 2.840997226671035e-02, 2.840997226671035e-02, 2.828803137428890e-02, 2.804528811870335e-02, 2.768400892832751e-02, 2.720756696962055e-02, 2.662041065278064e-02, 2.592802209813747e-02, 2.513686595107182e-02, 2.425432902336347e-02, 2.328865132451982e-02, 2.224884912702732e-02, 2.114463078384455e-02, 1.998630608412640e-02, 1.878468999350057e-02, 1.755100167764746e-02, 1.629675975197302e-02, 1.503367473540020e-02, 1.377353971240908e-02, 1.252812022418446e-02, 1.130904441692792e-02, 1.012769447298977e-02, 8.995100338499189e-03, 7.921836739729063e-03, 6.917924449726024e-03, 5.992736727052432e-03, 5.154911800196641e-03, 4.412272214761106e-03, 3.771751796461728e-03, 3.239330911865346e-03, 2.819980631318465e-03, 2.517616315402780e-03, 2.335061058268382e-03, 2.274019329164298e-03};

const double f_lpf048_b4_b[] {5.164738337291061e-10, 2.065895334916424e-09, 3.098843002374636e-09, 2.065895334916424e-09, 5.164738337291061e-10};
const double f_lpf048_b4_a[] {1.000000000000000e+00, -3.975007767097551e+00, 5.925335133687553e+00, -3.925644691784699e+00, 9.753173334582784e-01};

const double f_lpf30_b7_a[] {1.000000000000000e+00, -1.001752925667820e+01, 4.818012448934698e+01, -1.474362068100452e+02, 3.209452996998522e+02, -5.266697808887541e+02, 6.738478922002332e+02, -6.859158541504489e+02, 5.618723553981042e+02, -3.722260094293712e+02, 1.992906245125886e+02, -8.569286834120848e+01, 2.921444510991529e+01, -7.727318853556639e+00, 1.530726275923486e+00, -2.139064948453619e-01, 1.882054672323584e-02, -7.847626261975797e-04};
const double f_lpf30_b7_b[] {2.231228112437725e-10, 3.793087791144133e-09, 3.034470232915306e-08, 1.517235116457653e-07, 5.310322907601786e-07, 1.380683955976464e-06, 2.761367911952929e-06, 4.339292433068888e-06, 5.424115541336110e-06, 5.424115541336110e-06, 4.339292433068888e-06, 2.761367911952929e-06, 1.380683955976464e-06, 5.310322907601786e-07, 1.517235116457653e-07, 3.034470232915306e-08, 3.793087791144133e-09, 2.231228112437725e-10};

const double f_hp35_14_b[] {2.920242503210705e-03, 6.624873097752306e-03, 1.019323615024227e-02, -2.860428785028677e-03, -5.117884625321341e-02, -1.317695333943684e-01, -2.108392223608709e-01, 7.582009982420270e-01, -2.108392223608709e-01, -1.317695333943685e-01, -5.117884625321342e-02, -2.860428785028680e-03, 1.019323615024228e-02, 6.624873097752300e-03, 2.920242503210705e-03};

const double f_lpf49_8_b[] {-6.035564708478322e-03, -1.459747550010019e-03, 7.617213234063192e-02, 2.530939844348266e-01, 3.564583909660596e-01, 2.530939844348267e-01, 7.617213234063196e-02, -1.459747550010020e-03, -6.035564708478321e-03};

const double f_lpf45_8_b[] {-4.889502734137763e-03, 4.595036240066151e-03, 8.519412674978986e-02, 2.466567238634809e-01, 3.368872317616017e-01, 2.466567238634810e-01, 8.519412674978988e-02, 4.595036240066152e-03, -4.889502734137763e-03};

const double f_lpf13_8_b[] {1.511108761398408e-02, 4.481461214778652e-02, 1.207230841165654e-01, 2.014075783203990e-01, 2.358872756025299e-01, 2.014075783203991e-01, 1.207230841165654e-01, 4.481461214778654e-02, 1.511108761398408e-02};

const double f_hsync8[] {1.447786467971050e-02, 4.395811440315845e-02, 1.202636955256379e-01, 2.024216184054497e-01, 2.377574139720867e-01, 2.024216184054497e-01, 1.202636955256379e-01, 4.395811440315847e-02, 1.447786467971050e-02};

// todo?:  move into object

const int low = 7400000, high=9800000, bd = 300000;
const int nbands = ((high + 1 - low) / bd);

double fbin[nbands];

inline double IRE(double in) 
{
	return (in * 140.0) - 40.0;
}

struct YIQ {
	double y, i, q;

	YIQ(double _y = 0.0, double _i = 0.0, double _q = 0.0) {
		y = _y; i = _i; q = _q;
	};
};

double clamp(double v, double low, double high)
{
	if (v < low) return low;
	else if (v > high) return high;
	else return v;
}

struct RGB {
	double r, g, b;

	void conv(YIQ y) { 
	//	y.i = clamp(y.i, -0.5957, .5957);
	//	y.q = clamp(y.q, -0.5226, .5226);

		y.y -= (.4 / 1.4);
		y.y *= 1.4; 
		y.y = clamp(y.y, 0, 1.0);

		r = (y.y * 1.164) + (1.596 * y.i);
		g = (y.y * 1.164) - (0.813 * y.i) - (y.q * 0.391);
		b = (y.y * 1.164) + (y.q * 2.018);

		r = clamp(r, 0, 1.05);
		g = clamp(g, 0, 1.05);
		b = clamp(b, 0, 1.05);
		//cerr << 'y' << y.y << " i" << y.i << " q" << y.q << ' ';
		//cerr << 'r' << r << " g" << g << " b" << b << endl;
	};
};

// NewCode

/* 
 * NTSC(/PAL) Description 
 * ----------------
 *
 * There are a few different types of NTSC lines with different contained data.  While PAL is similar, I 
 * am currently only concerned with NTSC.  Perhaps I will wind up with PAL video tapes someday... 
 *
 * Since many of these lines are repeated, we will describe these lines and then generate the typical frame.
 */

// These are bit fields, since data type can be added to a core type
enum LineFeatures {
	// Core line types
	LINE_NORMAL       = 0x01, /* standard line - Porch, sync pulse, porch, color burst, porch, data */ 
	LINE_EQUALIZATION = 0x02, /* -SYNC, half line, -SYNC, half line */ 
	LINE_FIELDSYNC    = 0x04, /* Long -SYNC, serration pulse std sync pulse len */ 
	LINE_HALF         = 0x08, /* Half-length video line at end of odd field, followed by -SYNC at 262.5 */ 
	// Line data features
	LINE_VIDEO	  = 0x0040, /* What we actually care about - picture data! */
	LINE_MULTIBURST   = 0x0080, /* White, 0.5-4.1mhz burst pulses */
	LINE_COMPTEST     = 0x0100, /* 3.58mhz bursts, short pulses, white */
	LINE_REFSIGNAL    = 0x0200, /* Burst, grey, black */
	LINE_MCA	  = 0x0400, /* LD-specific MCA code (only matters on GM disks) */
	LINE_PHILLIPS	  = 0x0800, /* LD-specific 48-bit Phillips code */
	LINE_CAPTION	  = 0x1000, /* Closed captioning */
	LINE_WHITEFLAG	  = 0x2000, /* CAV LD only - depicts beginning of new film frame */
};

int NTSCLine[526], NTSCLineLoc[526];

void buildNTSCLines()
{
	int i;

	for (i = 0; i < 526; i++) NTSCLineLoc[i] = -1;

	// Each line array starts with 1 to line up with documetnation 

	// Odd field is line 1-263, even field is 264-525 

	// first set of eq lines
	for (i = 1; i <= 3; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_EQUALIZATION; 

	for (i = 4; i <= 6; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_FIELDSYNC; 

	for (i = 7; i <= 9; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_EQUALIZATION; 

	// While lines 10-21 have regular sync, but they contain special non-picture information 	
	for (i = 10; i <= 21; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_NORMAL; 

	// define odd field
	NTSCLine[10] |= LINE_WHITEFLAG; 
	NTSCLine[18] |= LINE_PHILLIPS; 

	for (i = 22; i <= 263; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 22) * 2) + 0;
	}
	NTSCLine[263] = LINE_HALF | LINE_VIDEO;

	// define even field
	NTSCLine[273] |= LINE_WHITEFLAG; 
	NTSCLine[264 + 18] |= LINE_PHILLIPS; 
	
	for (i = 285; i <= 525; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 285) * 2) + 1;
	}
}

enum tbc_type {TBC_HSYNC, TBC_CBURST};

class NTSColor {
	protected:
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;
		Filter *f_post;

		Filter *f_linelen;

		double fc, fci;
		double freq;

		tbc_type tbc;

		int cline;

		int fieldcount;

		int counter, lastline, lastsync;
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
	
		YIQ frame[1544 * 1024];
		
		vector<YIQ> *buf;

		int prev_igap, igap;
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

		bool whiteflag_decode() {
			int oc = 0;

			for (double c: line) {
				if (c > 0.8) {
					oc++;
				}
				if (oc > 600) return true;
			}
//			cerr << "W" << oc << endl;
			return false;
		}

		unsigned long phillips_decode() {
			int i = 0;
			int oc = 0;
			int lastone = 220 - 55 - 00;

			unsigned long code = 0;

			for (double c: line) {
				if (c > 0.8) {
					oc++;
				} else {
					if (oc) {
						int firstone = (i - oc) - 160;	
						int bit = firstone / 57;

						int offset = firstone - (bit * 57);
						if ((offset > 10) && (offset < 50)) {
							code |= (1 << (23 - bit));
						}

						cerr << cline << ' ' << i << ' ' << firstone << ' ' << bit * 57 << ' ' << bit << ' ' << hex << code << dec << endl;
						lastone = i;
					}
					oc = 0;
				}
				i++;
			}
			cerr << "P " << cline << ' ' << hex << code << dec << endl;
			return code;
		}

		NTSColor(vector<YIQ> *_buf = NULL, Filter *_f_post = NULL, Filter *_f_postc = NULL, double _freq = 8.0) {
			counter = 0;
			phased = insync = false;

			fieldcount = 0;
			cline = 0;

			pix_poffset = poffset = 0;
			adjfreq = 1.0;

			lastline = lastsync = -1;

			level = phase = 0.0;

			freq = _freq;

			buf = _buf;

			prev_igap = igap = -1;
					
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
	
			f_post = _f_post ? new Filter(*_f_post) : NULL;
		}

		void write() {
#ifndef RAW
			for (int i = 0; i < (1544 * 480); i++) {
				if (buf && ((i % 1544) >= 8)) buf->push_back(frame[i]);
			} 
			memset(frame, 0, sizeof(frame));
			cerr << "written\n";
#endif
		}

		void bump_cline() {
			cline++;
				
//			if (NTSCLine[cline] && LINE_NORMAL) lastsync = 0; 
	
			if ((cline == 263) || (cline == 526)) {
				fieldcount++;
				cerr << "fc " << fieldcount << endl;

				if (fieldcount == 2) {
					write();
					fieldcount = 0;
				}
			}
			if (cline == 526) cline = 1;
		}

		void feed(double in) {
			double dn = (double) in / 62000.0;
	
			if (!dn) {
				dn = buf_1h[counter % 1820]; 
			}

			buf_1h[counter % 1820] = dn;

			counter++;
			if (lastsync >= 0) lastsync++;

//			cerr << insync << ' ' << lastsync << endl;
			
			prev[counter % 32] = dn;

			int count = 0;
			if (insync == false) {
				for (int i = 0; i < 32; i++) {
					if (prev[i] < 0.1) {
						count++;
					}
				}
//				if (count >= 16) cerr << cline << " sync at 1 " << counter - 16 << ' ' << igap << ' ' << insync << endl;
				if (count >= 24) {
					if ((igap > 880) && (igap < 940)) {
						if ((cline <= 0) && (prev_igap >= 1800)) {
							cline = 1;
							lastline = counter;
						} /* else if ((cline >= 1) && ((counter - lastline) > 1800)) {
							lastline = counter;
							cline++;
							if (cline == 526) cline = 1;
						} */
					} else {
						if (buf && (NTSCLine[cline] & LINE_WHITEFLAG)) {
							if (whiteflag_decode()) {
								cerr << "whiteflag " << cline << endl;
								fieldcount = 0;	
							}
						}
/*						if (0 && buf && (cfline >= 6) && (cfline <= 8)) {
							unsigned long pc = phillips_decode() & 0xff0000;
							if (pc == 0xf80000 || pc == 0xfa0000 || pc == 0xf00000) {
								fieldcount = 0;
							}					
						}
*/						if ((igap > 1800) && (igap < 1840)) {
							f_linelen->feed(igap);
							if ((cline >= 1) && ((counter - lastline) > 1810)) {
								lastline = counter;
								bump_cline();
							}
						}
					}
				
					prev_igap = igap;	
					igap = lastsync;

					lastsync = 0;
					peaksynci = peaksyncq = peaksync = 0;

					cerr << cline << ' ' << NTSCLineLoc[cline] << " sync at " << counter - 24 << ' ' << igap << ' ' << insync << endl;
					insync = true;
					prev.clear();
					line.clear();
				}
					
				line.push_back(dn);

				if ((NTSCLine[cline] & LINE_NORMAL) && (igap < 1900) && lastsync == 250) {
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

					//cerr << (buf ? 'B' : 'A') << ' ' ;
					//cerr << counter << " level " << level << " q " << fc << " i " << fci << " phase " << atan2(fci, ctor(fc, fci)) << " adjfreq " << adjfreq << ' ' << igap << ':' << f_linelen->val() << ' ' << poffset - pix_poffset << endl ;
				} else {
//					if (buf && lastsync == 200 && igap >= 0) cerr << "S " << counter << ' ' << igap << endl;
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

                        double q = f_q->feed(dn * _cos[counter % 8]);
			double i = f_i->feed(-dn * _sin[counter % 8]);
                       
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
			if ((cline >= 1) && ((counter - lastline) == 2100)) {
				lastline += 1820;
				bump_cline();
			}

//			cerr << _cos[counter % 8] << ' ' << cos(phase + (2.0 * M_PIl * ((double)(counter) / freq))) << endl;

//                      double q = f_q->feed(dn * cos(phase + (2.0 * M_PIl * ((double)(counter) / freq))));
//			double i = f_i->feed(-dn * sin(phase + (2.0 * M_PIl * ((double)(counter) / freq))));

			if (buf && (lastsync >= 0)) {
				double _y = dn, y = dn;

				if (counter > 17) {
					_y = circbuf[counter % 17];
				}
				circbuf[counter % 17] = y;
				y = _y;

#ifndef BW
				double iadj = i * 2 * _cos[(counter - 3) % 8];
				double qadj = q * 2 * _sin[(counter - 3) % 8]; 
//				cerr << "p " << lastsync << ' ' << ctor(i, q) << ' ' << (atan2(i, ctor(i,q)) / (M_PIl / 180.0)) + 180.0 << " iadj " << iadj << " qadj " << qadj << " y " << y << " " << iadj + qadj;
				//cerr << "p " << atan2(i, q) << " iadj " << iadj << " qadj " << qadj << " y " << y;
				y += iadj + qadj;
//				cerr << " " << y << endl;

				if (f_post) y = f_post->feed(y);

				YIQ outc = YIQ(y, 2.5 * i, 2.5 * q);
#else
				YIQ outc = YIQ(y, 0,0);
#endif
				if (!lastsync) outc.y = 1.0;

#ifdef RAW
				buf->push_back(outc);			
#else
				if ((NTSCLineLoc[cline] >= 0) && (lastsync > 252) && (lastsync < (252 + 1544)) ) {
//					cerr << cline << ' ' << lastsync << endl;
					frame[(NTSCLineLoc[cline] * 1544) + (lastsync - 252)].y = outc.y;
					frame[(NTSCLineLoc[cline] * 1544) + (lastsync - 252) + 8].i = outc.i;
					frame[(NTSCLineLoc[cline] * 1544) + (lastsync - 252) + 8].q = outc.q;
				}
#endif
			}
	//		return YIQ();
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
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

	buildNTSCLines();

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
	Filter f_hp35(14, NULL, f_hp35_14_b);
	Filter f_lpf30(32, f_lpf30_b7_a, f_lpf30_b7_b);
	Filter f_lpf02(4, f_lpf048_b4_a, f_lpf048_b4_b);
	Filter f_butter6(6, f_butter6_a, f_butter6_b);
	Filter f_butter8(8, f_butter8_a, f_butter8_b);
	Filter f_boost6(8, NULL, f_boost6_b);
	Filter f_boost8(8, NULL, f_boost8_b);
	Filter f_boost16(8, NULL, f_boost16_b);

	Filter f_lpf49(8, NULL, f_lpf49_8_b);
	Filter f_lpf45(8, NULL, f_lpf45_8_b);
	Filter f_lpf13(8, NULL, f_lpf13_8_b);

	vector<YIQ> outbuf;	

	NTSColor *color = new NTSColor(&outbuf, &f_lpf45);

	int count = 0;

	while ((rv > 0) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;

		vector<unsigned short> bout;

		for (int i = 0; i < (rv / 2); i++) {
			int in = inbuf[i];

			count++;
			color->feed(in);
		}
		
		i += rv;
		if (i % 2) inbuf[0] = inbuf[rv];
		rv = read(fd, &inbuf[i % 2], 2048 - (i % 2));

		for (YIQ i : outbuf) {
			RGB r;
			r.conv(i);
			bout.push_back(r.r * 62000.0);
			bout.push_back(r.g * 62000.0);
			bout.push_back(r.b * 62000.0);
		}
		outbuf.clear();

		unsigned short *boutput = bout.data();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}
	}

	return 0;
}
