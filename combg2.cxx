/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"
#include "deemp.h"

// capture frequency and fundamental NTSC color frequency
//const double CHZ = (1000000.0*(315.0/88.0)*8.0);
//const double FSC = (1000000.0*(315.0/88.0));

bool pulldown_mode = false;
int ofd = 1;
bool image_mode = false;
char *image_base = "FRAME";
bool bw_mode = false;

// NTSC properties
const double freq = 4.0;	// in FSC.  Must be an even number!

const double hlen = 227.5 * freq;
const int    hleni = (int)hlen;
const double dotclk = (1000000.0*(315.0/88.0)*freq); 

const double dots_usec = dotclk / 1000000.0; 

// values for horizontal timings 
const double line_blanklen = 10.9 * dots_usec;

inline uint16_t ire_to_u16(double ire);

// uint16_t levels
uint16_t level_m40ire = 1;
uint16_t level_0ire = 16384;
uint16_t level_7_5_ire = 16384+3071;
uint16_t level_100ire = 57344;
uint16_t level_120ire = 65535;

// tunables

double black_ire = 7.5;
int black_u16 = level_7_5_ire;
int white_u16 = ire_to_u16(110); 
bool whiteflag_detect = true;

double nr_y = 2.0;
double nr_c = 0.5;

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
		YIQ t;

		t.y = (y.y - black_u16) * 1.43;
		t.i = y.i * 1.43;
		t.q = y.q * 1.43;

                r = (t.y * 1.164) + (1.596 * t.i);
                g = (t.y * 1.164) - (0.813 * t.i) - (t.q * 0.391);
                b = (t.y * 1.164) + (t.q * 2.018);

                r = clamp(r / 256, 0, 255);
                g = clamp(g / 256, 0, 255);
                b = clamp(b / 256, 0, 255);
                //cerr << 'y' << y.y << " i" << y.i << " q" << y.q << ' ';
                //cerr << 'r' << r << " g" << g << " b" << b << endl;
        };
};

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

	return (((ire + 40.0) / 160.0) * 65534.0) + 1;
} 

typedef struct cline {
	double y[hleni]; // Y
	double m[hleni]; // IQ magnitude
	double a[hleni]; // IQ phase angle
	double i[hleni]; // IQ phase angle
	double q[hleni]; // IQ phase angle
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
		uint8_t obuf[744 * 525 * 3];
		uint8_t tmp_obuf[744 * 525 * 3];

		double blevel[525];

		double _cos[525][16], _sin[525][16];
		cline_t wbuf[3][525];
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;

		Filter *f_hpy, *f_hpi, *f_hpq;

		cline_t Blend(cline_t &prev, cline_t &cur, cline_t &next) {
			cline cur_combed;

			int counter = 0;
			for (int h = 0; counter < 852; h++) {
				cur_combed.y[h] = cur.y[h];
				cur_combed.i[h] = cur.i[h];
				cur_combed.q[h] = cur.q[h];

				cur_combed.i[h] = (cur.i[h] / 2.0) + (prev.i[h] / 4.0) + (next.i[h] / 4.0);
				cur_combed.q[h] = (cur.q[h] / 2.0) + (prev.q[h] / 4.0) + (next.q[h] / 4.0);

				cur_combed.m[h] = ctor(cur_combed.i[h], cur_combed.q[h]); 
				cur_combed.a[h] = atan2(cur_combed.i[h], cur_combed.q[h]); 
				counter++;
			}

			return cur_combed;
		}

		// buffer: 852x505 uint16_t array
		void CombFilter(uint16_t *buffer, uint8_t *output)
		{
			YIQ outline[852], hpline[852];
			for (int l = 24; l < 504; l++) {
				uint16_t *line = &buffer[l * 852];
				bool invertphase = (line[0] == 16384);

				double si = 0, sq = 0;

				for (int h = 68; h < 852; h++) {
					int phase = h % 4;

					double prev = line[h - 2];	
					double cur  = line[h];	
					double next = line[h - 2];	

					double c = (cur - ((prev + next) / 2)) / 2;

					if (invertphase) c = -c;

					switch (phase) {
						case 0: sq = c; break;
						case 1: si = -c; break;
						case 2: sq = -c; break;
						case 3: si = c; break;
						default: break;
					}

					if (bw_mode) si = sq = 0;

					wbuf[0][l].y[h] = cur; 
					wbuf[0][l].i[h - 9] = f_i->feed(si); 
					wbuf[0][l].q[h - 9] = f_q->feed(sq); 
				}
			}

			for (int l = 24; l < 504; l++) {
				bool invertphase = (buffer[l * 852] == 16384);
				cline_t line;
				int o = 0;

				if (l < 503) 
					line = Blend(wbuf[0][l - 2], wbuf[0][l], wbuf[0][l + 2]);
				else
					memcpy(&line, &wbuf[0][l], sizeof(cline_t));
		
				uint8_t *line_output = &output[(744 * 3 * (l - 24))];
//				cerr << l << ' ' << (744 * 3 * (l - 24)) << endl;

				// only need 744 for deocding, but need extra space for the NR filter
				for (int h = 0; h < 760; h++) {
					double comp;	
					int phase = h % 4;
					YIQ y;
					RGB r;

					y.y = line.y[h + 70];
					y.i = line.i[h + 70];
					y.q = line.q[h + 70];

					switch (phase) {
						case 0: comp = y.q; break;
						case 1: comp = -y.i; break;
						case 2: comp = -y.q; break;
						case 3: comp = y.i; break;
						default: break;
					}

					if (invertphase) comp = -comp;
					y.y -= comp;

					hpline[h].y = clamp(f_hpy->feed(y.y), -nr_y, nr_y);
					hpline[h].i = clamp(f_hpi->feed(y.i), -nr_c, nr_c);
					hpline[h].q = clamp(f_hpq->feed(y.q), -nr_c, nr_c);

					outline[h] = y;
				}

				for (int h = 0; h < 760; h++) {
					RGB r;

//					cerr << h << ' ' << outline[h].y << ' ' << nr_y << ' ' << hpline[h + 8].y << endl;

					outline[h].y -= hpline[h+8].y;
					outline[h].i -= hpline[h+8].i;
					outline[h].q -= hpline[h+8].q;
					r.conv(outline[h]);

//					if ((l == 50) && !(h % 20)) {
//						cerr << h << ' ' << (int)(outline[h+32].y * 65536) << ' ' << (int)(outline[h+32].i * 65536) << ' ' << (int)(outline[h+32].q * 65536) << ' ' << r.r << ' ' << r.g << ' ' << r.b << endl;
//					}
//					cerr << l << ' ' << (744 * 3 * (l - 24)) << ' ' << o << ' ' << (r.r * 255.0) << endl;

					line_output[o++] = (uint8_t)(r.r); 
					line_output[o++] = (uint8_t)(r.g); 
					line_output[o++] = (uint8_t)(r.b); 
				}
			}

			return;
		}

		uint32_t ReadPhillipsCode(uint16_t *line) {
			const int first_bit = (int)73;
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
	
			f_i = new Filter(f_colorlp4);
			f_q = new Filter(f_colorlp4);

			f_hpy = new Filter(f_nr);
			f_hpi = new Filter(f_nrc);
			f_hpq = new Filter(f_nrc);
		}

		void WriteFrame(uint8_t *obuf, int fnum = 0) {
			if (!image_mode) {
				write(ofd, obuf, (744 * 480 * 3));
			} else {
				char ofname[512];

				sprintf(ofname, "%s%d.rgb", image_base, fnum); 
				cerr << "W " << ofname << endl;
				ofd = open(ofname, O_WRONLY | O_CREAT, S_IRUSR | S_IWUSR | S_IROTH);
				write(ofd, obuf, (744 * 480 * 3));
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
					memcpy(&obuf[744 * 3 * i], &tmp_obuf[744 * 3 * i], 744 * 3); 
				}
				WriteFrame(obuf, framecode);
				f_oddframe = false;		
			}

			for (int line = 2; line <= 3; line++) {
				int wc = 0;
				for (int i = 0; i < 700; i++) {
					if (buffer[(852 * line) + i] > 45000) wc++;
				} 
				if (wc > 500) {
					fstart = (line % 2); 
				}
				cerr << "PW" << line << ' ' << wc << ' ' << fieldcount << endl;
			}

			for (int line = 14; line <= 17; line++) {
				int new_framecode = ReadPhillipsCode(&buffer[line * 852]) - 0xf80000;

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
	unsigned short inbuf[852 * 525 * 2];
	unsigned char *cinbuf = (unsigned char *)inbuf;
	int c;

	char out_filename[256] = "";

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;
	
	while ((c = getopt(argc, argv, "Bb:w:i:o:fphn:N:")) != -1) {
		switch (c) {
			case 'B':
				bw_mode = true;
				break;
			case 'b':
				sscanf(optarg, "%d", &black_u16);
				break;
			case 'n':
				sscanf(optarg, "%lf", &nr_y);
				break;
			case 'N':
				sscanf(optarg, "%lf", &nr_c);
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

	nr_y = (nr_y / 160.0) * 65534.0;
	nr_c = (nr_c / 160.0) * 65534.0;

	if (!image_mode && strlen(out_filename)) {
		ofd = open(image_base, O_WRONLY | O_CREAT);
	}

	cout << std::setprecision(8);

	int bufsize = 852 * 505 * 2;

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

