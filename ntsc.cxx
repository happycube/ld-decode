/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

// capture frequency and fundamental NTSC color frequency
//const double CHZ = (1000000.0*(315.0/88.0)*8.0);
//const double FSC = (1000000.0*(315.0/88.0));

// back-reason for selecting 30:  14.318/1.3*e = 29.939.  seems to work better than 31 ;) 
const double f28_1_3mhz_b30[] {4.914004914004915e-03, 5.531455998921954e-03, 7.356823678403171e-03, 1.031033062576930e-02, 1.426289441492169e-02, 1.904176904176904e-02, 2.443809475353342e-02, 3.021602622216704e-02, 3.612304011689930e-02, 4.190097158553291e-02, 4.729729729729729e-02, 5.207617192414463e-02, 5.602873571329703e-02, 5.898224266066317e-02, 6.080761034014438e-02, 6.142506142506142e-02, 6.080761034014438e-02, 5.898224266066317e-02, 5.602873571329704e-02, 5.207617192414465e-02, 4.729729729729731e-02, 4.190097158553292e-02, 3.612304011689932e-02, 3.021602622216705e-02, 2.443809475353343e-02, 1.904176904176904e-02, 1.426289441492169e-02, 1.031033062576930e-02, 7.356823678403167e-03, 5.531455998921954e-03, 4.914004914004915e-03};

const double f28_1_3mhz_b32[] {-1.605533065998730e-03, -1.720671809315438e-03, -1.946714932361703e-03, -1.994955262998560e-03, -1.418668951504014e-03, 3.196223312744169e-04, 3.750192920679346e-03, 9.284036375671866e-03, 1.710727911480327e-02, 2.710292793921179e-02, 3.881702596824465e-02, 5.147908615666569e-02, 6.407728145733732e-02, 7.547900436664387e-02, 8.457890959912071e-02, 9.045104659530802e-02, 9.248026239443490e-02, 9.045104659530802e-02, 8.457890959912071e-02, 7.547900436664387e-02, 6.407728145733733e-02, 5.147908615666569e-02, 3.881702596824466e-02, 2.710292793921179e-02, 1.710727911480328e-02, 9.284036375671866e-03, 3.750192920679346e-03, 3.196223312744170e-04, -1.418668951504014e-03, -1.994955262998559e-03, -1.946714932361704e-03, -1.720671809315439e-03, -1.605533065998730e-03};

const double f28_0_6mhz_b64[] {-6.916447903947148e-04, -6.637277886690091e-04, -6.506794962762819e-04, -6.385960636428408e-04, -6.091489627652988e-04, -5.401328736698201e-04, -4.062390816451122e-04, -1.800289567056259e-04, 1.669277273337949e-04, 6.627933750400666e-04, 1.334132570703104e-03, 2.204566737142542e-03, 3.293471104686198e-03, 4.614771600461567e-03, 6.175896724145871e-03, 7.976934496300239e-03, 1.001003732312394e-02, 1.225910839260336e-02, 1.469979236820074e-02, 1.729978111972153e-02, 2.001943252605971e-02, 2.281268753589040e-02, 2.562825822709219e-02, 2.841104809911676e-02, 3.110375576479802e-02, 3.364860502185666e-02, 3.598913834498529e-02, 3.807200741849585e-02, 3.984869359245655e-02, 4.127709314339044e-02, 4.232290688845818e-02, 4.296078085959773e-02, 4.317515410421566e-02, 4.296078085959773e-02, 4.232290688845819e-02, 4.127709314339045e-02, 3.984869359245655e-02, 3.807200741849585e-02, 3.598913834498529e-02, 3.364860502185667e-02, 3.110375576479803e-02, 2.841104809911677e-02, 2.562825822709219e-02, 2.281268753589041e-02, 2.001943252605972e-02, 1.729978111972153e-02, 1.469979236820075e-02, 1.225910839260336e-02, 1.001003732312394e-02, 7.976934496300244e-03, 6.175896724145871e-03, 4.614771600461570e-03, 3.293471104686198e-03, 2.204566737142541e-03, 1.334132570703105e-03, 6.627933750400653e-04, 1.669277273337959e-04, -1.800289567056260e-04, -4.062390816451116e-04, -5.401328736698201e-04, -6.091489627652993e-04, -6.385960636428407e-04, -6.506794962762823e-04, -6.637277886690096e-04, -6.916447903947148e-04};

const double f28_0_3mhz_b32[] {3.978057329252118e-03, 4.515056281806121e-03, 5.964949733492637e-03, 8.323677232466895e-03, 1.154314080495843e-02, 1.553225223505762e-02, 2.016018845137591e-02, 2.526172777477888e-02, 3.064442643002365e-02, 3.609729304005547e-02, 4.140053457612618e-02, 4.633588526888740e-02, 5.069699391924866e-02, 5.429933707757621e-02, 5.698914631738589e-02, 5.865088633990866e-02, 5.921289437519849e-02, 5.865088633990864e-02, 5.698914631738591e-02, 5.429933707757621e-02, 5.069699391924866e-02, 4.633588526888740e-02, 4.140053457612618e-02, 3.609729304005548e-02, 3.064442643002365e-02, 2.526172777477887e-02, 2.016018845137590e-02, 1.553225223505763e-02, 1.154314080495844e-02, 8.323677232466895e-03, 5.964949733492642e-03, 4.515056281806124e-03, 3.978057329252118e-03};

const double f28_0_3mhz_b64[] {1.156216942166937e-03, 1.260302595139044e-03, 1.439372164292797e-03, 1.703612390217742e-03, 2.062019858422272e-03, 2.522165397605361e-03, 3.089981612510836e-03, 3.769578440427629e-03, 4.563091102952233e-03, 5.470564206893792e-03, 6.489875042604241e-03, 7.616698349024995e-03, 8.844513978562953e-03, 1.016465801913355e-02, 1.156641703393353e-02, 1.303716418092476e-02, 1.456253509299260e-02, 1.612664055540294e-02, 1.771231222795924e-02, 1.930137694250046e-02, 2.087495447795009e-02, 2.241377318905297e-02, 2.389849745309321e-02, 2.531006061071641e-02, 2.662999691928111e-02, 2.784076601392927e-02, 2.892606348388255e-02, 2.987111141749148e-02, 3.066292314453501e-02, 3.129053690062719e-02, 3.174521374612856e-02, 3.202059577804195e-02, 3.211282146320453e-02, 3.202059577804194e-02, 3.174521374612856e-02, 3.129053690062719e-02, 3.066292314453502e-02, 2.987111141749148e-02, 2.892606348388254e-02, 2.784076601392927e-02, 2.662999691928112e-02, 2.531006061071642e-02, 2.389849745309320e-02, 2.241377318905297e-02, 2.087495447795010e-02, 1.930137694250046e-02, 1.771231222795925e-02, 1.612664055540295e-02, 1.456253509299260e-02, 1.303716418092477e-02, 1.156641703393353e-02, 1.016465801913356e-02, 8.844513978562949e-03, 7.616698349024998e-03, 6.489875042604247e-03, 5.470564206893790e-03, 4.563091102952234e-03, 3.769578440427634e-03, 3.089981612510838e-03, 2.522165397605363e-03, 2.062019858422274e-03, 1.703612390217742e-03, 1.439372164292798e-03, 1.260302595139044e-03, 1.156216942166937e-03};

const double f_hsync8[] {1.447786467971050e-02, 4.395811440315845e-02, 1.202636955256379e-01, 2.024216184054497e-01, 2.377574139720867e-01, 2.024216184054497e-01, 1.202636955256379e-01, 4.395811440315847e-02, 1.447786467971050e-02};

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
        //      y.i = clamp(y.i, -0.5957, .5957);
        //      y.q = clamp(y.q, -0.5226, .5226);

                y.y -= (.4 / 1.4);
                y.y *= 1.4;
                y.y = clamp(y.y, 0, 1.0);

                r = (y.y * 1.164) + (1.596 * y.i);
                g = (y.y * 1.164) - (0.813 * y.i) - (y.q * 0.391);
                b = (y.y * 1.164) + (y.q * 2.018);

                r = clamp(r, 0, 1.00);
                g = clamp(g, 0, 1.00);
                b = clamp(b, 0, 1.00);
                //cerr << 'y' << y.y << " i" << y.i << " q" << y.q << ' ';
                //cerr << 'r' << r << " g" << g << " b" << b << endl;
        };
};


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
	NTSCLine[17] |= LINE_PHILLIPS; 
	NTSCLine[18] |= LINE_PHILLIPS; 

	for (i = 22; i <= 263; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 22) * 2) + 0;
	}

	NTSCLine[263] = LINE_HALF | LINE_VIDEO | LINE_ENDFIELD;

	// define even field
	NTSCLine[263 + 11] |= LINE_WHITEFLAG; 
	NTSCLine[263 + 17] |= LINE_PHILLIPS; 
	NTSCLine[263 + 18] |= LINE_PHILLIPS; 
	
	for (i = 285; i <= 525; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 285) * 2) + 1;
	}

	NTSCLine[525] |= LINE_ENDFIELD;

	// full frame mode
	for (i = 0; i <= 263; i++) {
		NTSCLineLoc[i] = ((i) * 2) + 0;
	}
	for (i = 264; i <= 525; i++) {
		NTSCLineLoc[i] = ((i - 263) * 2) + 1;
	}
}

// NTSC properties
const double freq = 8.0;	// in FSC.  Must be an even number!

const double hlen = 227.5 * freq;
const int    hleni = (int)hlen;
const double dotclk = (1000000.0*(315.0/88.0)*8.0); 

const double dots_usec = dotclk / 1000000.0; 

// values for horizontal timings 
const double line_blanklen = 10.9 * dots_usec;

const double line_fporch = 1.5 * dots_usec; // front porch

const double line_syncp = 4.7 * dots_usec; // sync pulse
const double line_bporch = 4.7  * dots_usec; // total back porch 

const double line_bporch1 = 0.5 * dots_usec;
const double line_burstlen = 9.0 * freq; // 9 3.58mhz cycles
const double line_bporch2 = 1.7 * dots_usec; // approximate 

// timings used in vsync lines
const double line_eqpulse = 2.3 * dots_usec;
const double line_serpulse = 4.7 * dots_usec;

const double line_vspulse = 30 * dots_usec; // ???

// uint16_t levels
uint16_t level_m40ire = 1;
uint16_t level_0ire = 16384;
uint16_t level_7_5_ire = 16384+3071;
uint16_t level_100ire = 57344;
uint16_t level_120ire = 65535;

inline double u16_to_ire(uint16_t level)
{
	if (level == 0) return -100;
	
	return -40 + ((160.0 / 65533.0) * (double)level); 
} 

inline uint16_t ire_to_u16(double ire)
{
	if (ire <= -60) return 0;
	if (ire <= -40) return 1;

	if (ire >= 120) return 65535;	

	return (((ire + 40) / 160.0) * 65534) + 1;
} 

// tunables

double black_ire = 7.5;
bool whiteflag_detect = true;

int write_locs = -1;

class TBC
{
	protected:
		int linecount;  // total # of lines process - needed to maintain phase
		int curline;    // current line # in frame 
		int active;	// set to 1 when first frame ends

		bool f_newframe, f_whiteflag;

		long long scount;	// total # of samples consumed

		int fieldcount;
		int frames_out;	// total # of written frames
	
		int bufsize; 

		bool jumped;
		double prev_gap, prev_adjust;

		double curscale;

		uint16_t frame[1820 * 530];

		double _cos[16], _sin[16];
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;

		int32_t framecode;	// in hex

		int FindHSync(uint16_t *buf, int start, int len, int &pulselen, int tlen = 60) {
			Filter f_s(32, NULL, f28_0_3mhz_b32);

			int sync_start = -1;

			framecode = -1;

			// allow for filter startup
			if (start > 32) start -= 32;
	
			for (int i = start; i < start + len; i++) {
				double v = f_s.feed(buf[i]);

//				cerr << i << ' ' << buf[i] << ' ' << v << endl; 

				// need to wait 30 samples
				if (i > 32) {
					if (sync_start < 0) {
						if (v < 11000) sync_start = i;
					} else if (v > 11000) {
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
		
		int eBurstDetect(uint16_t *buf, int start, int len, double &plevel, double &pphase)
		{
			int rv = 0;
			double pi = 0, pq = 0;

			double i[4096], q[4096], level[4096];

			plevel = 0.0;
			pphase = 0.0;

			f_synci->clear(ire_to_u16(black_ire));
			f_syncq->clear(ire_to_u16(black_ire));

			// XXX? allow for filter startup
			if (start > 65) start -= 65;

			for (int l = start; l < start + len; l++) {
				double v = buf[l];

//				v = (double)(v - black_u16) / (double)(white_u16 - black_u16); 

				q[l] = f_syncq->feed(v * _cos[l % 8]);
				i[l] = f_synci->feed(-v * _sin[l % 8]);

				level[l] = ctor(i[l], q[l]);

//				if ((l - start) > 65) cerr << l << ' ' << buf[l] << ' ' << level[l] << ' ' << atan2(i[l], q[l]) << ' ' << atan2(pi, pq) << endl;
	
				if (((l - start) > 65) && level[l] > plevel) {
					plevel = level[l];
					pi = i[l]; pq = q[l];
				}
			}
	
			double aphase = 0.0, threshold = plevel * .98;	
			int valid = 0;	
			for (int l = start + 65; l < start + len; l++) {
				if (level[l] > threshold) {
					aphase += atan2(i[l], q[l]);
					valid++;
//					cerr << aphase << ' ' << aphase / valid << endl;
				}
			}

			if (plevel) {
				pphase = aphase / valid;
//				pphase = atan2(pi, pq);
			}

//			cerr << pi << ' ' << pq << ' ' << pphase << endl;

			return rv;
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

		//		if ((l - start) > 65) cerr << l << ' ' << buf[l] << ' ' << level << ' ' << atan2(i, q) << endl;
	
				if (((l - start) > 65) && level > plevel) {
					plevel = level;
					pi = i; pq = q;
				}
			}

			if (plevel) {
				pphase = atan2(pi, pq);
			}

//			cerr << pi << ' ' << pq << ' ' << pphase << endl;

			return rv;
		}
	
		// writes a 1685x505 16-bit grayscale frame	
		void WriteBWFrame(uint16_t *buffer) {
			for (int i = 20; i <= 524; i++) {
				write(1, &buffer[(i * 1820) + 135], 1685 * 2);
			}
		}

		// taken from http://www.paulinternet.nl/?page=bicubic
		double CubicInterpolate(uint16_t *y, double x)
		{
			double p[4];
			p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

			return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
		}
	
		void ScaleOut(uint16_t *buf, uint16_t *outbuf, double start, double len)
		{
			double perpel = len / hlen; 
			double plevel, pphase, out;

			for (int i = 0; i < hlen + 400; i++) {
				double p1;
				
				p1 = start + (i * perpel);
				int index = (int)p1;
				if (index < 1) index = 1;

				out = CubicInterpolate(&buf[index - 1], p1 - index);

				if (out > 65535) out = 65535;
				if (out < 0) out = 0;
				outbuf[i] = out;
			}
		}

		uint32_t ReadPhillipsCode(uint16_t *line) {
			const int first_bit = (int)(.188 * hlen);
			const double bitlen = 2.0 * dots_usec;
			uint32_t out = 0;

			for (int i = 0; i < 24; i++) {
				double val = 0;
	
//				cerr << dots_usec << ' ' << (int)(first_bit + (bitlen * i) + dots_usec) << ' ' << (int)(first_bit + (bitlen * (i + 1))) << endl;	
				for (int h = (int)(first_bit + (bitlen * i) + dots_usec); h < (int)(first_bit + (bitlen * (i + 1))); h++) {
//					cerr << h << ' ' << line[h] << ' ' << endl;
					val += u16_to_ire(line[h]); 
				}

//				cerr << "bit " << 23 - i << " " << val / dots_usec << endl;	
				if ((val / dots_usec) < 50) {
					out |= (1 << (23 - i));
				} 
			}
			cerr << "P " << curline << ' ' << hex << out << dec << endl;			

			return out;
		}

		bool IsVisibleLine(int curline) {
			if ((curline < 0) || (curline > 525)) return false;

			return (NTSCLine[curline] & LINE_VIDEO);
		}

	public:
		TBC(int _bufsize = 4096) {
			fieldcount = curline = linecount = -1;
			active = 0;
			frames_out = 0;

			scount = 0;

			bufsize = _bufsize;
	
			f_newframe = f_whiteflag = false;
	
			// build table of standard cos/sin for phase/level calc	
			for (int e = 0; e < freq; e++) {
				_cos[e] = cos((2.0 * M_PIl * ((double)e / freq)));
				_sin[e] = sin((2.0 * M_PIl * ((double)e / freq)));
			}

			f_i = new Filter(32, NULL, f28_1_3mhz_b32);
			f_q = new Filter(32, NULL, f28_1_3mhz_b32);

                        f_synci = new Filter(64, NULL, f28_0_3mhz_b64);
                        f_syncq = new Filter(64, NULL, f28_0_3mhz_b64);

			jumped = false;
			prev_gap = prev_adjust = 0;
		}

		// This assumes an entire 4K sliding buffer is available.  The return value is the # of new bytes desired 
		int Process(uint16_t *buffer) {
			uint16_t outbuf[(int)hlen * 2];	
			// find the first VSYNC, determine it's length
			double pcon = 0;
			double gap = 0.0;

			int sync_len;
			int sync_start = FindHSync(buffer, 0, bufsize, sync_len);
		
			// if there isn't a whole line and (if applicable) following burst, advance first
			if (sync_start < 0) {
				scount += 4096;
				return 4096;
			}
			if ((4096 - sync_start) < 2400) {
				scount += sync_start - 64;
				return sync_start - 64;
			}
			if (sync_start < 50) {
				scount += 512;
				return 512;
			}

//			cerr << "first sync " << sync_start << " " << sync_len << endl;

			// find next vsync.  this may be at .5H, if we're in VSYNC
			int sync2_len;
			int sync2_start;
	
			sync2_start = FindHSync(buffer, sync_start + 750, 300, sync2_len);
			if (sync2_start < 0) {
				sync2_start = FindHSync(buffer, sync_start + 1800, 300, sync2_len);
			}		
			if (sync2_start < 0) {
				sync2_start = sync_start + 1820;
			}		
	
//			cerr << "second sync " << sync2_start << " " << sync2_len << endl;

			// determine if this is a standard line
			double linelen = sync2_start - sync_start;

			// check sync lengths and distance between syncs to see if we've got a regular line
			if ((fabs(linelen - hlen) < (hlen * .05)) && 
/*			    (sync2_len > (16 * freq)) && (sync2_len < (18 * freq)) && */
			    (sync_len > (15 * freq)) && (sync_len < (20 * freq)))
			{
				double plevel, plevel2, pphase, pphase2;

				// determine color burst and phase levels of both this and next color bursts

				BurstDetect(&buffer[sync_start], 4.5 * dots_usec, 7.0 * dots_usec, plevel, pphase);
//				cerr << curline << " start " << sync_start << " burst 1 " << plevel << " " << pphase << endl;
		
				// cerr << sync_len << ' ' << (sync2_start - sync_start + sync2_len) << endl;	
				BurstDetect(&buffer[sync_start], (sync2_start - sync_start) + (4.5 * dots_usec), 7.0 * dots_usec, plevel2, pphase2);
				// cerr << "burst 2 " << plevel2 << " " << pphase2 << ' ';

				// if available, use the phase data of the next line's burst to determine line length
				if ((plevel > 500) && (plevel2 > 500)) {
					gap = -((pphase2 - pphase) / M_PIl) * 4.0;
					// cerr << sync_start << ":" << sync2_start << " " << (((sync2_start - sync_start) > hlen)) << ' ' << gap << endl;
					if (gap < -4) gap += 8;
					if (gap > 4) gap -= 8;
			
//					if (((sync2_start - sync_start) > hlen) && (gap < -.5)) gap += 4;
//					if (((sync2_start - sync_start) < hlen) && (gap > .5)) gap -= 4;

//					cerr << "gap " << gap << endl;
					ScaleOut(buffer, outbuf, sync_start, 1820 + gap);
				
					BurstDetect(outbuf, 4.5 * dots_usec, 7.0 * dots_usec, plevel, pphase);
//					cerr << "gap " << gap << ' ' << "post-scale 1 " << plevel << " " << pphase << endl;
				
					// if this is the first line (of the frame?) set up phase targets for each line
					if (linecount == -1) {
						if (pphase > 0) { 
							linecount = 0;
						} else {
							linecount = 1;
						}
					}
				} else {
					cerr << "WARN:  Missing burst\n";
					gap = 0.0; // sync2_start - sync_start;
				}

				// if this line has a good color burst, adjust phase
				if (plevel > 500) {
//					cerr << pphase << ' ';

					if (pphase < 0) {
						pcon = (-M_PIl / 2) - pphase;
                                                if (pcon < -M_PIl) {
                                                        pcon = (M_PIl / 2) + (M_PIl - pphase);
                                                }
					} else {
						pcon = (M_PIl / 2) - pphase;
                                                if (pcon > M_PIl) {
                                                        pcon = (-M_PIl / 2) - (pphase + M_PIl);
						}
					}
					// cerr << pcon << endl;

					double adjust = (pcon / M_PIl) * 4.0;
					double dadjust = fabs(adjust - prev_adjust);

					// if we jumped a half phase, we might be repeating a frame
					if (((dadjust > 3.5) && (dadjust < 6.0)) || 
					    (!jumped && (fabs(gap - prev_gap) > 2.0))) { 
	
						cerr << "J" << linecount << ' ' << prev_adjust << ' ' << adjust << ' ' << gap << ' ' << prev_gap << endl;
						jumped = true;
						linecount++;
					} else {
						jumped = false;
					}
			
	
					if (dadjust > 7.0) {
//						cerr << "E";
						if (prev_adjust < 0) adjust -= 8;
						else adjust += 8;
					}
/*
					if (adjust < -4) {
						cerr << "e";
						adjust += 8;
					}
					if (adjust > 4) {
						cerr << "e";
						adjust -= 8;
					}
*/
//					cerr << linecount << " adjust " << adjust << " gap " << gap << " syncgap " << (sync2_start - sync_start) << endl;

                                        ScaleOut(buffer, outbuf, sync_start + adjust, 1820 + gap);
				
					prev_adjust = jumped ? 0 : adjust;
				} else {
					cerr << "WARN:  No first burst found\n";
				}
			} else {
//				cerr << "special line" << endl; 

				if (((curline > 23) && (curline < 260)) || 
				    ((curline > 290) && (curline < 520))) {
					cerr << "ERR " << scount << endl;
				}

				if ((sync_len > (15 * freq)) &&
				    (sync_len < (18 * freq)) &&
				    (sync2_len < (10 * freq)) &&
				    ((sync2_start - sync_start) < (freq * 125)) &&
				    ((sync2_start - sync_start) > (freq * 110))) {
					curline = 263;
				}

				ScaleOut(buffer, outbuf, sync_start, 1820);
			}
		
			if (write_locs == 1) {
				char outline[128];

				sprintf(outline, "%ld %lf\n", scount + sync_start, gap);
				write(3, outline, strlen(outline));
			}

			if (curline >= 0) {
//				cerr << "L" << NTSCLineLoc[curline] << endl;
				bool is_whiteflag = false;
				bool is_newframe = false;

				if (NTSCLineLoc[curline] >= 0) {
					memcpy(&frame[NTSCLineLoc[curline] * 1820], outbuf, 3840);
				
					if ((fieldcount >= 0) && (NTSCLine[curline] & LINE_ENDFIELD))
					{
						fieldcount++;
						if (fieldcount == 2) {
							frames_out++;
							cerr << "Writing Frame #" << frames_out << endl;
							WriteBWFrame(frame);
							memset(frame, 0, sizeof(frame));
							fieldcount = 0;
						}
					}
				}

				curline++;
				if (curline > 525) {
					curline = 1; 
				//	linecount = -1;
					if (fieldcount < 0) fieldcount = 0;
					if (!write_locs) {
						write_locs = 1;
					}
				}
			}
			if (linecount >= 0) linecount++;

			prev_gap = gap;

			scount += sync_start - 64 + 1820;
			return (sync_start - 64 + 1820);
		}
};

int is_valid_fd(int fd)
{
    return fcntl(fd, F_GETFL) != -1 || errno != EBADF;
}

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1, tproc = 0;
	//double output[2048];
	unsigned short inbuf[4096];
	unsigned char *cinbuf = (unsigned char *)inbuf;

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

	if (is_valid_fd(3)) {
		write_locs = 0;
	}

	cout << std::setprecision(8);

	buildNTSCLines();

	TBC tbc;

	rv = read(fd, inbuf, 8192);
	while ((rv > 0) && (rv < 8192)) {
		int rv2 = read(fd, &cinbuf[rv], 8192 - rv);
		if (rv2 <= 0) exit(0);
		rv += rv2;
	}

	while (rv == 8192 && ((tproc < dlen) || (dlen < 0))) {
		int plen = tbc.Process(inbuf);	

		tproc += plen;
                memmove(inbuf, &inbuf[plen], (4096 - plen) * 2);
                rv = read(fd, &inbuf[(4096 - plen)], plen * 2) + ((4096 - plen) * 2);
		while ((rv > 0) && (rv < 8192)) {
			int rv2 = read(fd, &cinbuf[rv], 8192 - rv);
			if (rv2 <= 0) exit(-1);
			rv += rv2;
		}	
	}

	return 0;
}

