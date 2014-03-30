/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

// capture frequency and fundamental NTSC color frequency
//const double CHZ = (1000000.0*(315.0/88.0)*8.0);
//const double FSC = (1000000.0*(315.0/88.0));

bool pulldown_mode = false;
int ofd = 1;
bool image_mode = false;
char *image_base = "FRAME";
bool bw_mode = false;

// back-reason for selecting 30:  14.318/1.3*e = 29.939.  seems to work better than 31 ;) 
const double f28_1_3mhz_b30[] {4.914004914004915e-03, 5.531455998921954e-03, 7.356823678403171e-03, 1.031033062576930e-02, 1.426289441492169e-02, 1.904176904176904e-02, 2.443809475353342e-02, 3.021602622216704e-02, 3.612304011689930e-02, 4.190097158553291e-02, 4.729729729729729e-02, 5.207617192414463e-02, 5.602873571329703e-02, 5.898224266066317e-02, 6.080761034014438e-02, 6.142506142506142e-02, 6.080761034014438e-02, 5.898224266066317e-02, 5.602873571329704e-02, 5.207617192414465e-02, 4.729729729729731e-02, 4.190097158553292e-02, 3.612304011689932e-02, 3.021602622216705e-02, 2.443809475353343e-02, 1.904176904176904e-02, 1.426289441492169e-02, 1.031033062576930e-02, 7.356823678403167e-03, 5.531455998921954e-03, 4.914004914004915e-03};

const double f28_0_6mhz_b32[] {2.214464531115009e-03, 2.779566868356983e-03, 4.009052177841430e-03, 6.041802526864055e-03, 8.964977379775094e-03, 1.280250319629312e-02, 1.750822265693915e-02, 2.296445273166145e-02, 2.898626064895014e-02, 3.533129030361252e-02, 4.171449995422212e-02, 4.782674655050909e-02, 5.335581047849616e-02, 5.800822770944922e-02, 6.153020526791717e-02, 6.372594980605055e-02, 6.447193442389310e-02, 6.372594980605055e-02, 6.153020526791718e-02, 5.800822770944922e-02, 5.335581047849616e-02, 4.782674655050909e-02, 4.171449995422215e-02, 3.533129030361253e-02, 2.898626064895015e-02, 2.296445273166145e-02, 1.750822265693915e-02, 1.280250319629313e-02, 8.964977379775097e-03, 6.041802526864056e-03, 4.009052177841434e-03, 2.779566868356985e-03, 2.214464531115009e-03};

const double f28_1_3mhz_b32[] {-1.605533065998730e-03, -1.720671809315438e-03, -1.946714932361703e-03, -1.994955262998560e-03, -1.418668951504014e-03, 3.196223312744169e-04, 3.750192920679346e-03, 9.284036375671866e-03, 1.710727911480327e-02, 2.710292793921179e-02, 3.881702596824465e-02, 5.147908615666569e-02, 6.407728145733732e-02, 7.547900436664387e-02, 8.457890959912071e-02, 9.045104659530802e-02, 9.248026239443490e-02, 9.045104659530802e-02, 8.457890959912071e-02, 7.547900436664387e-02, 6.407728145733733e-02, 5.147908615666569e-02, 3.881702596824466e-02, 2.710292793921179e-02, 1.710727911480328e-02, 9.284036375671866e-03, 3.750192920679346e-03, 3.196223312744170e-04, -1.418668951504014e-03, -1.994955262998559e-03, -1.946714932361704e-03, -1.720671809315439e-03, -1.605533065998730e-03};

const double f28_2_0mhz_b32[] {1.006978939588801e-03, 4.700244549263112e-04, -4.726346152704030e-04, -2.225844911626193e-03, -4.930568911222814e-03, -8.168445482658226e-03, -1.081751892744065e-02, -1.115502409857046e-02, -7.225662580847139e-03, 2.599834101418699e-03, 1.902920988854001e-02, 4.140374974465560e-02, 6.756622702884178e-02, 9.412348408941272e-02, 1.170721331619509e-01, 1.326445909772283e-01, 1.381589342821457e-01, 1.326445909772283e-01, 1.170721331619509e-01, 9.412348408941271e-02, 6.756622702884177e-02, 4.140374974465560e-02, 1.902920988854002e-02, 2.599834101418700e-03, -7.225662580847139e-03, -1.115502409857046e-02, -1.081751892744065e-02, -8.168445482658233e-03, -4.930568911222816e-03, -2.225844911626193e-03, -4.726346152704032e-04, 4.700244549263113e-04, 1.006978939588801e-03};

const double f28_0_6mhz_b64[] {-6.916447903947148e-04, -6.637277886690091e-04, -6.506794962762819e-04, -6.385960636428408e-04, -6.091489627652988e-04, -5.401328736698201e-04, -4.062390816451122e-04, -1.800289567056259e-04, 1.669277273337949e-04, 6.627933750400666e-04, 1.334132570703104e-03, 2.204566737142542e-03, 3.293471104686198e-03, 4.614771600461567e-03, 6.175896724145871e-03, 7.976934496300239e-03, 1.001003732312394e-02, 1.225910839260336e-02, 1.469979236820074e-02, 1.729978111972153e-02, 2.001943252605971e-02, 2.281268753589040e-02, 2.562825822709219e-02, 2.841104809911676e-02, 3.110375576479802e-02, 3.364860502185666e-02, 3.598913834498529e-02, 3.807200741849585e-02, 3.984869359245655e-02, 4.127709314339044e-02, 4.232290688845818e-02, 4.296078085959773e-02, 4.317515410421566e-02, 4.296078085959773e-02, 4.232290688845819e-02, 4.127709314339045e-02, 3.984869359245655e-02, 3.807200741849585e-02, 3.598913834498529e-02, 3.364860502185667e-02, 3.110375576479803e-02, 2.841104809911677e-02, 2.562825822709219e-02, 2.281268753589041e-02, 2.001943252605972e-02, 1.729978111972153e-02, 1.469979236820075e-02, 1.225910839260336e-02, 1.001003732312394e-02, 7.976934496300244e-03, 6.175896724145871e-03, 4.614771600461570e-03, 3.293471104686198e-03, 2.204566737142541e-03, 1.334132570703105e-03, 6.627933750400653e-04, 1.669277273337959e-04, -1.800289567056260e-04, -4.062390816451116e-04, -5.401328736698201e-04, -6.091489627652993e-04, -6.385960636428407e-04, -6.506794962762823e-04, -6.637277886690096e-04, -6.916447903947148e-04};

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
                y.y *= 1.1;
//                y.y = clamp(y.y, 0, 1.0);

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

double black_ire = -20;
int black_u16 = ire_to_u16(black_ire);
int white_u16 = level_100ire; 
bool whiteflag_detect = true;


int write_locs = -1;

class Comb
{
	protected:
		int linecount;  // total # of lines process - needed to maintain phase
		int curline;    // current line # in frame 
		int active;	// set to 1 when first frame ends

		int framecode;
		int framecount;	

		bool f_oddframe;	// true if frame starts with odd line

		long long scount;	// total # of samples consumed

		int fieldcount;
		int frames_out;	// total # of written frames
	
		int bufsize; 

		double curscale;

		uint16_t frame[1820 * 530];
		uint8_t obuf[1488 * 525 * 3];
		uint8_t tmp_obuf[1488 * 525 * 3];

		double blevel[525];

		double _cos[525][16], _sin[525][16];
		double i[525][1820], q[525][1820];
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;

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

				v = (double)(v - black_u16) / (double)(white_u16 - black_u16); 

				double q = f_syncq->feed(v * _cos[0][l % 8]);
				double i = f_synci->feed(-v * _sin[0][l % 8]);

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

//			cerr << pi << ' ' << pq << ' ' << pphase << endl;

			return rv;
		}

		double blend(double orig, double a, double b, bool &dis) {
			double abs_orig = fabs(orig);
		        double agreementa = fabs(orig - a);
		        double agreementb = fabs(orig - b);
        		double disagreementa = fabs(orig + a);
        		double disagreementb = fabs(orig + b);

			dis = false;

			if ((agreementa < agreementb) && (agreementa < (abs_orig / 4))) {
				if (agreementb < (abs_orig / 4)) {
					return (0.5 * orig) + (0.25 * a) + (0.25 * b);
				} else {
					return (0.5 * orig) + (0.5 * a);
				}
			}
			if (agreementb < (abs_orig / 4)) {
				return (0.5 * orig) + (0.5 * b);
			}
			if ((disagreementa < disagreementb) && (disagreementa < (abs_orig / 4))) {
				dis = true;
				if (disagreementb < (abs_orig / 4)) {
					return ((0.5 * orig) + (0.25 * a) + (0.25 * b));
				} else {
					return ((0.5 * orig) + (0.5 * a));
				}
			}
			if (disagreementb < (abs_orig / 4)) {
				dis = true;
				return ((0.5 * orig) + (0.5 * b));
			}

			return (0.5 * orig) + (0.25 * a) + (0.25 * b);
		}

		// buffer: 1685x505 uint16_t array
		void CombFilter(uint16_t *buffer, uint8_t *output)
		{
			YIQ outline[1685];
			blevel[23] = 0;
			for (int l = 24; l < 504; l++) {
				uint16_t *line = &buffer[l * 1685];
//				double _cos[(int)freq + 1], _sin[(int)freq + 1];
				double level, phase;

				double val, _val;
				double cmult;

				BurstDetect(line, 0, 4 * dots_usec, level, phase);
//				cerr << "burst " << level << ' ' << phase << endl;
				for (int j = 0; j < (int)freq; j++) { 
	                                _cos[l][j] = cos(phase + (2.0 * M_PIl * ((double)j / freq)));
					_sin[l][j] = sin(phase + (2.0 * M_PIl * ((double)j / freq)));
				}

				if (blevel[l - 1] > 0) {
					blevel[l] = blevel[l - 1] * 0.9;
					blevel[l] += (level * 0.1);
				} else blevel[l] = level;

				int counter = 0;
				for (int h = line_blanklen - 64 - 135; counter < 1760 - 135; h++) {
//					val = (double)line[h] / (double)level_100ire;
					val = (double)(line[h] - black_u16) / (double)(white_u16 - black_u16); 
//					val = clamp(val, 0, 1.2);
//					val = u16_to_ire(line[h]);
				
					q[l][h] = f_q->feed(-val * _cos[l][h % 8]);
					i[l][h] = f_i->feed(val * _sin[l][h % 8]);
					
//					cerr << "P" << h << ' ' << counter << ' ' << line[h] << ' ' << val << ' ' << (double)line[h] / (double)level_100ire << endl;
					counter++;
				}
			}
	
			for (int l = 24; l < 504; l++) {
				uint16_t *line = &buffer[l * 1685];
				int counter = 0;
				double circbuf[18];
				double val, _val;
				for (int h = line_blanklen - 64 - 135; counter < 1760 - 135; h++) {
					val = (double)(line[h] - black_u16) / (double)(white_u16 - black_u16); 
//					cerr << black_u16 << ' ' << line[h] << ' ' << level_100ire << ' ' << val << endl;
#ifdef BW
					i = q = 0;
#endif
					double cmult = 0.12 / blevel[l];
//					double cmult = 3.5;

					double icomp = i[l][h];
					double qcomp = q[l][h];

					bool dis;

					double icomb = blend(i[l][h], i[l - 2][h], i[l + 2][h], dis);
					icomp = dis ? 0 : icomb;
					double qcomb = blend(q[l][h], q[l - 2][h], q[l + 2][h], dis);
					qcomp = dis ? 0 : qcomb;

					//double icomb = i[l][h];
					//double qcomb = q[l][h];

					if (bw_mode) {
						icomb = qcomb = 0;
						icomp = qcomp = 0;
					}
 
					double iadj = icomp * 2 * _cos[l][(h + 1) % 8];
					double qadj = qcomp * 2 * _sin[l][(h + 1) % 8];

//					cerr << ' ' << _val << ' ' << iadj + qadj << ' ';
	                                if (counter > 17) {
						_val = circbuf[counter % 17];
       	                         	}
	                                circbuf[counter % 17] = val;
					val = _val;

					val += iadj + qadj;
#ifdef GRAY 
					i = q = 0;
#endif
					YIQ outc = YIQ(val, cmult * icomb, cmult * qcomb);	

					if (counter >= 42) {
						outline[counter - 42].y = outc.y;
						outline[counter - 42].i = outc.i;
						outline[counter - 42].q = outc.q;
//						cerr << ' ' << outc.y << ' ' << outc.i << ' ' << outc.q;
					} 
//					cerr << endl;

					counter++;
				}
		
				uint8_t *line_output = &output[(1488 * 3 * (l - 24))];

				int o = 0; 
				for (int h = 0; h < 1488; h++) {
					RGB r;
					r.conv(outline[h]);

					line_output[o++] = (uint8_t)(r.r * 255.0); 
					line_output[o++] = (uint8_t)(r.g * 255.0); 
					line_output[o++] = (uint8_t)(r.b * 255.0); 
				}
			}

			return;
		}

		uint32_t ReadPhillipsCode(uint16_t *line) {
			const int first_bit = (int)205 - 58;
			const double bitlen = 2.0 * dots_usec;
			uint32_t out = 0;

			for (int i = 0; i < 24; i++) {
				double val = 0;
	
//				cerr << dots_usec << ' ' << (int)(first_bit + (bitlen * i) + dots_usec) << ' ' << (int)(first_bit + (bitlen * (i + 1))) << endl;	
				for (int h = (int)(first_bit + (bitlen * i) + dots_usec); h < (int)(first_bit + (bitlen * (i + 1))); h++) {
//					cerr << h << ' ' << line[h] << ' ' << endl;
					val += u16_to_ire(line[h]); 
				}

//				cerr << "bit " << 23 - i << " " << val / dots_usec << ' ' << hex << out << dec << endl;	
				if ((val / dots_usec) < 50) {
					out |= (1 << (23 - i));
				} 
			}
			cerr << "P " << curline << ' ' << hex << out << dec << endl;			

			return out;
		}

	public:
		Comb(int _bufsize = 4096) {
			fieldcount = curline = linecount = -1;
			active = 0;
			framecode = framecount = frames_out = 0;

			scount = 0;

			bufsize = _bufsize;

			f_oddframe = false;	
	
			// build table of standard cos/sin for phase/level calc	
			for (int e = 0; e < freq; e++) {
				_cos[0][e] = cos((2.0 * M_PIl * ((double)e / freq)));
				_sin[0][e] = sin((2.0 * M_PIl * ((double)e / freq)));
			}

			//f_i = new Filter(30, NULL, f28_1_3mhz_b30);
			//f_q = new Filter(30, NULL, f28_1_3mhz_b30);
			f_i = new Filter(32, NULL, f28_0_6mhz_b32);
			f_q = new Filter(32, NULL, f28_0_6mhz_b32);
//			f_i = new Filter(32, NULL, f28_2_0mhz_b32);
//			f_q = new Filter(32, NULL, f28_2_0mhz_b32);

                        f_synci = new Filter(64, NULL, f28_0_6mhz_b64);
                        f_syncq = new Filter(64, NULL, f28_0_6mhz_b64);
		}

		void WriteFrame(uint8_t *obuf, int fnum = 0) {
			if (!image_mode) {
				write(ofd, obuf, (1488 * 480 * 3));
			} else {
				char ofname[512];

				sprintf(ofname, "%s%d.rgb", image_base, fnum); 
				cerr << "W " << ofname << endl;
				ofd = open(ofname, O_WRONLY | O_CREAT, S_IRUSR | S_IWUSR | S_IROTH);
				write(ofd, obuf, (1488 * 480 * 3));
				close(ofd);
			}
		}

		int Process(uint16_t *buffer) {
			int fstart = -1;

			if (!pulldown_mode) {
				fstart = 0;
			} else if (f_oddframe) {
				CombFilter(buffer, tmp_obuf);
				for (int i = 0; i <= 478; i += 2) {
					memcpy(&obuf[1488 * 3 * i], &tmp_obuf[1488 * 3 * i], 1488 * 3); 
				}
				WriteFrame(obuf, framecode);
				f_oddframe = false;		
			}

			for (int line = 2; line <= 3; line++) {
				int wc = 0;
				for (int i = 0; i < 1400; i++) {
					if (buffer[(1685 * line) + i] > 45000) wc++;
				} 
				if (wc > 1000) {
					fstart = (line % 2); 
				}
				cerr << "PW" << line << ' ' << wc << ' ' << fieldcount << endl;
			}

			for (int line = 14; line <= 17; line++) {
				int new_framecode = ReadPhillipsCode(&buffer[line * 1685]) - 0xf80000;

				cerr << line << ' ' << hex << new_framecode << dec << endl;

				if ((new_framecode > 0) && (new_framecode < 0x60000)) {
					int ofstart = fstart;

					framecode = new_framecode & 0x0f;
					framecode += ((new_framecode & 0x000f0) >> 4) * 10;
					framecode += ((new_framecode & 0x00f00) >> 8) * 100;
					framecode += ((new_framecode & 0x0f000) >> 12) * 1000;
					framecode += ((new_framecode & 0xf0000) >> 16) * 10000;
	
	
					fstart = (line % 2); 
					if ((ofstart >= 0) && (fstart != ofstart)) {
						cerr << "MISMATCH\n";
					}
				}
			}

			CombFilter(buffer, obuf);

			cerr << "FR " << framecount << ' ' << fstart << endl;
			if (!pulldown_mode || (fstart == 0)) {
				WriteFrame(obuf, framecode);
			} else if (fstart == 1) {
				f_oddframe = true;
			}

			framecount++;

			return 0;
		}
};
	
Comb comb;

void usage()
{
	cerr << "comb: " << endl;
	cerr << "-i [filename] : input filename (default: stdin)\n";
	cerr << "-o [filename] : output filename/base (default: stdout/frame)\n";
	cerr << "-f : use separate file for each frame\n";
	cerr << "-p : use white flag/frame # for pulldown\n";	
	cerr << "-h : this\n";	
}

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1, tproc = 0;
	//double output[2048];
	unsigned short inbuf[1685 * 525 * 2];
	unsigned char *cinbuf = (unsigned char *)inbuf;
	int c;

	char out_filename[256] = "";

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;

	while ((c = getopt(argc, argv, "Bb:w:i:o:fph")) != -1) {
		switch (c) {
			case 'B':
				bw_mode = true;
				break;
			case 'b':
				sscanf(optarg, "%d", &black_u16);
				break;
			case 'w':
				sscanf(optarg, "%d", &white_u16);
				break;
			case 'h':
				usage();
				return 0;
			case 'f':
				image_mode = true;	
				break;
			case 'p':
				pulldown_mode = true;	
				break;
			case 'i':
				fd = open(optarg, O_RDONLY);
				break;
			case 'o':
				image_base = (char *)malloc(strlen(optarg) + 1);
				strncpy(image_base, optarg, strlen(optarg));
				break;
			default:
				return -1;
		} 
	} 

	if (!image_mode && strlen(out_filename)) {
		ofd = open(image_base, O_WRONLY | O_CREAT);
	}

	cout << std::setprecision(8);

	buildNTSCLines();

	int bufsize = 1685 * 505 * 2;

	rv = read(fd, inbuf, bufsize);
	while ((rv > 0) && (rv < bufsize)) {
		int rv2 = read(fd, &cinbuf[rv], bufsize - rv);
		if (rv2 <= 0) exit(0);
		rv += rv2;
	}

	while (rv == bufsize && ((tproc < dlen) || (dlen < 0))) {
		comb.Process(inbuf);	
	
		rv = read(fd, inbuf, bufsize);
		while ((rv > 0) && (rv < bufsize)) {
			int rv2 = read(fd, &cinbuf[rv], bufsize - rv);
			if (rv2 <= 0) exit(0);
			rv += rv2;
		}
	}

	return 0;
}

