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

const double f28_1_3mhz_b32[] {-1.605533065998730e-03, -1.720671809315438e-03, -1.946714932361703e-03, -1.994955262998560e-03, -1.418668951504014e-03, 3.196223312744169e-04, 3.750192920679346e-03, 9.284036375671866e-03, 1.710727911480327e-02, 2.710292793921179e-02, 3.881702596824465e-02, 5.147908615666569e-02, 6.407728145733732e-02, 7.547900436664387e-02, 8.457890959912071e-02, 9.045104659530802e-02, 9.248026239443490e-02, 9.045104659530802e-02, 8.457890959912071e-02, 7.547900436664387e-02, 6.407728145733733e-02, 5.147908615666569e-02, 3.881702596824466e-02, 2.710292793921179e-02, 1.710727911480328e-02, 9.284036375671866e-03, 3.750192920679346e-03, 3.196223312744170e-04, -1.418668951504014e-03, -1.994955262998559e-03, -1.946714932361704e-03, -1.720671809315439e-03, -1.605533065998730e-03};

const double f28_0_6mhz_b64[] {-6.916447903947148e-04, -6.637277886690091e-04, -6.506794962762819e-04, -6.385960636428408e-04, -6.091489627652988e-04, -5.401328736698201e-04, -4.062390816451122e-04, -1.800289567056259e-04, 1.669277273337949e-04, 6.627933750400666e-04, 1.334132570703104e-03, 2.204566737142542e-03, 3.293471104686198e-03, 4.614771600461567e-03, 6.175896724145871e-03, 7.976934496300239e-03, 1.001003732312394e-02, 1.225910839260336e-02, 1.469979236820074e-02, 1.729978111972153e-02, 2.001943252605971e-02, 2.281268753589040e-02, 2.562825822709219e-02, 2.841104809911676e-02, 3.110375576479802e-02, 3.364860502185666e-02, 3.598913834498529e-02, 3.807200741849585e-02, 3.984869359245655e-02, 4.127709314339044e-02, 4.232290688845818e-02, 4.296078085959773e-02, 4.317515410421566e-02, 4.296078085959773e-02, 4.232290688845819e-02, 4.127709314339045e-02, 3.984869359245655e-02, 3.807200741849585e-02, 3.598913834498529e-02, 3.364860502185667e-02, 3.110375576479803e-02, 2.841104809911677e-02, 2.562825822709219e-02, 2.281268753589041e-02, 2.001943252605972e-02, 1.729978111972153e-02, 1.469979236820075e-02, 1.225910839260336e-02, 1.001003732312394e-02, 7.976934496300244e-03, 6.175896724145871e-03, 4.614771600461570e-03, 3.293471104686198e-03, 2.204566737142541e-03, 1.334132570703105e-03, 6.627933750400653e-04, 1.669277273337959e-04, -1.800289567056260e-04, -4.062390816451116e-04, -5.401328736698201e-04, -6.091489627652993e-04, -6.385960636428407e-04, -6.506794962762823e-04, -6.637277886690096e-04, -6.916447903947148e-04};

const double f_hsync8[] {1.447786467971050e-02, 4.395811440315845e-02, 1.202636955256379e-01, 2.024216184054497e-01, 2.377574139720867e-01, 2.024216184054497e-01, 1.202636955256379e-01, 4.395811440315847e-02, 1.447786467971050e-02};

inline double IRE(double in) 
{
	return (in * 140.0) - 40.0;
}

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
	LINE_ENDFIELD     = 0x10, /* End of Field */ 
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

// WIP
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
	NTSCLine[11] |= LINE_WHITEFLAG; 
	NTSCLine[15] |= LINE_PHILLIPS; 
	NTSCLine[16] |= LINE_PHILLIPS; 
	NTSCLine[17] |= LINE_PHILLIPS; 
	NTSCLine[18] |= LINE_PHILLIPS; 
	NTSCLine[19] |= LINE_PHILLIPS; 
	NTSCLine[20] |= LINE_PHILLIPS; 

	for (i = 22; i <= 263; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 22) * 2) + 0;
	}
	NTSCLine[263] = LINE_HALF | LINE_VIDEO | LINE_ENDFIELD;

	// define even field
	NTSCLine[274] |= LINE_WHITEFLAG; 
	NTSCLine[264 + 18] |= LINE_PHILLIPS; 
	
	for (i = 285; i <= 525; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 285) * 2) + 1;
	}

	NTSCLine[525] |= LINE_ENDFIELD;
#if 1
	// debug only
	for (i = 0; i <= 263; i++) {
		NTSCLineLoc[i] = ((i) * 2) + 0;
	}
	for (i = 264; i <= 525; i++) {
		NTSCLineLoc[i] = ((i - 263) * 2) + 1;
	}
#endif
}

// NTSC properties
const double freq = 8.0;	// in FSC

const double hlen = 227.5 * freq;
const double dotclk = (1000000.0*(315.0/88.0)*8.0); 

const double dots_usec = dotclk / 1000000.0; 

// values for horizontal timings 
const double line_blanklen = 10.7 * dots_usec;

const double line_fporch = 1.5 * dots_usec; // front porch

const double line_syncp = 4.7 * dots_usec; // sync pulse
const double line_bporch = 4.5  * dots_usec; // total back porch 

const double line_bporch1 = 0.5 * dots_usec;
const double line_burstlen = 9.0 * freq; // 9 3.58mhz cycles
const double line_bporch2 = 1.5 * dots_usec; // approximate 

// timings used in vsync lines
const double line_eqpulse = 2.3 * dots_usec;
const double line_serpulse = 4.7 * dots_usec;

const double line_vspulse = 30 * dots_usec; // ???

// uint16_t levels
uint16_t level_m40ire = 1;
uint16_t level_0ire = 16384;
uint16_t level_7_5_ire = 3071;
uint16_t level_100ire = 40959;
uint16_t level_120ire = 65535;

inline double u16_to_ire(uint16_t level)
{
	if (level == 0) return -100;
	
	return -40 + ((160.0 / 65533.0) * (double)level); 
} 

inline uint16_t ire_to_u16(double ire)
{
	if (ire <= -100) return 0;
	if (ire <= -40) return 1;

	if (ire >= 120) return 65535;	

	return (((ire + 40) / 160.0) * 65534) + 1;
} 

// tunables

double black_ire = 7.5;

class TBC
{
	protected:
		int linecount;  // total # of lines process - needed to maintain phase
		int curline;    // current line # in frame 
		int active;	// set to 1 when first frame ends

		int fieldcount;
	
		int bufsize; 

		double curscale;

		uint16_t frame[1820 * 530];

		double _cos[16], _sin[16];
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;

		int FindHSync(uint16_t *buf, int start, int &pulselen, int tlen = 32) {
			Filter f_s(32, NULL, f28_1_3mhz_b32);

			int sync_start = -1;

			// allow for filter startup
			if (start > 31) start -= 31;
	
			for (int i = start; i < bufsize; i++) {
				double v = f_s.feed(buf[i]);

//				cerr << i << ' ' << buf[i] << ' ' << v << endl; 

				// need to wait 30 samples
				if (i > 30) {
					if (sync_start < 0) {
						if (v < 10000) sync_start = i;
					} else if (v > 10000) {
						if ((i - sync_start) > tlen) {
						//	cerr << "found " << i << " " << sync_start << ' ' << (i - sync_start) << endl;
							pulselen = i - sync_start;
							return sync_start - 15; // XXX: find right offset
						}
						sync_start = -1;
					}
				}
			}
			return -1;
		} 

		int BurstDetect(uint16_t *buf, int start, int len, double &plevel, double &pphase)
		{
			int rv = 0;
			double pi = 0, pq = 0;

			plevel = 0.0;
			pphase = 0.0;

			f_synci->clear(ire_to_u16(black_ire));
			f_syncq->clear(ire_to_u16(black_ire));

			// XXX? allow for filter startup
			if (start > 65) start -= 65;

			for (int l = start; l < start + len; l++) {
				double v = buf[l];

				double q = f_syncq->feed(v * _cos[l % 8]);
				double i = f_synci->feed(-v * _sin[l % 8]);

				double level = ctor(i, q);

//				if ((l - start) > 65) cerr << l << ' ' << buf[l] << ' ' << level << ' ' << atan2(i, q) << endl;
	
				if (((l - start) > 65) && level > plevel) {
					plevel = level;
					pi = i; pq = q;
				}
			}

			if (plevel) {
				pphase = atan2(pi, pq);
			}

			cerr << pi << ' ' << pq << ' ' << pphase << endl;

			return rv;
		}


		void ScaleOut(uint16_t *buf, uint16_t *outbuf, double start, double len)
		{
			double perpel = len / hlen; 
			double plevel, pphase, out;

			for (int i = 0; i < hlen + 400; i++) {
				double p1, p2;

				p1 = start + (i * perpel);
				p2 = start + ((i + 1) * perpel);
				
				int l1 = floor(p1), l2 = floor(p2);

				if (l1 == l2) {
					out = perpel * buf[(int)floor(p1)];
				} else {
					out = (buf[l1] * (floor(p2) - p1)) +
					      (buf[l2] * (p2 - floor(p2))); 
				}
//				out *= perpel;
				if (out > 65535) out = 65535;
				if (out < 0) out = 0;
				outbuf[i] = out;
			}
		}

	public:
		TBC(int _bufsize = 4096) {
			fieldcount = curline = linecount = -1;
			active = 0;

			bufsize = _bufsize;
		
			// build table of standard cos/sin for phase/level calc	
			for (int e = 0; e < freq; e++) {
				_cos[e] = cos((2.0 * M_PIl * ((double)e / freq)));
				_sin[e] = sin((2.0 * M_PIl * ((double)e / freq)));
			}

			f_i = new Filter(32, NULL, f28_1_3mhz_b32);
			f_q = new Filter(32, NULL, f28_1_3mhz_b32);

                        f_synci = new Filter(64, NULL, f28_0_6mhz_b64);
                        f_syncq = new Filter(64, NULL, f28_0_6mhz_b64);
		}

		// This assumes an entire 4K sliding buffer is available.  The return value is the # of new bytes desired 
		int Process(uint16_t *buffer) {
			uint16_t outbuf[(int)hlen * 2];	
			// find the first VSYNC, determine it's length
			double pcon;

			int sync_len;
			int sync_start = FindHSync(buffer, 0, sync_len);

			// if there isn't a whole line and (if applicable) following burst, advance first
			if (sync_start < 0) return 4096;
			if ((4096 - sync_start) < 2400) return (sync_start - 64);
			if (sync_start < 50) return 512;

			cerr << "first sync " << sync_start << " " << sync_len << endl;

			// find next vsync.  this may be at .5H, if we're in VSYNC
			int sync2_len;
			int sync2_start = FindHSync(buffer, sync_start + sync_len + (int)(64 * freq), sync2_len);
			
			cerr << "second sync " << sync2_start << " " << sync2_len << endl;

			// determine if this is a standard line
			double linelen = sync2_start - sync_start;

			// check sync lengths and distance between syncs to see if we've got a regular line
			if ((fabs(linelen - hlen) < (hlen * .02)) && 
/*			    (sync2_len > (16 * freq)) && (sync2_len < (18 * freq)) && */
			    (sync_len > (16 * freq)) && (sync_len < (18 * freq)))
			{
				double plevel, pphase, pphase2;

				cerr << "regular line" << endl; 
				BurstDetect(&buffer[sync_start], 3.5 * dots_usec, 7.5 * dots_usec, plevel, pphase);
				cerr << "burst 1 " << plevel << " " << pphase << endl;
			
				cerr << sync_len << ' ' << (sync2_start - sync_start + sync2_len) << endl;	
				BurstDetect(&buffer[sync_start], (sync2_start - sync_start) + (3.5 * dots_usec), 7.5 * dots_usec, plevel, pphase2);
				cerr << "burst 2 " << plevel << " " << pphase2 << endl;

				double gap = -((pphase2 - pphase) / M_PIl) * 4.0;
				if (gap < -4) gap += 8;
				if (gap > 4) gap -= 8;

				cerr << "gap " << gap << endl;
				ScaleOut(buffer, outbuf, sync_start, 1820 + gap);
				
				BurstDetect(outbuf, 3.5 * dots_usec, 7.5 * dots_usec, plevel, pphase);
				cerr << "post-scale 1 " << plevel << " " << pphase << endl;

				if (linecount == -1) {
					if (pphase > 0) { 
						linecount = 0;
						pcon = (M_PIl / 2) - pphase;
					} else {
						linecount = 1;
						pcon = (-M_PIl / 2) - pphase;
					}
				}
				if (linecount % 2) {
					pcon = (-M_PIl / 2) - pphase;
				} else {
					pcon = (M_PIl / 2) - pphase;
				}
				cerr << pcon << endl;

				double adjust = (pcon / M_PIl) * 4.0;
				if (adjust < -4) adjust += 8;
				if (adjust > 4) adjust -= 8;
				cerr << "adjust " << adjust << endl;

				ScaleOut(buffer, outbuf, sync_start + adjust, 1820 + gap);
				BurstDetect(outbuf, 3.5 * dots_usec, 7.5 * dots_usec, plevel, pphase);
				cerr << "post-scale 2 " << plevel << " " << pphase << endl;
			} else {
				cerr << "special line" << endl; 

				if ((sync_len > (15 * freq)) &&
				    (sync_len < (18 * freq)) &&
				    (sync2_len < (9 * freq)) &&
				    ((sync2_start - sync_start) < (freq * 125)) &&
				    ((sync2_start - sync_start) > (freq * 110))) {
					curline = 263;
				}

				ScaleOut(buffer, outbuf, sync_start, 1820);
			}
		

			if (curline >= 0) {
				cerr << "L" << NTSCLineLoc[curline] << endl;

				// On Laserdisc, lines 11 and 274 are 'white' flags indicating new field start
				if (NTSCLine[curline] & LINE_WHITEFLAG) {
					int wc = 0;
					for (int i = line_blanklen; i < 1800; i++) {
						if (outbuf[i] > 40000) wc++;
					} 
					if (wc > 800) fieldcount = 0;
				}

				if (NTSCLineLoc[curline] >= 0) {
					memcpy(&frame[NTSCLineLoc[curline] * 1820], outbuf, 3840);
				
					if ((fieldcount >= 0) && (NTSCLine[curline] & LINE_ENDFIELD))
					{
						fieldcount++;
						if (fieldcount == 2) {
							write(1, frame, 1820 * 2 * 525);
							memset(frame, 0, sizeof(frame));
							fieldcount = 0;
						}
					}
				}

				curline++;
				if (curline > 525) {
					curline = 1; 
					if (fieldcount < 0) fieldcount = 0;
				}
			}
			if (linecount >= 0) linecount++;

			return (sync_start - 64 + 1820);
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1, tproc = 0;
	//double output[2048];
	unsigned short inbuf[4096];

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

	buildNTSCLines();

	TBC tbc;

	rv = read(fd, inbuf, 8192);

	while (rv == 8192 && ((tproc < dlen) || (dlen < 0))) {
		int plen = tbc.Process(inbuf);	

		tproc += plen;
                memmove(inbuf, &inbuf[plen], (4096 - plen) * 2);
                rv = read(fd, &inbuf[(4096 - plen)], plen * 2) + ((4096 - plen) * 2);
	}

	return 0;
}

