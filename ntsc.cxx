/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

// capture frequency and fundamental NTSC color frequency
//const double CHZ = (1000000.0*(315.0/88.0)*8.0);
//const double FSC = (1000000.0*(315.0/88.0));

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
const double in_freq = 8.0;	// in FSC 
const double freq = 4.0;	// output freq in FSC.  Needs to be an even number (for now?) 
const int freqi = 4;

const double sfreq = in_freq / freq;

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

		double curscale;

		uint16_t frame[hleni * 530];

		double _cos[16], _sin[16];
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;

		int32_t framecode;	// in hex

		int FindHSync(uint16_t *buf, int start, int len, int &pulselen, int tlen = 25) {
			Filter f_s(15, NULL, f14_1_3mhz_b15);

			int sync_start = -1;

			framecode = -1;

			// allow for filter startup
			if (start > 15) start -= 15;
	
			for (int i = start; i < start + len; i++) {
				double v = f_s.feed(buf[i]);

//				cerr << i << ' ' << buf[i] << ' ' << v << endl; 

				// need to wait 15 samples
				if (i > 15) {
					if (sync_start < 0) {
						if (v < 11000) sync_start = i;
					} else if (v > 11000) {
						if ((i - sync_start) > tlen) {
//							cerr << "found " << i << " " << sync_start << ' ' << (i - sync_start) << endl;
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
			if (start > 20) start -= 20;

			for (int l = start; l < start + len; l++) {
				double v = buf[l];

				double q = f_syncq->feed(v * _cos[l % freqi]);
				double i = f_synci->feed(-v * _sin[l % freqi]);

				double level = ctor(i, q);

//				if ((l - start) > 65) cerr << l << ' ' << buf[l] << ' ' << level << ' ' << atan2(i, q) << endl;
	
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
	
		// writes a 1685x505 16-bit grayscale frame	
		void WriteBWFrame(uint16_t *buffer) {
			for (int i = 20; i <= 524; i++) {
				write(1, &buffer[(i * 910) + 90], 842 * 2);
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
			double rescale_len = len * sfreq;
			double perpel = rescale_len / hlen; 
			double plevel, pphase, out;

			int slen = (int)(bufsize / perpel) - 2; 

			start *= (in_freq / freq);

//			cerr << "scaling inlen " << len << " recale_len " << rescale_len << "  slen " << slen << " perpel " << perpel << "start " << start << endl;

			for (int i = 0; i < slen; i++) {
				double p1;
				
				p1 = start + (i * perpel);
				int index = (int)p1;
				if (index < 1) index = 1;

//				if (!i) cerr << index << endl;

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

			f_i = new Filter(15, NULL, f14_1_3mhz_b15);
			f_q = new Filter(15, NULL, f14_1_3mhz_b15);

                        f_synci = new Filter(15, NULL, f14_0_6mhz_b15);
                        f_syncq = new Filter(15, NULL, f14_0_6mhz_b15);
		}

		// This assumes an entire 4K sliding buffer is available.  The return value is the # of new bytes desired 
		int Process(uint16_t *buffer) {
			uint16_t buf[hleni * 4];	
			// find the first VSYNC, determine it's length
			double pcon;
			double gap = 0.0;

			// initialize internal buffer - rescales the input to desired fsc 
			ScaleOut(buffer, buf, 0, hleni);

			int sync_len;
			int sync_start = FindHSync(buf, 0, bufsize / sfreq, sync_len);
			
			// if there isn't a whole line and (if applicable) following burst, advance first
			if (sync_start < 0) {
				scount += 2048;
				return 2048;
			}
			if ((2048 - sync_start) < 1100) {
				scount += sync_start - 64;
				return sync_start - 64;
			}
			if (sync_start < 50) {
				scount += 512;
				return 512;
			}

			cerr << "first sync " << sync_start << " " << sync_len << endl;

			// find next vsync.  this may be at .5H, if we're in VSYNC
			int sync2_len = 0;
			int sync2_start;
	
			sync2_start = FindHSync(buf, sync_start + 300, 300, sync2_len);
			if (sync2_start < 0) {
				sync2_start = FindHSync(buf, sync_start + 900, 200, sync2_len);
			}		
			if (sync2_start < 0) {
				sync2_start = sync_start + hleni;
			}		
	
			// determine if this is a standard line
			double linelen = sync2_start - sync_start;
			cerr << "second sync " << sync2_start << " " << sync2_len << " " << linelen << endl;

			// check sync lengths and distance between syncs to see if we've got a regular line
			if ((fabs(linelen - hlen) < (hlen * .05)) && 
/*			    (sync2_len > (16 * freq)) && (sync2_len < (18 * freq)) && */
			    (sync_len > (15 * freq)) && (sync_len < (20 * freq)))
			{
				double plevel, plevel2, pphase, pphase2;

				// determine color burst and phase levels of both this and next color bursts

				BurstDetect(&buf[sync_start], 3.5 * dots_usec, 7.5 * dots_usec, plevel, pphase);
				cerr << curline << " start " << sync_start << " burst 1 " << plevel << " " << pphase << endl;
		
				// cerr << sync_len << ' ' << (sync2_start - sync_start + sync2_len) << endl;	
				BurstDetect(&buf[sync_start], (sync2_start - sync_start) + (3.5 * dots_usec), 7.5 * dots_usec, plevel2, pphase2);
				cerr << "burst 2 " << plevel2 << " " << pphase2 << ' ';

				// if available, use the phase data of the next line's burst to determine line length
				if ((plevel > 500) && (plevel2 > 500)) {
					gap = -((pphase2 - pphase) / M_PIl) * 2.0;
					cerr << sync_start << ":" << sync2_start << " " << (((sync2_start - sync_start) > hlen)) << ' ' << gap << endl;
					if (gap < -2) gap += 4;
					if (gap > 2) gap -= 4;
			
					if (((sync2_start - sync_start) > hlen) && (gap < -.5)) gap += 2;
					if (((sync2_start - sync_start) < hlen) && (gap > .5)) gap -= 2;

					cerr << "gap " << gap << endl;
					ScaleOut(buffer, buf, sync_start, hlen + gap);
				
					BurstDetect(buf, 3.5 * dots_usec, 7.5 * dots_usec, plevel, pphase);
					cerr << "gap " << gap << ' ' << "post-scale 1 " << plevel << " " << pphase << endl;
				
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
					gap = sync2_start - sync_start;
				}

				// if this line has a good color burst, adjust phase
				if (plevel > 500) {
					if (linecount % 2) {
						pcon = (-M_PIl / 2) - pphase;
						if (pcon < -M_PIl) {
							pcon = (M_PIl / 2) + (M_PIl - pphase);
						}
						cerr << "- " << pcon << endl;
					} else {
						pcon = (M_PIl / 2) - pphase;
						cerr << "+ " << pcon << endl;
						if (pcon > M_PIl) {
							pcon = (-M_PIl / 2) - (pphase + M_PIl);
							cerr << "+ " << pcon << endl;
						}
					}

					double adjust = (pcon / M_PIl) * 2.02;
					cerr << "adjust " << adjust << " gap " << gap << endl;
					if (adjust < -2) {
						adjust += 4;
						if ((curline == 273) || (curline == 274) || 
						    (curline == 10) || (curline == 11)) { 
//							linecount++;
						}
					}
					if (adjust > 2) {
						adjust -= 4;
						if ((curline == 273) || (curline == 274) || 
						    (curline == 10) || (curline == 11)) { 
//							linecount++;
						}
					}
//					cerr << "adjust " << adjust << " gap " << gap << endl;
				
					ScaleOut(buffer, buf, sync_start - 16 + adjust, hlen + gap);
					BurstDetect(buf, 3.5 * dots_usec, 7.5 * dots_usec, plevel, pphase);
					int new_sync_len = 0;
					int new_sync_start = FindHSync(buf, 0, bufsize / sfreq, new_sync_len);
					cerr << "adjust " << adjust << " gap " << gap << " post-scale 2 " << plevel << " " << new_sync_start << " " << pphase << endl;
					
					if (new_sync_start != 15) {	
						adjust += (new_sync_start - 15);
						ScaleOut(buffer, buf, sync_start - 16 + adjust, hlen + gap);
						new_sync_start = FindHSync(buf, 0, bufsize / sfreq, new_sync_len);
						cerr << "adjust " << adjust << " gap " << gap << " post-scale 3 " << plevel << " " << new_sync_start << " " << pphase << endl;
					}
				} else {
					cerr << "WARN:  No first burst found\n";
				}
			} else {
				cerr << "special line" << endl; 

				if (((curline > 23) && (curline < 260)) || 
				    ((curline > 290) && (curline < 520))) {
					cerr << "ERR " << scount << endl;
				}

				cerr << sync_len / freq << " " << (sync2_start - sync_start) / freq << endl;

				if ((sync_len > (15 * freq)) &&
				    (sync_len < (18 * freq)) &&
				    (sync2_len < (10 * freq)) &&
				    ((sync2_start - sync_start) < (freq * 125)) &&
				    ((sync2_start - sync_start) > (freq * 110))) {
					curline = 263;
				}

				ScaleOut(buffer, buf, sync_start, hlen);
			}
	
			cerr << curline << endl;
	
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
					memcpy(&frame[NTSCLineLoc[curline] * hleni], buf, hleni * 2);
				
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
					linecount = -1;
					if (fieldcount < 0) fieldcount = 0;
					if (!write_locs) {
						write_locs = 1;
					}
				}
			}
			if (linecount >= 0) linecount++;

			scount += sync_start - 64 + hleni;
			return (sfreq * (sync_start - 64 + hleni));
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

