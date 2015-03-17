/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"
#include "deemp.h"

#include <opencv2/core/core.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <opencv2/imgproc/imgproc.hpp>

using namespace cv;

int ofd = 1;
char *image_base = "FRAME";

bool f_write8bit = false;
bool f_pulldown = false;
bool f_writeimages = false;
bool f_bw = false;
bool f_debug2d = false;
bool f_oneframe = false;

bool f_monitor = false;

double p_3dcore = 1.25;
double p_3drange = 5.5;
double p_3d2drej = 2;

int debug_line = -1000;
	
int dim = 2;

// NTSC properties
const double freq = 4.0;
//const double hlen = 227.5 * freq; 
//const int hleni = (int)hlen; 

const double dotclk = (1000000.0*(315.0/88.0)*freq); 
const double dots_usec = dotclk / 1000000.0; 

// values for horizontal timings 
//const double line_blanklen = 10.9 * dots_usec;

double irescale = 327.67;
double irebase = 1;
inline uint16_t ire_to_u16(double ire);

// tunables

int linesout = 480;

double brightness = 240;

double black_ire = 7.5;
int black_u16 = ire_to_u16(black_ire);
int white_u16 = ire_to_u16(100); 

double nr_y = 1.0;

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

const int nframes = 3;	// 3 frames needed for 3D buffer - for now

const int in_y = 505;
const int in_x = 844;
const int in_size = in_y * in_x;
const int out_x = 744;

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

		uint16_t output[out_x * in_y * 3];
		uint16_t BGRoutput[out_x * in_y * 3];
		uint16_t obuf[out_x * in_y * 3];

		double combbuffer[nframes][3][in_y][in_x];
		double combk[nframes][3][in_y][in_x];

		uint16_t rawbuffer[nframes][in_x * in_y];
		double LPraw[nframes][in_x * in_y];

		double aburstlev;	// average color burst

		cline_t cbuf[in_y];
		cline_t tbuf[in_y];
		cline_t prevbuf[in_y];

		Filter *f_hpy, *f_hpi, *f_hpq;
		Filter *f_hpvy, *f_hpvi, *f_hpvq;

		void LPFrame(int fnum)
		{
			for (int l = 24; l < in_y; l++) {
				for (int h = 32; h < in_x; h++) {
					LPraw[fnum][(l * in_x) + h - 16] = f_lpf_comb.feed(rawbuffer[fnum][(l * in_x) + h]);
				}
			}
		}

		void ColorProc(int frame, int dim)
		{

		}

		// precompute 1D comb filter, needed for 2D and optical flow 
		void Split1D(int frame)
		{
			for (int l = 24; l < in_y; l++) {
				uint16_t *line = &rawbuffer[frame][l * in_x];	
				bool invertphase = (line[0] == 16384);

				Filter f_1di((dim == 3) ? f_colorwlp4 : f_colorwlp4);
				Filter f_1dq((dim == 3) ? f_colorwlp4 : f_colorwlp4);
				int f_toffset = 8;

				for (int h = 4; h < 840; h++) {
					int phase = h % 4;
					double tc1 = (((line[h + 2] + line[h - 2]) / 2) - line[h]); 
					double tc1f = 0, tsi = 0, tsq = 0;

					if (!invertphase) tc1 = -tc1;
						
					switch (phase) {
						case 0: tsi = tc1; tc1f = f_1di.feed(tsi); break;
						case 1: tsq = -tc1; tc1f = -f_1dq.feed(tsq); break;
						case 2: tsi = -tc1; tc1f = -f_1di.feed(tsi); break;
						case 3: tsq = tc1; tc1f = f_1dq.feed(tsq); break;
						default: break;
					}
						
					if (!invertphase) {
						tc1 = -tc1;
						tc1f = -tc1f;
					}

					combbuffer[frame][0][l][h - f_toffset] = tc1f;					

					if (l == (debug_line + 25)) {
						cerr << h << ' ' << line[h - 4] << ' ' << line[h - 2] << ' ' << line[h] << ' ' << line[h + 2] << ' ' << line[h + 4] << ' ' << tc1 << ' ' << combbuffer[frame][0][l][h - f_toffset] << endl;
					}
				}
			}
		}
	
		void Split23D(int f, int dim) 
		{
			for (int l = 24; l < in_y; l++) {
				uint16_t *line = &rawbuffer[f][l * in_x];	
		
				// shortcuts for previous/next 1D/pixel lines	
				uint16_t *p3line = &rawbuffer[0][l * in_x];	
				uint16_t *n3line = &rawbuffer[2][l * in_x];	
		
				double *p1line = combbuffer[f][0][l - 2];
				double *n1line = combbuffer[f][0][l + 2];
		
				// 2D filtering.  can't do top or bottom line - calced between 1d and 3d because this is
				// filtered 
				if (1 && (dim >= 2) && (l >= 4) && (l <= 503)) {
					for (int h = 16; h < 840; h++) {
						double tc1;

						if (l == (debug_line + 25)) {
							//cerr << "2D " << h << ' ' << combbuffer[l][h] << ' ' << p1line[h] << ' ' << n1line[h] << endl;
							cerr << "2D " << h << ' ' << p1line[h] << ' ' << combbuffer[f][0][l][h] << ' ' << n1line[h] << ' ' << endl;
						}	

						tc1  = (combbuffer[f][0][l][h] - p1line[h]);
						tc1 += (combbuffer[f][0][l][h] - n1line[h]);
						tc1 /= (2 * 2);

						combbuffer[f][1][l][h] = tc1;
					}
				}

				// a = fir1(16, 0.1); printf("%.15f, ", a)
				Filter lp_3d({0.005719569452904, 0.009426612841315, 0.019748592575455, 0.036822680065252, 0.058983880135427, 0.082947830292278, 0.104489989820068, 0.119454688318951, 0.124812312996699, 0.119454688318952, 0.104489989820068, 0.082947830292278, 0.058983880135427, 0.036822680065252, 0.019748592575455, 0.009426612841315, 0.005719569452904}, {1.0});

				// need to prefilter K using a LPF
				double _k[in_x];
				for (int h = 4; (dim >= 3) && (h < 840); h++) {
					int adr = (l * in_x) + h;

					double __k = abs(rawbuffer[0][adr] - rawbuffer[2][adr]); 
					__k += abs((rawbuffer[1][adr] - rawbuffer[2][adr]) - (rawbuffer[1][adr] - rawbuffer[0][adr])); 

					if (h > 12) _k[h - 8] = lp_3d.feed(__k);
					if (h >= 836) _k[h] = __k;
				}
	
				for (int h = 4; h < 840; h++) {
					if (dim >= 3) {
						double k2 = abs(p1line[h] - n1line[h]) / (irescale * 15); 
						double adj = (p_3d2drej - p_3dcore) * (clamp(k2, 0, 1));
				
						combbuffer[f][2][l][h] = (((p3line[h] + n3line[h]) / 2) - line[h]); 
						combk[f][2][l][h] = clamp(1 - ((_k[h] - (p_3dcore + adj)) / p_3drange), 0, 1);
						if (l == (debug_line + 25)) {
//							cerr << "3DC " << h << ' ' << k2 << ' ' << adj << ' ' << k[h] << endl;
						}
					}
				
					if ((dim >= 2) && (l >= 2) && (l <= 502)) {
						combk[f][1][l][h] = 1 - combk[f][2][l][h];
					}
					
					// 1D 
					combk[f][0][l][h] = 1 - combk[f][2][l][h] - combk[f][1][l][h];
				}
			}	
		}	

		void SplitIQ(int f) {
			double mse = 0.0;
			double me = 0.0;
			for (int l = 24; l < in_y; l++) {
				double msel = 0.0, sel = 0.0;
				uint16_t *line = &rawbuffer[f][l * in_x];	
				bool invertphase = (line[0] == 16384);

				double si = 0, sq = 0;
				for (int h = 4; h < 840; h++) {
					int phase = h % 4;
					double cavg = 0;

					cavg += (combbuffer[f][2][l][h] * combk[f][2][l][h]);
					cavg += (combbuffer[f][1][l][h] * combk[f][1][l][h]);
					cavg += (combbuffer[f][0][l][h] * combk[f][0][l][h]);

					cavg /= 2;
					
					if (f_debug2d) {
						cavg = combbuffer[f][1][l][h] - combbuffer[f][2][l][h];
						msel += (cavg * cavg);
						sel += fabs(cavg);
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
//						_k = fabs(LPraw[1][adr - (in_x * 2)] - LPraw[1][adr]) + fabs(LPraw[1][adr + (in_x * 2)] - LPraw[1][adr]);
//						cerr << h << ' ' << combbuffer[f][1][l][h] - combbuffer[f][2][l][h] << ' ' << c[1] << ' ' << c[2] << ' ' << LPraw[1][adr - (in_x * 2)] << ' ' << LPraw[1][adr] << ' ' << LPraw[1][adr + (in_x * 2)] << endl;
					}						
						
					if (f_bw) {
						cbuf[l].p[h].i = cbuf[l].p[h].q = 0;  
					}

					if (l == (debug_line + 25)) {
//						cerr << "E " << h << ' ' << si << ' ' << sq << ' ' << c[1] << ' ' << c[2] << ' ' << k[h] << endl;
					}
				}
				if (f_debug2d && (l >= 6) && (l <= 500)) {
					cerr << l << ' ' << msel / (840 - 4) << " ME " << sel / (840 - 4) << endl; 
					mse += msel / (840 - 4);
					me += sel / (840 - 4);
				}
			}
			if (f_debug2d) {
				cerr << "TOTAL MSE " << mse << " ME " << me << endl;
			}
		}
					
		void DoYNR() {
			int firstline = (linesout == in_y) ? 0 : 23;
			if (nr_y < 0) return;

			for (int l = firstline; l < in_y; l++) {
				YIQ hplinef[in_x];
				cline_t *input = &cbuf[l];

				for (int h = 70; h <= 752 + 80; h++) {
					hplinef[h].y = f_hpy->feed(input->p[h].y);
				}
				
				for (int h = 70; h < out_x + 70; h++) {
					double a = hplinef[h + 12].y;

					if (l == (debug_line + 25)) {
						cerr << "NR " << h << ' ' << input->p[h].y << ' ' << hplinef[h + 12].y << ' ' << ' ' << a << ' ' ;
					}

					if (fabs(a) > nr_y) {
						a = (a > 0) ? nr_y : -nr_y;
					}

					if (fabs(a) <= nr_y) {
//						double hpm = (a / nr_y);
//						a *= (1 - fabs(hpm * hpm * hpm));
						input->p[h].y -= a;
						if (l == (debug_line + 25)) cerr << a << ' ' << input->p[h].y << endl; 
					} else if (l == (debug_line + 25)) cerr << endl;
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


		void ToRGB(int f, int firstline) {
			// YIQ (YUV?) -> RGB conversion	
			for (int l = firstline; l < in_y; l++) {
				double burstlev = rawbuffer[f][(l * in_x) + 1] / irescale;
				uint16_t *line_output = &output[(out_x * 3 * (l - firstline))];
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
					write(ofd, obuf, (out_x * linesout * 3) * 2);
				} else {
					uint8_t obuf8[out_x * linesout * 3];	

					for (int i = 0; i < (out_x * linesout * 3); i++) {
						obuf8[i] = obuf[i] >> 8;
					}
					write(ofd, obuf8, (out_x * linesout * 3));
				}		
			} else {
				char ofname[512];

				sprintf(ofname, "%s%d.rgb", image_base, fnum); 
				cerr << "W " << ofname << endl;
				ofd = open(ofname, O_WRONLY | O_CREAT, S_IRUSR | S_IWUSR | S_IROTH);
				write(ofd, obuf, (out_x * linesout * 3) * 2);
				close(ofd);
			}

			if (f_monitor) {
				// OpenCV wants BGR, not RGB

				for (int y = 0; y < 480; y++) {
					for (int x = 0; x < out_x; x++) {
						BGRoutput[(((y * out_x) + x) * 3) + 0] = obuf[(((y * out_x) + x) * 3) + 2];
						BGRoutput[(((y * out_x) + x) * 3) + 1] = obuf[(((y * out_x) + x) * 3) + 1];
						BGRoutput[(((y * out_x) + x) * 3) + 2] = obuf[(((y * out_x) + x) * 3) + 0];
//						pic.at<Scalar_<uint16_t>>(x,y) = Scalar_<uint16_t>(obuf[(((y * out_x) + x) * 3) + 2], obuf[(((y * out_x) + x) * 3) + 1], obuf[(((y * out_x) + x) * 3) + 0]); 
					}
				}
				
				Mat pic = Mat(480, out_x, CV_16UC3, BGRoutput);
				Mat rpic;

				resize(pic, rpic, Size(1280,960));

				imshow("comb", rpic);	
				waitKey(f_oneframe ? 0 : 1);
			}

			if (f_oneframe) exit(0);
			frames_out++;
		}

		void AdjustY(int f, cline_t cbuf[in_y]) {
			int firstline = (linesout == in_y) ? 0 : 25;
			// remove color data from baseband (Y)	
			for (int l = firstline; l < in_y; l++) {
				bool invertphase = (rawbuffer[f][l * in_x] == 16384);

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

		}
		
		// buffer: in_xxin_y uint16_t array
		void Process(uint16_t *buffer, int dim = 2)
		{
			int firstline = (linesout == in_y) ? 0 : 25;
			int f = (dim == 3) ? 1 : 0;

			cerr << "P " << f << ' ' << dim << endl;

			memcpy(rawbuffer[2], rawbuffer[1], (in_x * in_y * 2));
			memcpy(rawbuffer[1], rawbuffer[0], (in_x * in_y * 2));
			memcpy(rawbuffer[0], buffer, (in_x * in_y * 2));
			
			memcpy(LPraw[2], LPraw[1], (in_x * in_y * sizeof(double)));
			memcpy(LPraw[1], LPraw[0], (in_x * in_y * sizeof(double)));
		
			memcpy(prevbuf, cbuf, sizeof(cbuf));
	
			LPFrame(0);
		
			if ((dim == 3) && (framecount < 2)) {
				framecount++;
				return;
			} 
			
			for (int l = 0; l < 24; l++) {
				uint16_t *line = &rawbuffer[f][l * in_x];	
					
				for (int h = 4; h < 840; h++) {
					cbuf[l].p[h].y = line[h]; 
					cbuf[l].p[h].i = 0; 
					cbuf[l].p[h].q = 0; 
				}
			}
	
			memset(combbuffer[f], 0, sizeof(double) * 3 * in_size);
			memset(combk[f], 0, sizeof(double) * 3 * in_size);
	
			// precompute 1D comb filter, needed for 2D and optical flow 
			Split1D(f);
	
			memcpy(tbuf, cbuf, sizeof(cbuf));	

			// get IQ for 1D 
			SplitIQ(f);
			AdjustY(f, tbuf);

			// Now 2/3D 
			Split23D(f, dim); 
			SplitIQ(f);

			AdjustY(f, cbuf);

			DoYNR();
		
			ToRGB(f, firstline);
	
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
					memcpy(&obuf[out_x * 3 * i], &output[out_x * 3 * i], out_x * 3 * 2); 
				}
				WriteFrame(obuf, framecode);
				f_oddframe = false;		
			}

			for (int line = 4; line <= 5; line++) {
				int wc = 0;
				for (int i = 0; i < 700; i++) {
					if (rawbuffer[fnum][(in_x * line) + i] > 45000) wc++;
				} 
				if (wc > 500) {
					fstart = (line % 2); 
				}
			}

			for (int line = 16; line < 20; line++) {
				int new_framecode = ReadPhillipsCode(&rawbuffer[fnum][line * in_x]); // - 0xf80000;
				//int fca = new_framecode & 0xf80000;

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
					memcpy(&obuf[out_x * 3 * i], &output[out_x * 3 * i], out_x * 3 * 2); 
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
	unsigned short inbuf[in_x * 525 * 2];
	unsigned char *cinbuf = (unsigned char *)inbuf;
	int c;

	char out_filename[256] = "";

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;
	
	while ((c = getopt(argc, argv, "c:r:R:m8OwvDd:Bb:I:w:i:o:fphn:l:")) != -1) {
		switch (c) {
			case 'c':
				sscanf(optarg, "%lf", &p_3dcore);
				break; 
			case 'r':
				sscanf(optarg, "%lf", &p_3drange);
				break; 
			case 'R':
				sscanf(optarg, "%lf", &p_3d2drej);
				break; 
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
				linesout = in_y;
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
				image_base = (char *)malloc(strlen(optarg) + 2);
				strncpy(image_base, optarg, strlen(optarg) + 1);
				break;
			case 'l':
				// black out a desired line
				sscanf(optarg, "%d", &debug_line);
				break;
			case 'm':
				f_monitor = true;
				break;
			default:
				return -1;
		} 
	} 

	if (f_monitor) {
		namedWindow("comb", WINDOW_AUTOSIZE);
	}

	p_3dcore *= irescale;
	p_3drange *= irescale;
	p_3d2drej *= irescale;

	black_u16 = ire_to_u16(black_ire);

	nr_y *= irescale;

	if (!f_writeimages && strlen(out_filename)) {
		ofd = open(image_base, O_WRONLY | O_CREAT);
	}

	cout << std::setprecision(8);

	int bufsize = in_x * in_y * 2;

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

	if (f_monitor) {
		cerr << "Done - waiting for key\n";
		waitKey(0);
	}

	return 0;
}

