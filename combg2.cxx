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
const double freq = 4.0;
const double hlen = 227.5 * freq; 
const int hleni = (int)hlen; 

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

int linesout = 480;

double brightness = 240;

double black_ire = 7.5;
int black_u16 = level_7_5_ire;
int white_u16 = ire_to_u16(110); 
bool whiteflag_detect = true;

double nr_y = 4.0;
double nr_c = 1.0;

inline double IRE(double in) 
{
	return (in * 140.0) - 40.0;
}

// XXX:  This is actually YUV.
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

inline double u16_to_ire(uint16_t level)
{
	if (level == 0) return -100;
	
	return -40 + ((160.0 / 65533.0) * (double)level); 
}

struct RGB {
        double r, g, b;

        void conv(YIQ _y) {
               YIQ t;
		double y = u16_to_ire(_y.y);
		double i = (_y.i) * (160.0 / 65533.0);
		double q = (_y.q) * (160.0 / 65533.0);

                r = y + (1.13983 * q);
                g = y - (0.58060 * q) - (i * 0.39465);
                b = y + (i * 2.032);
#if 1
		double m = brightness / 100;

                r = clamp(r * m, 0, 255);
                g = clamp(g * m, 0, 255);
                b = clamp(b * m, 0, 255);
#else
		double m = 2.24;

                r = clamp(r * m, -16, 224) + 16;
                g = clamp(g * m, -16, 224) + 16;
                b = clamp(b * m, -16, 224) + 16;
#endif
                //cerr << 'y' << y.y << " i" << y.i << " q" << y.q << ' ';
     };
};

inline uint16_t ire_to_u16(double ire)
{
	if (ire <= -60) return 0;
	if (ire <= -40) return 1;

	if (ire >= 120) return 65535;	

	return (((ire + 40.0) / 160.0) * 65534.0) + 1;
} 

typedef struct cline {
	YIQ p[910];
} cline_t;

int write_locs = -1;

class Comb
{
	protected:
		int linecount;  // total # of lines process - needed to maintain phase
		int curline;    // current line # in frame 

		int framecode;
		int framecount;	

		bool f_oddframe;	// true if frame starts with odd line

		long long scount;	// total # of samples consumed

		int fieldcount;
		int frames_out;	// total # of written frames
	
		uint16_t frame[1820 * 530];

		uint8_t output[744 * 505 * 3];
		uint8_t obuf[744 * 505 * 3];

		uint16_t rawbuffer[3][844 * 505];

		cline_t wbuf[3][525];
		cline_t cbuf[3][525];
		Filter *f_i, *f_q;

		Filter *f_hpy, *f_hpi, *f_hpq;
		Filter *f_hpvy, *f_hpvi, *f_hpvq;

		cline_t Blend(cline_t &prev, cline_t &cur, cline_t &next, bool debug = false) {
			cline_t cur_combed;

			for (int h = 0; h < 844; h++) {
				cur_combed.p[h] = cur.p[h];

				if (debug) cerr << h << ' ' << prev.p[h].i << ' ' << cur.p[h].i << ' ' << next.p[h].i << endl;

				cur_combed.p[h].i = (cur.p[h].i / 2.0) + (prev.p[h].i / 4.0) + (next.p[h].i / 4.0);
				cur_combed.p[h].q = (cur.p[h].q / 2.0) + (prev.p[h].q / 4.0) + (next.p[h].q / 4.0);
			}

			return cur_combed;
		}
		
		cline_t Blend3D(cline_t &prev, cline_t &cur, cline_t &next, bool debug = false) {
			cline_t cur_combed;

			for (int h = 0; h < 844; h++) {
				cur_combed.p[h] = cur.p[h];

				if (debug) cerr << h << ' ' << prev.p[h].y << ' ' << cur.p[h].y << ' ' << next.p[h].y << endl;

				cur_combed.p[h].i = (cur.p[h].i / 2.0) + (prev.p[h].i / 4.0) + (next.p[h].i / 4.0);
				cur_combed.p[h].q = (cur.p[h].q / 2.0) + (prev.p[h].q / 4.0) + (next.p[h].q / 4.0);
			}

			return cur_combed;
		}

		void SplitLine(cline_t &out, uint16_t *line) 
		{
			bool invertphase = (line[0] == 16384);

			double si = 0, sq = 0;

			for (int h = 68; h < 844; h++) {
				int phase = h % 4;

				double prev = line[h - 2];	
				double cur  = line[h];	
				double next = line[h + 2];	

				double c = (cur - ((prev + next) / 2)) / 2;

				if (invertphase) c = -c;

				switch (phase) {
					case 0: si = c; break;
					case 1: sq = -c; break;
					case 2: si = -c; break;
					case 3: sq = c; break;
					default: break;
				}

				if (bw_mode) si = sq = 0;

				out.p[h].y = cur; 
				out.p[h - 4].i = f_i->feed(si); 
				out.p[h - 4].q = f_q->feed(sq); 
			}
		}
					

		void DoCNR(int fnum = 0) {
			if (nr_c < 0) return;

			// part 1:  do horizontal 
			for (int l = 24; l < 504; l++) {
				YIQ hpline[844];
				cline_t *input = &wbuf[fnum][l];

				for (int h = 70; h < 752 + 70; h++) {
					YIQ y = input->p[h]; 

					hpline[h].i = f_hpi->feed(y.i);
					hpline[h].q = f_hpq->feed(y.q);
				}

				for (int h = 70; h < 744 + 70; h++) {
					YIQ a = hpline[h + 8];

					if (fabs(a.i) < nr_c) {
						double hpm = (a.i / nr_c);
						a.i *= (1 - fabs(hpm * hpm * hpm));
						input->p[h].i -= a.i;
					}
					
					if (fabs(a.q) < nr_c) {
						double hpm = (a.q / nr_c);
						a.q *= (1 - fabs(hpm * hpm * hpm));
						input->p[h].q -= a.q;
					}
				}
			}

			for (int p = 0; p < 2; p++) {
				// part 2: vertical
				for (int x = 70; x < 744 + 70; x++) {
					YIQ hpline[505 + 16];

					for (int l = p; l < 505 + 16; l+=2) {
						int rl = (l < 505) ? l + p: 502 + p;

						YIQ y = wbuf[fnum][rl].p[x];
						hpline[l].i = f_hpvi->feed(y.i);
						hpline[l].q = f_hpvq->feed(y.q);
					}
				
					for (int l = p; l < 505; l+=2) {
						YIQ a = hpline[l + 16];
					
						if (fabs(a.i) < nr_c) {
							double hpm = (a.i / nr_c);
							a.i *= (1 - fabs(hpm * hpm * hpm));
							wbuf[fnum][l].p[x].i -= a.i;
						}
					
						if (fabs(a.q) < nr_c) {
							double hpm = (a.q / nr_c);
							a.q *= (1 - fabs(hpm * hpm * hpm));
							wbuf[fnum][l].p[x].q -= a.q;
						}
					}
				}
			}
		}
		
		void DoYNR(int fnum = 0) {
			int firstline = (linesout == 505) ? 0 : 24;
			if (nr_y < 0) return;

			// part 1:  do horizontal 
			for (int l = firstline; l < 504; l++) {
				YIQ hpline[844];
				cline_t *input = &wbuf[fnum][l];

				for (int h = 70; h < 752 + 70; h++) {
					hpline[h].y = f_hpy->feed(input->p[h].y);
				}

				for (int h = 70; h < 744 + 70; h++) {
					YIQ a = hpline[h + 8];

					if (fabs(a.y) < nr_y) {
						double hpm = (a.y / nr_y);
						a.y *= (1 - fabs(hpm * hpm * hpm));
						input->p[h].y -= a.y;
					}
				}
			}
#if 0 // 2D YNR really doesn't work well yet, if ever
			if (!pulldown_mode) return;

			// part 2: vertical
			for (int x = 70; x < 744 + 70; x++) {
				YIQ hpline[505 + 16];

				for (int l = 0; l < 505 + 16; l++) {
					int rl = (l < 505) ? l : 504;

					YIQ y = wbuf[fnum][rl].p[x];
					hpline[l].y = f_hpvy->feed(y.y);
				}
			
				for (int l = 0; l < 505; l++) {
					YIQ *y = &wbuf[fnum][l].p[x];
					YIQ a = hpline[l + 8];
				
					if (fabs(a.y) < _nr_y) {
						double hpm = (a.y / _nr_y);
						a.i *= (1 - fabs(hpm * hpm * hpm));
						wbuf[fnum][l].p[x].y -= a.y;
					}
				}
			}
#endif
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
		Comb() {
			fieldcount = curline = linecount = -1;
			framecode = framecount = frames_out = 0;

			scount = 0;

			f_oddframe = false;	
	
			f_i = new Filter(f_colorlp4);
			f_q = new Filter(f_colorlp4);

			f_hpy = new Filter(f_nr);
			f_hpi = new Filter(f_nrc);
			f_hpq = new Filter(f_nrc);
			
			f_hpvy = new Filter(f_nr);
			f_hpvi = new Filter(f_nrc);
			f_hpvq = new Filter(f_nrc);
		}

		void WriteFrame(uint8_t *obuf, int fnum = 0) {
			if (!image_mode) {
				write(ofd, obuf, (744 * linesout * 3));
			} else {
				char ofname[512];

				sprintf(ofname, "%s%d.rgb", image_base, fnum); 
				cerr << "W " << ofname << endl;
				ofd = open(ofname, O_WRONLY | O_CREAT, S_IRUSR | S_IWUSR | S_IROTH);
				write(ofd, obuf, (744 * linesout * 3));
				close(ofd);
			}
		}
		
		// buffer: 844x505 uint16_t array
		void Process(uint16_t *buffer, int dim = 2)
		{
			int firstline = (linesout == 505) ? 0 : 24;
			int f = (dim == 3) ? 1 : 0;

			cerr << "P " << f << endl;

			memcpy(wbuf[2], wbuf[1], sizeof(cline_t) * 505);
			memcpy(wbuf[1], wbuf[0], sizeof(cline_t) * 505);

			memcpy(rawbuffer[2], rawbuffer[1], (844 * 505 * 2));
			memcpy(rawbuffer[1], rawbuffer[0], (844 * 505 * 2));
			memcpy(rawbuffer[0], buffer, (844 * 505 * 2));

			for (int l = firstline; l < 504; l++) {
				SplitLine(wbuf[0][l], &rawbuffer[0][l * 844]); 
			}

			DoCNR(0);	
			
			if (framecount == 0) {
				f = 0;
				if (dim > 2) dim = 2;
			}

			if ((f == 1) && framecount == 1) {
				framecount++;
				return;
			}

			// comb filtering phase
			for (int l = firstline; l < 504; l++) {
				if (dim == 1) {
					memcpy(&cbuf[f][l], &wbuf[0][l], sizeof(cline_t));
				} else if (dim == 2) {
					if ((l >= 24) && (l < 503)) 
						cbuf[f][l] = Blend(wbuf[0][l - 2], wbuf[0][l], wbuf[0][l + 2]);
					else
						memcpy(&cbuf[f][l], &wbuf[0][l], sizeof(cline_t));
				} else {
					cbuf[f][l] = Blend3D(wbuf[0][l], wbuf[1][l], wbuf[2][l], (l == 50));
				}
			}

			// remove color data from baseband (Y)	
			for (int l = firstline; l < 504; l++) {
				bool invertphase = (rawbuffer[f][l * 844] == 16384);

				for (int h = 0; h < 760; h++) {
					double comp;	
					int phase = h % 4;

					YIQ y = cbuf[f][l].p[h + 70];

					switch (phase) {
						case 0: comp = y.i; break;
						case 1: comp = -y.q; break;
						case 2: comp = -y.i; break;
						case 3: comp = y.q; break;
						default: break;
					}

					if (invertphase) comp = -comp;
					y.y += comp;

					wbuf[f][l].p[h + 70] = y;
				}
			}
			
			DoYNR(f);
		
			// YIQ (YUV?) -> RGB conversion	
			for (int l = firstline; l < 504; l++) {
				uint8_t *line_output = &output[(744 * 3 * (l - firstline))];
				int o = 0;
				for (int h = 0; h < 752; h++) {
					RGB r;
					
					r.conv(wbuf[f][l].p[h + 70]);

                                       if (1 && l == 50) {
                                               double y = u16_to_ire(wbuf[f][l].p[h + 70].y);
                                               double i = (wbuf[f][l].p[h + 70].i) * (160.0 / 65533.0);
                                               double q = (wbuf[f][l].p[h + 70].q) * (160.0 / 65533.0);

                                               double m = ctor(q, i);
                                               double a = atan2(q, i);

                                               a *= (180 / M_PIl);
                                               if (a < 0) a += 360;

                                               cerr << h << ' ' << y << ' ' << i << ' ' << q << ' ' << m << ' ' << a << ' '; 
                                               cerr << r.r << ' ' << r.g << ' ' << r.b << endl;
                                       }

					line_output[o++] = (uint8_t)(r.r); 
					line_output[o++] = (uint8_t)(r.g); 
					line_output[o++] = (uint8_t)(r.b); 
				}
			}

			PostProcess(f);
			framecount++;

			return;
		}

		int PostProcess(int fnum) {
			int fstart = -1;

			if (!pulldown_mode) {
				fstart = 0;
			} else if (f_oddframe) {
				for (int i = 0; i <= linesout; i += 2) {
					memcpy(&obuf[744 * 3 * i], &output[744 * 3 * i], 744 * 3); 
				}
				WriteFrame(obuf, framecode);
				f_oddframe = false;		
			}

			for (int line = 2; line <= 3; line++) {
				int wc = 0;
				for (int i = 0; i < 700; i++) {
					if (rawbuffer[fnum][(844 * line) + i] > 45000) wc++;
				} 
				if (wc > 500) {
					fstart = (line % 2); 
				}
				cerr << "PW" << line << ' ' << wc << ' ' << fieldcount << endl;
			}

			for (int line = 14; line <= 17; line++) {
				int new_framecode = ReadPhillipsCode(&rawbuffer[fnum][line * 844]) - 0xf80000;

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

			cerr << "FR " << framecount << ' ' << fstart << endl;
			if (!pulldown_mode || (fstart == 0)) {
				WriteFrame(output, framecode);
			} else if (fstart == 1) {
				memcpy(obuf, output, sizeof(output));
				f_oddframe = true;
			}

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
	unsigned short inbuf[844 * 525 * 2];
	unsigned char *cinbuf = (unsigned char *)inbuf;
	int c;

	int dim = 2;

	char out_filename[256] = "";

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;
	
	while ((c = getopt(argc, argv, "vd:Bb:l:w:i:o:fphn:N:")) != -1) {
		switch (c) {
			case 'd':
				sscanf(optarg, "%d", &dim);
				break;
			case 'v':
				linesout = 505;
				break;
			case 'B':
				bw_mode = true;
				break;
			case 'b':
				sscanf(optarg, "%lf", &brightness);
				break;
			case 'l':
				sscanf(optarg, "%lf", &black_ire);
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

	black_u16 = ire_to_u16(black_ire);

	nr_y = (nr_y / 160.0) * 65534.0;
	nr_c = (nr_c / 160.0) * 65534.0;

	if (!image_mode && strlen(out_filename)) {
		ofd = open(image_base, O_WRONLY | O_CREAT);
	}

	cout << std::setprecision(8);

	int bufsize = 844 * 505 * 2;

	rv = read(fd, inbuf, bufsize);
	while ((rv > 0) && (rv < bufsize)) {
		int rv2 = read(fd, &cinbuf[rv], bufsize - rv);
		if (rv2 <= 0) exit(0);
		rv += rv2;
	}

	while (rv == bufsize && ((tproc < dlen) || (dlen < 0))) {
		comb.Process(inbuf, dim);
	
		rv = read(fd, inbuf, bufsize);
		while ((rv > 0) && (rv < bufsize)) {
			int rv2 = read(fd, &cinbuf[rv], bufsize - rv);
			if (rv2 <= 0) exit(0);
			rv += rv2;
		}
	}

	return 0;
}

