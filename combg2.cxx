/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"
#include "deemp.h"

int ofd = 1;
char *image_base = "FRAME";

bool f_write8bit = false;
bool f_pulldown = false;
bool f_writeimages = false;
bool f_bw = false;
bool f_debug2d = false;
bool f_oneframe = false;

int debug_line = -1000;
	
int dim = 2;

// NTSC properties
const double freq = 4.0;
const double hlen = 227.5 * freq; 
const int hleni = (int)hlen; 

const double dotclk = (1000000.0*(315.0/88.0)*freq); 

const double dots_usec = dotclk / 1000000.0; 

// values for horizontal timings 
const double line_blanklen = 10.9 * dots_usec;

double irescale = 327.67;
double irebase = 1;
inline uint16_t ire_to_u16(double ire);

// tunables

int linesout = 480;

double brightness = 240;

double black_ire = 7.5;
int black_u16 = ire_to_u16(black_ire);
int white_u16 = ire_to_u16(100); 

double nr_y = 4.0;
double nr_c = 0.0;

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

	YIQ operator*=(double x) {
		YIQ o;

		o.y = this->y * x;
		o.i = this->i * x;
		o.q = this->q * x;

		return o;
	}
	
	YIQ operator+=(YIQ p) {
		YIQ o;

		o.y = this->y + p.y;
		o.i = this->i + p.i;
		o.q = this->q + p.q;

		return o;
	}
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
	
	return -60 + ((double)(level - irebase) / irescale); 
}

struct RGB {
        double r, g, b;

        void conv(YIQ _y) {
               YIQ t;

		double y = u16_to_ire(_y.y);
		y = (y - black_ire) * (100 / (100 - black_ire)); 

		double i = (_y.i) / irescale;
		double q = (_y.q) / irescale;

                r = y + (1.13983 * q);
                g = y - (0.58060 * q) - (i * 0.39465);
                b = y + (i * 2.032);
		
		double m = brightness * 256 / 100;

                r = clamp(r * m, 0, 65535);
                g = clamp(g * m, 0, 65535);
                b = clamp(b * m, 0, 65535);
     };
};

inline uint16_t ire_to_u16(double ire)
{
	if (ire <= -60) return 0;
	
	return clamp(((ire + 60) * irescale) + irebase, 1, 65535);
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

		uint16_t output[744 * 505 * 3];
		uint16_t obuf[744 * 505 * 3];

		uint16_t rawbuffer[3][844 * 505];
		double LPraw[3][844 * 505];

		double aburstlev;	// average color burst

		cline_t cbuf[525];
		cline_t prevbuf[525];

		Filter *f_hpy, *f_hpi, *f_hpq;
		Filter *f_hpvy, *f_hpvi, *f_hpvq;

		void LPFrame(int fnum)
		{
			for (int l = 24; l < 505; l++) {
				for (int h = 32; h < 844; h++) {
					LPraw[fnum][(l * 844) + h - 16] = f_lpf_comb.feed(rawbuffer[fnum][(l * 844) + h]);
				}
			}
		}
	
		void Split(int dim) 
		{
			double lp[844 * 505];
			int f = 1;
			
			if (dim < 3) f = 0;
		
			for (int l = 0; l < 24; l++) {
				uint16_t *line = &rawbuffer[f][l * 844];	
					
				for (int h = 4; h < 840; h++) {
					cbuf[l].p[h].y = line[h]; 
					cbuf[l].p[h].i = 0; 
					cbuf[l].p[h].q = 0; 
				}
			}
		
			double d1buffer[505][844];
			// precompute 1D comb filter, needed for 2D 
			for (int l = 24; l < 505; l++) {
				uint16_t *line = &rawbuffer[f][l * 844];	
				for (int h = 4; h < 840; h++) {
					d1buffer[l][h] = (((line[h + 2] + line[h - 2]) / 2) - line[h]); 
				}
			}

			for (int l = 24; l < 505; l++) {
				uint16_t *line = &rawbuffer[f][l * 844];	
				bool invertphase = (line[0] == 16384);
		
				// shortcuts for previous/next 1D/pixel lines	
				uint16_t *p3line = &rawbuffer[0][l * 844];	
				uint16_t *n3line = &rawbuffer[2][l * 844];	
		
				double *p1line = d1buffer[l - 2];
				double *n1line = d1buffer[l + 2];
		
				double f3 = 0, f2 = 0;
				double si = 0, sq = 0;

				// In 3D mode the 2D is a lower color resolution backup, so it needs more filtering
				Filter f_ti((dim == 3) ? f_colorlp4 : f_colorwlp4);
				Filter f_tq((dim == 3) ? f_colorlp4 : f_colorwlp4);
				int f_toffset = 8;

				double k[840], c_2d[840], c_2df[840];

				// 2D filtering.  can't do top or bottom line - calced between 1d and 3d because this is
				// filtered 
				if (1 && (dim >= 2) && (l >= 2) && (l <= 502)) {
					for (int h = 16; h < 840; h++) {
						double tsi = 0, tsq = 0;
						int phase = h % 4;

						double tc1;

						tc1  = (d1buffer[l][h] - p1line[h]);
						tc1 += (d1buffer[l][h] - n1line[h]);

						tc1 /= (2 * 2);

						double tc1f = tc1;

						if (!invertphase) tc1 = -tc1;

						switch (phase) {
							case 0: tsi = tc1; tc1f = f_ti.feed(tsi); break;
							case 1: tsq = -tc1; tc1f = -f_tq.feed(tsq); break;
							case 2: tsi = -tc1; tc1f = -f_ti.feed(tsi); break;
							case 3: tsq = tc1; tc1f = f_tq.feed(tsq); break;
							default: break;
						}
						
						if (!invertphase) {
							tc1 = -tc1;
							tc1f = -tc1f;
						}
						c_2df[h - f_toffset] = tc1f;
						c_2d[h] = tc1;
					}
				}
	
				for (int h = 4; h < 840; h++) {
					int phase = h % 4;

					double _k;

					double c[3],  v[3];
					double err[3];
						
					int adr = (l * 844) + h;

					if (dim >= 3) {
						c[2] = (p3line[h] - line[h]); 
						c[2] = (((p3line[h] + n3line[h]) / 2) - line[h]); 
						_k = fabs(LPraw[1][adr] - LPraw[0][adr]) + fabs(LPraw[1][adr] - LPraw[2][adr]);
						_k /= irescale;
						k[h] = v[2] = clamp(1 - ((_k - 0) / 12), 0, 1);
						//v[2] = 1;
					} else {
						k[h] = c[2] = v[2] = 0;
					}
				
					if ((dim >= 2) && (l >= 2) && (l <= 502)) {
						c[1] = c_2df[h];
						if (fabs(c_2df[h]) > fabs(c_2d[h])) c[1] = c_2d[h];
						v[1] = 1 - v[2];
					} else {
						c[1] = v[1] = 0;
					}
					
					// 1D 
					if (1) {
						c[0] = d1buffer[l][h];
						v[0] = 1 - v[2] - v[1];
					} else v[0] = 0;
					
					double cavg = 0;

					cavg = c[2] * v[2];
					cavg += (c[1] * v[1]);
					cavg += (c[0] * v[0]);

					cavg /= 2;

					if (f_debug2d) {
						cavg = c[1] - c[2];
					}

					if (!invertphase) cavg = -cavg;

					switch (phase) {
						case 0: si = cavg; break;
						case 1: sq = -cavg; break;
						case 2: si = -cavg; break;
						case 3: sq = cavg; break;
						default: break;
					}

					cbuf[l].p[h].y = line[h]; 
					if (f_debug2d) cbuf[l].p[h].y = ire_to_u16(50); 
					cbuf[l].p[h].i = si;  
					cbuf[l].p[h].q = sq; 

					if (l == (debug_line + 25)) {
						cerr << "E " << h << ' ' << si << ' ' << sq << ' ' << c[1] << ' ' << c[2] << ' ' << k[h] << endl;
					}
				}
			}
		}
					
		void DoYNR() {
			int firstline = (linesout == 505) ? 0 : 23;
			if (nr_y < 0) return;

			for (int l = firstline; l < 505; l++) {
				YIQ hplinef[844], hplineb[844];
				cline_t *input = &cbuf[l];

				for (int h = 70; h <= 752 + 70; h++) {
					hplinef[h].y = f_hpy->feed(input->p[h].y);
				}
				
				for (int h = 760 + 70; h >= 62; h--) {
					hplineb[h].y = f_hpy->feed(input->p[h].y);
				}

				for (int h = 70; h < 744 + 70; h++) {
					double a = hplinef[h + 8].y ; // + hplineb[h - 8].y;

					if (fabs(a) < nr_y) {
						double hpm = (a / nr_y);
						a *= (1 - fabs(hpm * hpm * hpm));
						input->p[h].y -= a;
					}
				}
			}
		}
		
		uint32_t ReadPhillipsCode(uint16_t *line) {
			int first_bit = -1 ;// (int)100 - (1.0 * dots_usec);
			const double bitlen = 2.0 * dots_usec;
			uint32_t out = 0;

			// find first bit
		
			for (int i = 70; (first_bit == -1) && (i < 140); i++) {
				if (u16_to_ire(line[i]) > 90) {
					first_bit = i - (1.0 * dots_usec); 
				}
//				cerr << i << ' ' << line[i] << ' ' << u16_to_ire(line[i]) << ' ' << first_bit << endl;
			}
			if (first_bit < 0) return 0;

			for (int i = 0; i < 24; i++) {
				double val = 0;
	
			//	cerr << dots_usec << ' ' << (int)(first_bit + (bitlen * i) + dots_usec) << ' ' << (int)(first_bit + (bitlen * (i + 1))) << endl;	
				for (int h = (int)(first_bit + (bitlen * i) + dots_usec); h < (int)(first_bit + (bitlen * (i + 1))); h++) {
//					cerr << h << ' ' << line[h] << ' ' << endl;
					val += u16_to_ire(line[h]); 
				}

//				cerr << "bit " << 23 - i << " " << val / dots_usec << ' ' << hex << out << dec << endl;	
				if ((val / dots_usec) > 50) {
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

			aburstlev = -1;

			f_oddframe = false;	
		
			f_hpy = new Filter(f_nr);
			f_hpi = new Filter(f_nrc);
			f_hpq = new Filter(f_nrc);
			
			f_hpvy = new Filter(f_nr);
			f_hpvi = new Filter(f_nrc);
			f_hpvq = new Filter(f_nrc);

			memset(output, 0, sizeof(output));
		}

		void WriteFrame(uint16_t *obuf, int fnum = 0) {
			cerr << "WR" << fnum << endl;
			if (!f_writeimages) {
				if (!f_write8bit) {
					write(ofd, obuf, (744 * linesout * 3) * 2);
				} else {
					uint8_t obuf8[744 * linesout * 3];	

					for (int i = 0; i < (744 * linesout * 3); i++) {
						obuf8[i] = obuf[i] >> 8;
					}
					write(ofd, obuf8, (744 * linesout * 3));
				}		
			} else {
				char ofname[512];

				sprintf(ofname, "%s%d.rgb", image_base, fnum); 
				cerr << "W " << ofname << endl;
				ofd = open(ofname, O_WRONLY | O_CREAT, S_IRUSR | S_IWUSR | S_IROTH);
				write(ofd, obuf, (744 * linesout * 3) * 2);
				close(ofd);
			}
			if (f_oneframe) exit(0);
			frames_out++;
		}
		
		// buffer: 844x505 uint16_t array
		void Process(uint16_t *buffer, int dim = 2)
		{
			int firstline = (linesout == 505) ? 0 : 25;
			int f = (dim == 3) ? 1 : 0;

			cerr << "P " << f << ' ' << dim << endl;

			memcpy(rawbuffer[2], rawbuffer[1], (844 * 505 * 2));
			memcpy(rawbuffer[1], rawbuffer[0], (844 * 505 * 2));
			memcpy(rawbuffer[0], buffer, (844 * 505 * 2));
			
			memcpy(LPraw[2], LPraw[1], (844 * 505 * sizeof(double)));
			memcpy(LPraw[1], LPraw[0], (844 * 505 * sizeof(double)));
		
			memcpy(prevbuf, cbuf, sizeof(cbuf));
	
			LPFrame(0);
		
			if ((dim == 3) && (framecount < 2)) {
				framecount++;
				return;
			} 
	
			Split(dim); 

			// remove color data from baseband (Y)	
			for (int l = firstline; l < 505; l++) {
				bool invertphase = (rawbuffer[f][l * 844] == 16384);

				for (int h = 0; h < 760; h++) {
					double comp;	
					int phase = h % 4;

					YIQ y = cbuf[l].p[h + 70];

					switch (phase) {
						case 0: comp = y.i; break;
						case 1: comp = -y.q; break;
						case 2: comp = -y.i; break;
						case 3: comp = y.q; break;
						default: break;
					}

					if (invertphase) comp = -comp;
					y.y += comp;

					cbuf[l].p[h + 70] = y;
				}
			}
			
			DoYNR();
		
			// YIQ (YUV?) -> RGB conversion	
			for (int l = firstline; l < 505; l++) {
				double burstlev = rawbuffer[f][(l * 844) + 1] / irescale;
				uint16_t *line_output = &output[(744 * 3 * (l - firstline))];
				int o = 0;

				if (burstlev > 5) {
					if (aburstlev < 0) aburstlev = burstlev;	
					aburstlev = (aburstlev * .99) + (burstlev * .01);
				}
//				cerr << "burst level " << burstlev << " mavg " << aburstlev << endl;

				for (int h = 0; h < 752; h++) {
					RGB r;
					YIQ yiq = cbuf[l].p[h + 82];

					yiq.i *= (10 / aburstlev);
					yiq.q *= (10 / aburstlev);

					r.conv(yiq);
					
					if (l == debug_line) {
						r.r = r.g = r.b = 0;
					}
	
					line_output[o++] = (uint16_t)(r.r); 
					line_output[o++] = (uint16_t)(r.g); 
					line_output[o++] = (uint16_t)(r.b); 
				}
			}

			PostProcess(f);
			framecount++;

			return;
		}

		int PostProcess(int fnum) {
			int fstart = -1;

			if (!f_pulldown) {
				fstart = 0;
			} else if (f_oddframe) {
				for (int i = 1; i < linesout; i += 2) {
					memcpy(&obuf[744 * 3 * i], &output[744 * 3 * i], 744 * 3 * 2); 
				}
				WriteFrame(obuf, framecode);
				f_oddframe = false;		
			}

			for (int line = 4; line <= 5; line++) {
				int wc = 0;
				for (int i = 0; i < 700; i++) {
					if (rawbuffer[fnum][(844 * line) + i] > 45000) wc++;
				} 
				if (wc > 500) {
					fstart = (line % 2); 
				}
			}

			for (int line = 16; line < 20; line++) {
				int new_framecode = ReadPhillipsCode(&rawbuffer[fnum][line * 844]); // - 0xf80000;
				int fca = new_framecode & 0xf80000;

				if (((new_framecode & 0xf00000) == 0xf00000) && (new_framecode < 0xff0000)) {
					int ofstart = fstart;

					framecode = new_framecode & 0x0f;
					framecode += ((new_framecode & 0x000f0) >> 4) * 10;
					framecode += ((new_framecode & 0x00f00) >> 8) * 100;
					framecode += ((new_framecode & 0x0f000) >> 12) * 1000;
					framecode += ((new_framecode & 0xf0000) >> 16) * 10000;

					if (framecode > 80000) framecode -= 80000;
	
					cerr << "frame " << framecode << endl;
	
					fstart = (line % 2); 
					if ((ofstart >= 0) && (fstart != ofstart)) {
						cerr << "MISMATCH\n";
					}
				}
			}

			cerr << "FR " << framecount << ' ' << fstart << endl;
			if (!f_pulldown || (fstart == 0)) {
				WriteFrame(output, framecode);
			} else if (fstart == 1) {
				for (int i = 0; i < linesout; i += 2) {
					memcpy(&obuf[744 * 3 * i], &output[744 * 3 * i], 744 * 3 * 2); 
				}
				f_oddframe = true;
				cerr << "odd frame\n";
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
	cerr << "-d [dimensions] : Use 2D/3D comb filtering\n";
	cerr << "-B : B&W output\n";
	cerr << "-f : use separate file for each frame\n";
	cerr << "-p : use white flag/frame # for pulldown\n";	
	cerr << "-l [line] : debug selected line - extra prints for that line, and blacks it out\n";	
	cerr << "-h : this\n";	
}

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1, tproc = 0;
	unsigned short inbuf[844 * 525 * 2];
	unsigned char *cinbuf = (unsigned char *)inbuf;
	int c;

	char out_filename[256] = "";

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;
	
	while ((c = getopt(argc, argv, "8OwvDd:Bb:I:w:i:o:fphn:l:")) != -1) {
		switch (c) {
			case '8':
				f_write8bit = true;
				break;
			case 'd':
				sscanf(optarg, "%d", &dim);
				break;
			case 'D':
				f_debug2d = true;
				dim = 3;
				break;
			case 'O':
				f_oneframe = true;
				break;
			case 'v':
				// copy in VBI area (B&W)
				linesout = 505;
				break;
			case 'B':
				// B&W mode
				f_bw = true;
				dim = 2;
				break;
			case 'b':
				sscanf(optarg, "%lf", &brightness);
				break;
			case 'I':
				sscanf(optarg, "%lf", &black_ire);
				break;
			case 'n':
				sscanf(optarg, "%lf", &nr_y);
				break;
			case 'h':
				usage();
				return 0;
			case 'f':
				f_writeimages = true;	
				break;
			case 'p':
				f_pulldown = true;	
				break;
			case 'i':
				// set input file
				fd = open(optarg, O_RDONLY);
				break;
			case 'o':
				// set output file base name for image mode
				image_base = (char *)malloc(strlen(optarg) + 1);
				strncpy(image_base, optarg, strlen(optarg));
				break;
			case 'l':
				// black out a desired line
				sscanf(optarg, "%d", &debug_line);
				break;
			default:
				return -1;
		} 
	} 

	black_u16 = ire_to_u16(black_ire);
	cerr << ' ' << black_u16 << endl;

	nr_y = nr_y * irescale;
	nr_c = nr_c * irescale;

	if (!f_writeimages && strlen(out_filename)) {
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

