/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */


#include "ld-decoder.h"
#include "deemp.h"

#include <opencv2/core/core.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <opencv2/video/tracking.hpp> 

using namespace cv;

int ofd = 1;
char *image_base = "FRAME";

bool f_write8bit = false;
bool f_pulldown = false;
bool f_writeimages = false;
bool f_training = false;
bool f_bw = false;
bool f_debug2d = false;
bool f_adaptive2d = true;
bool f_oneframe = false;
bool f_showk = false;
bool f_wide = false;

bool f_colorlpf = false;
bool f_colorlpf_hq = true;

double nn_cscale = 32768.0;

bool f_monitor = false;

double p_3dcore = -1;
double p_3drange = -1;
double p_2dcore = -1;
double p_2drange = -1;
double p_3d2drej = 2;

bool f_opticalflow = true;

int f_debugline = -1000;
	
int dim = 1;

// NTSC properties
const double freq = 4.0;

double irescale = 327.67;
double irebase = 1;
inline uint16_t ire_to_u16(double ire);

// tunables

int lineoffset = 32;

int linesout = 576;

double brightness = 240;

double black_ire = 40;
int black_u16 = ire_to_u16(black_ire);
int white_u16 = ire_to_u16(100); 

double nr_c = 0.0;
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

int cline = -1;

struct RGB {
        double r, g, b;

        void conv(YIQ _y, double angleadj = 0, int line = 0) {
               YIQ t;

//		angleadj = 0;

		double y = u16_to_ire(_y.y);
		y = (y - black_ire) * (100 / (100 - black_ire)); 

		double i = +(_y.i) / irescale;
		double q = +(_y.q) / irescale;

		double mag = ctor(i, q);
//		if (((line + 1) % 4) >= 2) angleadj -= 65;
		double angle = atan2(q, i) + ((angleadj / 180.0) * M_PIl);

		double u = cos(angle) * mag;
		double v = sin(angle) * mag;

//		if (((line + 1) % 4) >= 2) u = -u;

		if (cline == (f_debugline + lineoffset)) {
//			cerr << i << ' ' << q << ' ' << atan2deg(q, i) << ' ' << mag << ' ' << angle << ' ' << u << ' ' << v << ' ' << atan2deg(v, u) << endl;
		}

                r = y + (1.13983 * v);
                g = y - (0.58060 * v) - (u * 0.39465);
                b = y + (u * 2.032);

		double m = brightness * 200 / 100;

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

int write_locs = -1;

const int nframes = 3;	// 3 frames needed for 3D buffer - for now

const int in_y = 610;
const int in_x = 1052;
const int in_size = in_y * in_x;

typedef struct cline {
	YIQ p[in_x];
} cline_t;

struct frame_t {
	uint16_t rawbuffer[in_x * in_y];

	double clpbuffer[3][in_y][in_x];
	double combk[3][in_y][in_x];
		
	cline_t cbuf[in_y];
};

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
	
		uint16_t output[in_x * in_y * 3];
		uint16_t BGRoutput[in_x * in_y * 3];
		uint16_t obuf[in_x * in_y * 3];
		
		uint16_t Goutput[in_x * in_y];
		uint16_t Flowmap[in_x * in_y];

		double aburstlev;	// average color burst

		cline_t tbuf[in_y];
		cline_t pbuf[in_y], nbuf[in_y];

		frame_t Frame[nframes];

		Filter *f_hpy, *f_hpi, *f_hpq;
		Filter *f_hpvy, *f_hpvi, *f_hpvq;

		void FilterIQ(cline_t cbuf[in_y], int fnum) {
			for (int l = 24; l < in_y; l++) {
				uint16_t *line = &Frame[fnum].rawbuffer[l * in_x];	
				bool invertphase = (line[0] == 16384);

				Filter f_i(f_colorlpi);
				Filter f_q(f_colorlpf_hq ? f_colorlpi : f_colorlpq);

				int qoffset = f_colorlpf_hq ? f_colorlpi_offset : f_colorlpq_offset;

				double filti = 0, filtq = 0;

				for (int h = 4; h < (in_x - 4); h++) {
					int phase = h % 4;
					
					switch (phase) {
						case 0: filti = f_i.feed(cbuf[l].p[h].i); break;
						case 1: filtq = f_q.feed(cbuf[l].p[h].q); break;
						case 2: filti = f_i.feed(cbuf[l].p[h].i); break;
						case 3: filtq = f_q.feed(cbuf[l].p[h].q); break;
						default: break;
					}

					if (l == (f_debugline + lineoffset)) {
						cerr << "IQF " << h << ' ' << cbuf[l].p[h - f_colorlpi_offset].i << ' ' << filti << ' ' << cbuf[l].p[h - qoffset].q << ' ' << filtq << endl;
					}

					cbuf[l].p[h - f_colorlpi_offset].i = filti; 
					cbuf[l].p[h - qoffset].q = filtq; 
				}
			}
		}
	
		// precompute 1D comb filter, used as a fallback for edges 
		void Split1D(int fnum)
		{
			for (int l = 24; l < in_y; l++) {
				uint16_t *line = &Frame[fnum].rawbuffer[l * in_x];	
				bool invertphase = false; // (line[0] == 16384);

				Filter f_1di(f_colorlpi);
				Filter f_1dq(f_colorlpq);
				int f_toffset = 8;

				for (int h = 4; h < (in_x - 4); h++) {
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

					Frame[fnum].clpbuffer[0][l][h] = tc1;
//					if (dim == 1) Frame[fnum].clpbuffer[0][l][h - f_toffset] = tc1f;

					Frame[fnum].combk[0][l][h] = 1;

					if (l == (f_debugline + lineoffset)) {
						cerr << h << ' ' << line[h - 4] << ' ' << line[h - 2] << ' ' << line[h] << ' ' << line[h + 2] << ' ' << line[h + 4] << ' ' << tc1 << ' ' << Frame[fnum].clpbuffer[0][l][h - f_toffset] << endl;
					}
				}
			}
		}
	
		int rawbuffer_val(int fr, int x, int y) {
			return Frame[fr].rawbuffer[(y * in_x) + x];
		}
	
		void Split2D(int f) 
		{
			for (int l = 24; l < in_y; l++) {
				uint16_t *pline = &Frame[f].rawbuffer[(l - 4) * in_x];	
				uint16_t *line = &Frame[f].rawbuffer[l * in_x];	
				uint16_t *nline = &Frame[f].rawbuffer[(l + 4) * in_x];	
		
				double *p1line = Frame[f].clpbuffer[0][l - 4];
				double *c1line = Frame[f].clpbuffer[0][l];
				double *n1line = Frame[f].clpbuffer[0][l + 4];
		
				// 2D filtering.  can't do top or bottom line - calced between 1d and 3d because this is
				// filtered 
				if ((l >= 4) && (l <= (in_y - 4))) {
					for (int h = 18; h < (in_x - 4); h++) {
						double tc1;
					
						double kp, kn;

						kp  = fabs(fabs(c1line[h]) - fabs(p1line[h])); // - fabs(c1line[h] * .20);
						kp += fabs(fabs(c1line[h - 1]) - fabs(p1line[h - 1])); 
						kp -= (fabs(c1line[h]) + fabs(c1line[h - 1])) * .10;
						kn  = fabs(fabs(c1line[h]) - fabs(n1line[h])); // - fabs(c1line[h] * .20);
						kn += fabs(fabs(c1line[h - 1]) - fabs(n1line[h - 1])); 
						kn -= (fabs(c1line[h]) + fabs(n1line[h - 1])) * .10;

						kp /= 2;
						kn /= 2;

						p_2drange = 45 * irescale;
						kp = clamp(1 - (kp / p_2drange), 0, 1);
						kn = clamp(1 - (kn / p_2drange), 0, 1);

						if (!f_adaptive2d) kn = kp = 1.0;

						double sc = 1.0;

						if (kn || kp) {	
							if (kn > (3 * kp)) kp = 0;
							else if (kp > (3 * kn)) kn = 0;

							sc = (2.0 / (kn + kp));// * max(kn * kn, kp * kp);
							if (sc < 1.0) sc = 1.0;
						} else {
							if ((fabs(fabs(p1line[h]) - fabs(n1line[h])) - fabs((n1line[h] + p1line[h]) * .2)) <= 0) {
								kn = kp = 1;
							}
						}
						

						tc1  = ((Frame[f].clpbuffer[0][l][h] - p1line[h]) * kp * sc);
						tc1 += ((Frame[f].clpbuffer[0][l][h] - n1line[h]) * kn * sc);
						tc1 /= (2 * 2);

						if (l == (f_debugline + lineoffset)) {
							//cerr << "2D " << h << ' ' << clpbuffer[l][h] << ' ' << p1line[h] << ' ' << n1line[h] << endl;
							cerr << "2D " << h << ' ' << ' ' << sc << ' ' << kp << ' ' << kn << ' ' << (pline[h]) << '|' << (p1line[h]) << ' ' << (line[h]) << '|' << (Frame[f].clpbuffer[0][l][h]) << ' ' << (nline[h]) << '|' << (n1line[h]) << " OUT " << (tc1) << endl;
						}	

						Frame[f].clpbuffer[1][l][h] = tc1;
						Frame[f].combk[1][l][h] = 1.0; // (sc * (kn + kp)) / 2.0;
					}
				}

				for (int h = 4; h < (in_x - 4); h++) {
					if ((l >= 2) && (l <= 502)) {
						Frame[f].combk[1][l][h] *= 1 - Frame[f].combk[2][l][h];
					}
					
					// 1D 
					Frame[f].combk[0][l][h] = 1 - Frame[f].combk[2][l][h] - Frame[f].combk[1][l][h];
				}
			}	
		}	
#if 0
		void Split3D(int f, bool opt_flow = false) 
		{
			for (int l = 24; l < in_y; l++) {
				uint16_t *line = &Frame[f].rawbuffer[l * in_x];	
		
				// shortcuts for previous/next 1D/pixel lines	
				uint16_t *p3line = &Frame[0].rawbuffer[l * in_x];	
				uint16_t *n3line = &Frame[2].rawbuffer[l * in_x];	
		
				// a = fir1(16, 0.1); printf("%.15f, ", a)
				Filter lp_3d({0.005719569452904, 0.009426612841315, 0.019748592575455, 0.036822680065252, 0.058983880135427, 0.082947830292278, 0.104489989820068, 0.119454688318951, 0.124812312996699, 0.119454688318952, 0.104489989820068, 0.082947830292278, 0.058983880135427, 0.036822680065252, 0.019748592575455, 0.009426612841315, 0.005719569452904}, {1.0});

				// need to prefilter K using a LPF
				double _k[in_x];
				for (int h = 4; (dim >= 3) && (h < (in_x - 4)); h++) {
					int adr = (l * in_x) + h;

					double __k = abs(Frame[0].rawbuffer[adr] - Frame[2].rawbuffer[adr]); 
					__k += abs((Frame[1].rawbuffer[adr] - Frame[2].rawbuffer[adr]) - (Frame[1].rawbuffer[adr] - Frame[0].rawbuffer[adr])); 

					if (h > 12) _k[h - 8] = lp_3d.feed(__k);
					if (h >= 836) _k[h] = __k;
				}
	
				for (int h = 4; h < (in_x - 4); h++) {
					if (opt_flow) {
						Frame[f].clpbuffer[2][l][h] = (p3line[h] - line[h]); 
					} else {
						Frame[f].clpbuffer[2][l][h] = (((p3line[h] + n3line[h]) / 2) - line[h]); 
						Frame[f].combk[2][l][h] = clamp(1 - ((_k[h] - (p_3dcore)) / p_3drange), 0, 1);
					}
					if (l == (f_debugline + lineoffset)) {
//						cerr << "3DC " << h << ' ' << k2 << ' ' << adj << ' ' << k[h] << endl;
					}
				
					if ((l >= 2) && (l <= 502)) {
						Frame[f].combk[1][l][h] = 1 - Frame[f].combk[2][l][h];
					}
					
					// 1D 
					Frame[f].combk[0][l][h] = 1 - Frame[f].combk[2][l][h] - Frame[f].combk[1][l][h];
				}
			}	
		}	
#endif
		void SplitIQ(int f) {
			double mse = 0.0;
			double me = 0.0;

			memset(Frame[f].cbuf, 0, sizeof(cline_t) * in_y); 

			for (int l = 24; l < in_y; l++) {
				double msel = 0.0, sel = 0.0;
				uint16_t *line = &Frame[f].rawbuffer[l * in_x];	
				bool invertphase = (line[0] == 16384);

//				if (f_neuralnet) invertphase = true;

				double si = 0, sq = 0;
				for (int h = 4; h < (in_x - 4); h++) {
					int phase = h % 4;
					double cavg = 0;

					cavg += (Frame[f].clpbuffer[2][l][h] * Frame[f].combk[2][l][h]);
					cavg += (Frame[f].clpbuffer[1][l][h] * Frame[f].combk[1][l][h]);
					cavg += (Frame[f].clpbuffer[0][l][h] * Frame[f].combk[0][l][h]);

					cavg /= 2;
					
					if (f_debug2d) {
						cavg = Frame[f].clpbuffer[1][l][h] - Frame[f].clpbuffer[2][l][h];
						msel += (cavg * cavg);
						sel += fabs(cavg);

						if (l == (f_debugline + lineoffset)) {
							cerr << "D2D " << h << ' ' << Frame[f].clpbuffer[1][l][h] << ' ' << Frame[f].clpbuffer[2][l][h] << ' ' << cavg << endl;
						}
					}

					if (!invertphase) cavg = -cavg;

					switch (phase) {
						case 0: si = cavg; break;
						case 1: sq = -cavg; break;
						case 2: si = -cavg; break;
						case 3: sq = cavg; break;
						default: break;
					}

					Frame[f].cbuf[l].p[h].y = line[h]; 
					if (f_debug2d) Frame[f].cbuf[l].p[h].y = ire_to_u16(50); 
					Frame[f].cbuf[l].p[h].i = si;  
					Frame[f].cbuf[l].p[h].q = sq; 
					
//					if (l == 240 ) {
//						cerr << h << ' ' << Frame[f].combk[1][l][h] << ' ' << Frame[f].combk[0][l][h] << ' ' << Frame[f].cbuf[l].p[h].y << ' ' << si << ' ' << sq << endl;
//					}

					if (f_bw) {
						Frame[f].cbuf[l].p[h].i = Frame[f].cbuf[l].p[h].q = 0;  
					}
				}

				if (f_debug2d && (l >= 6) && (l <= 500)) {
					cerr << l << ' ' << msel / (in_x - 4) << " ME " << sel / (in_x - 4) << endl; 
					mse += msel / (in_x - 4);
					me += sel / (in_x - 4);
				}
			}
			if (f_debug2d) {
				cerr << "TOTAL MSE " << mse << " ME " << me << endl;
			}
		}
		
		void DoCNR(int f, cline_t cbuf[in_y], double min = -1.0) {
			int firstline = (linesout == in_y) ? 0 : 23;
	
			if (nr_c < min) nr_c = min;
			if (nr_c <= 0) return;

			for (int l = firstline; l < in_y; l++) {
				YIQ hplinef[in_x + 32];
				cline_t *input = &cbuf[l];

				for (int h = 60; h <= (in_x - 4); h++) {
					hplinef[h].i = f_hpi->feed(input->p[h].i);
					hplinef[h].q = f_hpq->feed(input->p[h].q);
				}
				
				for (int h = 60; h < (in_x - 16); h++) {
					double ai = hplinef[h + 12].i;
					double aq = hplinef[h + 12].q;

//					if (l == (f_debugline + lineoffset)) {
//						cerr << "NR " << h << ' ' << input->p[h].y << ' ' << hplinef[h + 12].y << ' ' << ' ' << a << ' ' << endl;
//					}

					if (fabs(ai) > nr_c) {
						ai = (ai > 0) ? nr_c : -nr_c;
					}
					
					if (fabs(aq) > nr_c) {
						aq = (aq > 0) ? nr_c : -nr_c;
					}

					input->p[h].i -= ai;
					input->p[h].q -= aq;
//					if (l == (f_debugline + lineoffset)) cerr << a << ' ' << input->p[h].y << endl; 
				}
			}
		}
					
		void DoYNR(int f, cline_t cbuf[in_y], double min = -1.0) {
			int firstline = (linesout == in_y) ? 0 : 23;

			if (nr_y < min) nr_y = min;

			if (nr_y <= 0) return;

			for (int l = firstline; l < in_y; l++) {
				YIQ hplinef[in_x + 32];
				cline_t *input = &cbuf[l];

				for (int h = 40; h <= in_x; h++) {
					hplinef[h].y = f_hpy->feed(input->p[h].y);
				}
				
				for (int h = 40; h < in_x - 12; h++) {
					double a = hplinef[h + 12].y;

					if (l == (f_debugline + lineoffset)) {
						cerr << "NR " << l << ' ' << h << ' ' << input->p[h].y << ' ' << hplinef[h + 12].y << ' ' << ' ' << a << ' ' << endl;
					}

					if (fabs(a) > nr_y) {
						a = (a > 0) ? nr_y : -nr_y;
					}

					input->p[h].y -= a;
					if (l == (f_debugline + lineoffset)) cerr << a << ' ' << input->p[h].y << endl; 
				}
			}
		}
		
		void ToRGB(int f, int firstline, cline_t cbuf[in_y]) {
			// YIQ (YUV?) -> RGB conversion	

			double angle[in_y];

			// HACK!!!:  Need to figure out which phase we're in this frame
			for (int l = 10; l < in_y; l++) {
				double ang = 0;
				double i = 0, q = 0;

				for (int h = 25; h < 55; h++) {
					YIQ yiq = cbuf[l].p[h];

					i += yiq.i; q += yiq.q;
					if (l == (f_debugline + lineoffset)) 
						cerr << "BIQ " << l << ' ' << h << ' ' << yiq.q << ' ' << yiq.i << endl;
//					cerr << "BURST " << l << ' ' << h << ' ' << yiq.y << ' ' << yiq.i << ' ' << yiq.q << ' ' << ctor(yiq.i, yiq.q) << ' ' << atan2deg(yiq.q, yiq.i) << endl;
				}
				angle[l] = atan2deg(q, i);

				cerr << "angle of " << l << " is " << angle[l] << ' ' <<  endl; 
			}

			// XXX:  This is an awful hack, looking at only one of the stages to determine flip
			bool phase = angle[230] > 180;

			for (int l = firstline; l < in_y; l++) {
				double burstlev = 8; // Frame[f].rawbuffer[(l * in_x) + 1] / irescale;
				uint16_t *line_output = &output[(in_x * 3 * (l - firstline))];
				int o = 0;

				if (burstlev > 5) {
					if (aburstlev < 0) aburstlev = burstlev;	
					aburstlev = (aburstlev * .99) + (burstlev * .01);
				}
				if (f == f_debugline + lineoffset) cerr << "burst level " << burstlev << " mavg " << aburstlev << endl;

				double angleadj = 135 - angle[l];
	
				for (int h = 0; h < in_x; h++) {
					double adj2 = 0;

					double i = +(cbuf[l].p[h].i);
					double q = +(cbuf[l].p[h].q);

					double mag = ctor(i, q);
//					if (((line + 1) % 4) >= 2) angleadj -= 65;
//					if ((l % 4) >= 2) adj2 = +65;
					int rotate = l % 4;
//					if ((rotate == 0) || (rotate == 3)) adj2 = +65;
//					angleadj = 0;
					double angle = atan2(q, i) + (((angleadj + adj2) / 180.0) * M_PIl);

					if (l == (f_debugline + lineoffset))
						cerr << "A " << h << ' ' << cbuf[l].p[h].i << ' ' << cbuf[l].p[h].q << ' ' ;

					cbuf[l].p[h].i = cos(angle) * mag;
					cbuf[l].p[h].q = sin(angle) * mag;

					if (l == (f_debugline + lineoffset)) 
						cerr << cbuf[l].p[h].i << ' ' << cbuf[l].p[h].q << endl ;
				}

				for (int h = 0; h < in_x; h++) {
					RGB r;
					YIQ yiqp = cbuf[l - 2].p[h + 0];
					YIQ yiq = cbuf[l].p[h + 0];

//					yiq.i = (yiqp.i + yiq.i) / 1;
//					yiq.q = (yiqp.q + yiq.q) / 1;

					yiq.i *= (10 / aburstlev);
					yiq.q *= (10 / aburstlev);
					
					double i = yiq.i, q = yiq.q;

					int rotate = l % 4;
					bool flip = (rotate == 1) || (rotate == 2);
					if (phase) flip = !flip;

					if (flip) {
						yiq.i = -q;
						yiq.q = -i;
					}

					if (f_showk) {
						yiq.y = ire_to_u16(Frame[f].combk[dim - 1][l][h + 82] * 100);
//						yiq.y = ire_to_u16(((double)h / 752.0) * 100);
						yiq.i = yiq.q = 0;
					}

					if (l == (f_debugline + lineoffset)) {
						cerr << "YIQ " << h << ' ' << l << ' ' << l % 4 << ' ' << angle[l] << ' ' << atan2deg(yiq.q, yiq.i) << ' ' << yiq.y << ' ' << yiq.i << ' ' << yiq.q << endl;
					}

					cline = l;
					r.conv(yiq); // , 135 - ang, l);
					
					if (l == (f_debugline + lineoffset)) {
//						cerr << "RGB " << r.r << ' ' << r.g << ' ' << r.b << endl ;
						r.r = r.g = r.b = 0;
					}
	
					line_output[o++] = (uint16_t)(r.r); 
					line_output[o++] = (uint16_t)(r.g); 
					line_output[o++] = (uint16_t)(r.b); 
				}
			}
		}

		void OpticalFlow3D(cline_t cbuf[in_y]) {
			static Mat prev[2];
			static Mat flow[2];	
			static int fcount = 0;
			int fnum = 0;		
	
			const int cysize = 242;
			const int cxsize = in_x - 70;
	
			uint16_t fieldbuf[in_x * cysize];
			uint16_t flowmap[in_y][cxsize];

			memset(fieldbuf, 0, sizeof(fieldbuf));
			memset(flowmap, 0, sizeof(flowmap));

			int l, y;

			Mat pic;

			for (int field = 0; field < 2; field++) {
				for (y = 0; y < cysize; y++) {
					for (int x = 0; x < cxsize; x++) {
						fieldbuf[(y * cxsize) + x] = cbuf[23 + field + (y * 2)].p[70 + x].y;
					}
				}
				pic = Mat(242, cxsize, CV_16UC1, fieldbuf);
				if (fcount) calcOpticalFlowFarneback(pic, prev[field], flow[field], 0.5, 4, 60, 3, 7, 1.5, (fcount > 1) ? OPTFLOW_USE_INITIAL_FLOW : 0);
				prev[field] = pic.clone();
			}

			double min = p_3dcore;  // 0.0
			double max = p_3drange; // 0.5

			if (fcount) {
				for (y = 0; y < cysize; y++) {
					for (int x = 0; x < cxsize; x++) {
            					const Point2f& flowpoint1 = flow[0].at<Point2f>(y, x);  
	            				const Point2f& flowpoint2 = flow[1].at<Point2f>(y, x);  
							
						double c1 = 1 - clamp((ctor(flowpoint1.y, flowpoint1.x * 2) - min) / max, 0, 1);
						double c2 = 1 - clamp((ctor(flowpoint2.y, flowpoint2.x * 2) - min) / max, 0, 1);
			
						double c = (c1 < c2) ? c1 : c2;

						// HACK:  This goes around a 1-frame delay	
						Frame[1].combk[2][(y * 2)][70 + x] = c;
						Frame[1].combk[2][(y * 2) + 1][70 + x] = c;

						uint16_t fm = clamp(c * 65535, 0, 65535);
						flowmap[(y * 2)][0 + x] = fm;
						flowmap[(y * 2) + 1][0 + x] = fm;
					}
				}

				Mat fpic = Mat(in_y - 23, cxsize, CV_16UC1, flowmap);
				Mat rpic;
				resize(fpic, rpic, Size(1280,960));
	
//				imshow("comb", rpic);	
//				waitKey(f_oneframe ? 0 : 1);
			}
			fcount++; 
		}

		void DrawFrame(uint16_t *obuf, int owidth = 1052) {
			for (int y = 0; y < 576; y++) {
				for (int x = 0; x < owidth; x++) {
					BGRoutput[(((y * owidth) + x) * 3) + 0] = obuf[(((y * owidth) + x) * 3) + 2];
					BGRoutput[(((y * owidth) + x) * 3) + 1] = obuf[(((y * owidth) + x) * 3) + 1];
					BGRoutput[(((y * owidth) + x) * 3) + 2] = obuf[(((y * owidth) + x) * 3) + 0];
				}
			}
				
			Mat pic = Mat(576, owidth, CV_16UC3, BGRoutput);
			Mat rpic;

			resize(pic, rpic, Size(1280,960));

			imshow("comb", rpic);	
			waitKey(f_oneframe ? 0 : 1);
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

		void WriteFrame(uint16_t *obuf, int owidth = 1052, int fnum = 0) {
			cerr << "WR" << fnum << endl;
			if (!f_writeimages) {
				if (!f_write8bit) {
					write(ofd, obuf, (owidth * linesout * 3) * 2);
				} else {
					uint8_t obuf8[owidth * linesout * 3];	

					for (int i = 0; i < (owidth * linesout * 3); i++) {
						obuf8[i] = obuf[i] >> 8;
					}
					write(ofd, obuf8, (owidth * linesout * 3));
				}		
			} else {
				char ofname[512];
				
				sprintf(ofname, "%s%d.rgb", image_base, fnum); 
				cerr << "W " << ofname << endl;
				ofd = open(ofname, O_WRONLY | O_CREAT, S_IRUSR | S_IWUSR | S_IROTH);
				write(ofd, obuf, (owidth * linesout * 3) * 2);
				close(ofd);
			}

			if (f_monitor) {
				DrawFrame(obuf, owidth);
			}	

			if (f_oneframe) exit(0);
			frames_out++;
		}

		void AdjustY(int f, cline_t cbuf[in_y]) {
			int firstline = (linesout == in_y) ? 0 : 32;
			// remove color data from baseband (Y)	
			for (int l = firstline; l < in_y; l++) {
				bool invertphase = (Frame[f].rawbuffer[l * in_x] == 16384);

				for (int h = 2; h < in_x; h++) {
					double comp;	
					int phase = h % 4;

					YIQ y = cbuf[l].p[h + 2];

					switch (phase) {
						case 0: comp = y.i; break;
						case 1: comp = -y.q; break;
						case 2: comp = -y.i; break;
						case 3: comp = y.q; break;
						default: break;
					}

					if (invertphase) comp = -comp;
					y.y += comp;

					cbuf[l].p[h + 0] = y;
				}
			}

		}

		// buffer: in_xxin_y uint16_t array
		void Process(uint16_t *buffer, int dim = 2)
		{
			int firstline = (linesout == in_y) ? 0 : 32;
			int f = (dim == 3) ? 1 : 0;

			cerr << "P " << f << ' ' << dim << endl;

			memcpy(&Frame[2], &Frame[1], sizeof(frame_t));
			memcpy(&Frame[1], &Frame[0], sizeof(frame_t));
			memset(&Frame[0], 0, sizeof(frame_t));

			memcpy(Frame[0].rawbuffer, buffer, (in_x * in_y * 2));

			Split1D(0);
			if (dim >= 2) Split2D(0); 
			SplitIQ(0);
		
			// copy VBI	
			for (int l = 0; l < 24; l++) {
				uint16_t *line = &Frame[0].rawbuffer[l * in_x];	
					
				for (int h = 4; h < (in_x - 4); h++) {
					Frame[0].cbuf[l].p[h].y = line[h]; 
				}
			}
	#if 0	
			if (dim >= 3) {
				if (f_opticalflow && (framecount >= 1)) {
					memcpy(tbuf, Frame[0].cbuf, sizeof(tbuf));	
					AdjustY(0, tbuf);
					DoYNR(0, tbuf, 5);
					DoCNR(0, tbuf, 2);
					OpticalFlow3D(tbuf);
				}

				if (framecount < 2) {
					framecount++;
					return;
				}

				Split3D(f, f_opticalflow); 
			}
#endif
			SplitIQ(f);

			memcpy(tbuf, Frame[f].cbuf, sizeof(tbuf));	

			AdjustY(f, tbuf);
			if (f_colorlpf) FilterIQ(tbuf, f);
			DoYNR(f, tbuf);
			DoCNR(f, tbuf);
			ToRGB(f, firstline, tbuf);
	
			PostProcess(f);
			framecount++;

			return;
		}
		
		int PostProcess(int fnum) {
			int fstart = -1;
			uint16_t *fbuf = Frame[fnum].rawbuffer;

			int out_x = f_wide ? in_x : 744;
			int roffset = f_wide ? 0 : 78;

			if (!f_pulldown) {
				fstart = 0;
			} else if (f_oddframe) {
				for (int i = 1; i < linesout; i += 2) {
					memcpy(&obuf[out_x * 3 * i], &output[(in_x * 3 * i) + (roffset * 3)], out_x * 3 * 2); 
				}
				WriteFrame(obuf, out_x, framecode);
				f_oddframe = false;		
			}

			uint16_t flags = fbuf[7];

			cerr << "flags " << hex << flags << dec << endl;
//			if (flags & FRAME_INFO_CAV_ODD) fstart = 1;
			if (flags & FRAME_INFO_WHITE_ODD) fstart = 1;
			else if (flags & FRAME_INFO_WHITE_EVEN) fstart = 0;

			framecode = (fbuf[8] << 16) | fbuf[9];

			cerr << "FR " << framecount << ' ' << fstart << endl;
			if (!f_pulldown || (fstart == 0)) {
				for (int i = 0; i < linesout; i++) {
					memcpy(&obuf[out_x * 3 * i], &output[(in_x * 3 * i) + (roffset * 3)], out_x * 3 * 2); 
				}
				WriteFrame(obuf, out_x, framecode);
			} else if (fstart == 1) {
				for (int i = 0; i < linesout; i += 2) {
					memcpy(&obuf[out_x * 3 * i], &output[(in_x * 3 * i) + (roffset * 3)], out_x * 3 * 2); 
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
	
unsigned short inbuf[in_x * in_y * 2];
const int bufsize = in_x * in_y * 2;

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1, tproc = 0;
	unsigned char *cinbuf = (unsigned char *)inbuf;
	int c;

	char out_filename[256] = "";

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;
	
	while ((c = getopt(argc, argv, "WQLakN:tFc:r:R:m8OwvDd:Bb:I:w:i:o:fphn:l:")) != -1) {
		switch (c) {
			case 'W':
				f_wide = !f_wide;
				break;
			case 'L':
				f_colorlpf = !f_colorlpf;
				break;
			case 'Q':
				f_colorlpf_hq = !f_colorlpf_hq;
				break;
			case 'F':
				f_opticalflow = false;
				break;
			case 'a':
				f_adaptive2d = !f_adaptive2d;
				break;
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
			case 'N':
				sscanf(optarg, "%lf", &nr_c);
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
				sscanf(optarg, "%d", &f_debugline);
				break;
			case 'm':
				f_monitor = true;
				break;
			case 't': // training mode - write images as well
				f_training = true;
				f_writeimages = true;	
				dim = 3;
				break;
			case 'k':
				f_showk = true;
				break;
			default:
				return -1;
		} 
	} 

	if (f_monitor) {
		namedWindow("comb", WINDOW_AUTOSIZE);
	}

	if (f_opticalflow) {
		if (p_3dcore < 0) p_3dcore = 0;
		if (p_3drange < 0) p_3drange = 0.5;
	} else {
		if (p_3dcore < 0) p_3dcore = 1.25;
		if (p_3drange < 0) p_3drange = 5.5;
		p_3dcore *= irescale;
		p_3drange *= irescale;
		p_3d2drej *= irescale;
	}

	p_2dcore = 0 * irescale;
	p_2drange = 10 * irescale;

	black_u16 = ire_to_u16(black_ire);

	nr_y *= irescale;
	nr_c *= irescale;

	if (!f_writeimages && strlen(out_filename)) {
		ofd = open(image_base, O_WRONLY | O_CREAT);
	}

	cout << std::setprecision(8);

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

