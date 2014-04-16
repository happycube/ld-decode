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

const double f14_1_3mhz_b15[] {-3.190093002289628e-03, -3.191345516111202e-03, 2.934926651176227e-04, 1.634894114451717e-02, 5.123523965895763e-02, 1.014467069217903e-01, 1.523838439686879e-01, 1.846732141593300e-01, 1.846732141593300e-01, 1.523838439686880e-01, 1.014467069217904e-01, 5.123523965895767e-02, 1.634894114451718e-02, 2.934926651176237e-04, -3.191345516111201e-03, -3.190093002289628e-03};

const double f14_0_6mhz_b15[] {5.162833431022274e-03, 9.537169343788440e-03, 2.179793428021240e-02, 4.246170446278436e-02, 6.920721093300924e-02, 9.725734014351654e-02, 1.206398826611330e-01, 1.339359247445336e-01, 1.339359247445335e-01, 1.206398826611330e-01, 9.725734014351656e-02, 6.920721093300930e-02, 4.246170446278436e-02, 2.179793428021239e-02, 9.537169343788435e-03, 5.162833431022274e-03};

const double f14_0_6mhz_b30[] {-1.258748785899385e-03, -1.057528127814725e-03, -7.529999144837454e-04, 9.019397940118997e-05, 1.988350225701514e-03, 5.443508287665837e-03, 1.083818469820938e-02, 1.833894901300455e-02, 2.782730702513882e-02, 3.887247656764735e-02, 5.075392314356197e-02, 6.253310939739308e-02, 7.316529074574056e-02, 8.163491886101157e-02, 8.709363828372436e-02, 8.897885319999538e-02, 8.709363828372438e-02, 8.163491886101154e-02, 7.316529074574056e-02, 6.253310939739311e-02, 5.075392314356199e-02, 3.887247656764737e-02, 2.782730702513884e-02, 1.833894901300456e-02, 1.083818469820939e-02, 5.443508287665837e-03, 1.988350225701514e-03, 9.019397940119008e-05, -7.529999144837451e-04, -1.057528127814725e-03, -1.258748785899385e-03};

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
const double freq = 4.0;	// in FSC.  Must be an even number!

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

enum cline_stat {
};

typedef struct cline {
	double y[hleni]; // Y
	double m[hleni]; // IQ magnitude
	double a[hleni]; // IQ phase angle
//	int stat[hleni];
} cline_t;

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
		uint8_t obuf[742 * 525 * 3];
		uint8_t tmp_obuf[742 * 525 * 3];

		double blevel[525];

		double _cos[525][16], _sin[525][16];
		cline_t wbuf[3][525];
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
			if (start > 30) start -= 30;

			for (int l = start; l < start + len; l++) {
				double v = buf[l];

				v = (double)(v - black_u16) / (double)(white_u16 - black_u16); 

				double q = f_syncq->feed(v * _cos[0][l % 4]);
				double i = f_synci->feed(-v * _sin[0][l % 4]);

				double level = ctor(i, q);

//				if ((l - start) > 65) cerr << l << ' ' << buf[l] << ' ' << level << ' ' << atan2(i, q) << endl;

//				cerr << l << ' ' << i << ' ' << q << ' ' << level << endl;
	
				if (((l - start) > 15) && level > plevel) {
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

		double adiff(double a1, double a2) {
			double v = a2 - a1;

			if (v > M_PIl) v -= (2 * M_PIl);
			else if (v <= -M_PIl) v += (2 * M_PIl);

			return v;
		}

		cline_t Blend(cline_t &prev, cline_t &cur, cline_t &next) {
			cline cur_combed;

			int counter = 0;
			for (int h = 0; counter < 842; h++) {
//				cerr << h << ' ' << prev.a[h] << ' ' << cur.a[h] << ' ' << next.a[h] << ' ';	
//				cerr << ": " << prev.m[h] << ' ' << cur.m[h] << ' ' << next.m[h] << endl;	
//				cerr << h << ' ' << adiff(prev.a[h], cur.a[h]) << ' ' << adiff(cur.a[h], next.a[h]) << ' ' << adiff(prev.a[h], next.a[h]) << endl;	

				double diff = (fabs(adiff(prev.a[h], cur.a[h])) + fabs(adiff(cur.a[h], next.a[h]))) / 2.0;
//				double adj = fabs(adiff(prev.a[h], next.a[h]) / diff);	

				cur_combed.y[h] = cur.y[h];
				cur_combed.a[h] = cur.a[h];
				cur_combed.m[h] = cur.m[h];
#if 0
				if (fabs(adiff(prev.a[h], cur.a[h])) < (M_PIl * .1)) {
					cur_combed.a[h] *= 0.5;
					cur_combed.a[h] += (prev.a[h] * 0.5);
				} else if (fabs(adiff(prev.a[h], next.a[h])) < (M_PIl * .1)) {
					cur_combed.a[h] *= 0.5;
					cur_combed.a[h] += (next.a[h] * 0.5);
				} 
#endif	
				if (diff > (M_PIl * .5)) {
					double adj = 1 - (diff / M_PIl); 
					if (adj < 0) adj = 0;
					if (adj > 1) adj = 1;
					
					cur_combed.m[h] *= adj;
				}

				counter++;
//				cerr << h << ' ' << diff << ' ' <<  adj << endl;
			}
			return cur_combed;
		}

		// buffer: 842x505 uint16_t array
		void CombFilter(uint16_t *buffer, uint8_t *output)
		{
			YIQ outline[842];
			blevel[23] = 0;
			for (int l = 24; l < 504; l++) {
				uint16_t *line = &buffer[l * 842];
//				double _cos[(int)freq + 1], _sin[(int)freq + 1];
				double level, phase;

				double val;

				BurstDetect(line, 0, 1.5 * dots_usec, level, phase);
				cerr << "burst " << level << ' ' << phase << endl;
				for (int j = 0; j < (int)freq; j++) { 
	                                _cos[l][j] = cos(phase + (2.0 * M_PIl * ((double)j / freq)));
					_sin[l][j] = sin(phase + (2.0 * M_PIl * ((double)j / freq)));
				}

				if (blevel[l - 1] > 0) {
					blevel[l] = blevel[l - 1] * 0.9;
					blevel[l] += (level * 0.1);
				} else blevel[l] = level;

				int counter = 0;
				for (int h = 0; counter < 842; h++) {
					double sq, si;

					val = (double)(line[h] - black_u16) / (double)(white_u16 - black_u16); 
				
					sq = f_q->feed(-val * _cos[l][h % 4]);
					si = f_i->feed(val * _sin[l][h % 4]);

					wbuf[0][l].y[h] = line[h]; 
					wbuf[0][l].m[h] = ctor(si, sq); 
					wbuf[0][l].a[h] = atan2(si, sq); 
					
//					cerr << "P" << h << ' ' << counter << ' ' << line[h] << ' ' << val << ' ' << (double)line[h] / (double)level_100ire << endl;
					counter++;
				}
			}
	
			for (int l = 24; l < 504; l++) {
				cline_t line;

				if (l < 503) 
					line = Blend(wbuf[0][l - 2], wbuf[0][l], wbuf[0][l + 2]);
				else
					memcpy(&line, &wbuf[0][l], sizeof(cline_t));

				int counter = 0;
				double circbuf[9];
				for (int i = 0; i < 9; i++) circbuf[i] = 0;

				double val, _val;
				for (int h = 0; counter < 842; h++) {
					val = (double)(line.y[h] - black_u16) / (double)(white_u16 - black_u16); 
					double cmult = 0.12 / blevel[l];

					double icomp = 0;
					double qcomp = 0;

					//cerr << h << "x" << l << endl;
				
					if (!bw_mode) {
						icomp = line.m[h] * sin(line.a[h]);
						qcomp = line.m[h] * cos(line.a[h]);
					} else {
						icomp = qcomp = 0;
					}
	
					double iadj = icomp * 2 * _cos[l][(h + 1) % 4];
					double qadj = qcomp * 2 * _sin[l][(h + 1) % 4];
					
//					cerr << counter << ' ' << val << ' ' ;

//					cerr << ' ' << _val << ' ' << iadj + qadj << ' ';
	                                if (counter > 8) {
						_val = circbuf[counter % 8];
       	                         	}
	                                circbuf[counter % 8] = val;
					val = _val;

					val += iadj + qadj;
#ifdef GRAY 
					i = q = 0;
#endif
					YIQ outc = YIQ(val, cmult * icomp, cmult * qcomp);	

//					cerr << outc.y << endl;

					if ((counter >= 81) && (counter < (742 + 81))) {
						outline[counter - 81].y = outc.y;
						outline[counter - 81].i = outc.i;
						outline[counter - 81].q = outc.q;
//						cerr << ' ' << outc.y << ' ' << outc.i << ' ' << outc.q;
					} 
//					cerr << endl;

					counter++;
				}
		
				uint8_t *line_output = &output[(742 * 3 * (l - 24))];

				int o = 0; 
				for (int h = 0; h < 742; h++) {
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
			const int first_bit = (int)102 - 29;
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

			f_i = new Filter(15, NULL, f14_0_6mhz_b15);
			f_q = new Filter(15, NULL, f14_0_6mhz_b15);

                        f_synci = new Filter(15, NULL, f14_0_6mhz_b15);
                        f_syncq = new Filter(15, NULL, f14_0_6mhz_b15);
		}

		void WriteFrame(uint8_t *obuf, int fnum = 0) {
			if (!image_mode) {
				write(ofd, obuf, (742 * 480 * 3));
			} else {
				char ofname[512];

				sprintf(ofname, "%s%d.rgb", image_base, fnum); 
				cerr << "W " << ofname << endl;
				ofd = open(ofname, O_WRONLY | O_CREAT, S_IRUSR | S_IWUSR | S_IROTH);
				write(ofd, obuf, (742 * 480 * 3));
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
					memcpy(&obuf[742 * 3 * i], &tmp_obuf[742 * 3 * i], 742 * 3); 
				}
				WriteFrame(obuf, framecode);
				f_oddframe = false;		
			}

			for (int line = 2; line <= 3; line++) {
				int wc = 0;
				for (int i = 0; i < 700; i++) {
					if (buffer[(842 * line) + i] > 45000) wc++;
				} 
				if (wc > 1000) {
					fstart = (line % 2); 
				}
				cerr << "PW" << line << ' ' << wc << ' ' << fieldcount << endl;
			}

			for (int line = 14; line <= 17; line++) {
				int new_framecode = ReadPhillipsCode(&buffer[line * 842]) - 0xf80000;

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
	unsigned short inbuf[842 * 525 * 2];
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

	int bufsize = 842 * 505 * 2;

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

